---
create_time: 2026-07-07 16:27:38
status: done
prompt: sdd/prompts/202607/stuck_pending_tool_calls.md
---
# Fix never-completing tool calls in the SLOW TOOL CALLS panel

## Problem

The "SLOW TOOL CALLS" section of the agent metadata panel (Agents tab, `sase ace` TUI) shows `Read` tool calls that stay
in the "running" state forever (e.g. 18m+ for a `Read` that in reality finished in under a second). The duration keeps
ticking as long as the agent family is active.

## Root-cause diagnosis (confirmed with evidence)

### How a call becomes permanently "running"

The Tools/slow-calls reader (`src/sase/ace/tui/tools/`) pairs `ToolUse` (start) rows with `ToolResult` (end) rows from
`tool_calls.jsonl` by `tool_use_id` (`_parser.py::collapse_tool_use_pairs`). An orphan `ToolUse` row with no matching
`ToolResult` row stays `status="pending"`, and `slow.py::select_slow_tool_calls` renders a pending entry of an active
agent as "running" with `duration = now - start`, forever.

### Why the `ToolResult` rows are missing: partial-line shredding of large stream-json events

Inspecting the artifact for one affected run
(`~/.sase/projects/gh_sase-org__sase/artifacts/ace-run/202607/07/20260707155434/tool_calls.jsonl`) shows 37 `ToolUse`
rows but only 35 `ToolResult` rows. The two orphans are exactly the stuck calls from the screenshot:

- a `Read` of a **615 KB PNG screenshot** (base64-encoded in the stream → multi-MB JSON line), and
- a `Read` of a **36 KB Python file** (stream-json duplicates file content in `message.content` and the
  `tool_use_result` envelope → ~75 KB+ JSON line).

Every call whose result was small paired fine. The discriminator is the size of the `user` tool-result event line
relative to the OS pipe buffer (64 KB default on Linux).

Mechanism, in `src/sase/llm_provider/_subprocess_stream.py::stream_json_lines`:

1. stdout is put in **non-blocking** mode and read with `process.stdout.readline()`.
2. When a stream-json line is larger than the bytes currently available in the pipe (always true at some point for large
   tool results, because the CLI's writes race the reader), non-blocking `readline()` returns a **partial line
   fragment** instead of blocking for the newline.
3. Each fragment is passed to the per-runtime line handler (`_subprocess_claude.py::_process_json_line` and the
   codex/qwen/opencode equivalents), where `json.loads` fails and the fragment is **silently dropped**
   (`except json.JSONDecodeError: return`).
4. The dropped event is precisely the `user` event carrying the `tool_result` block, so `append_claude_tool_call_event`
   never writes the `ToolResult` row.

**Reproduced** against the real `stream_json_lines`: a child process that dribbles a single 400 KB JSON line in 50 KB
chunks yields 9 undecodable fragments — the event is lost entirely. A fast producer that writes the same line in one
shot is often _not_ split, which explains why the bug is intermittent and correlates with large results (images, big
files) streaming over the network.

### Collateral damage (same drop path)

Any oversized stream-json event can be lost the same way: large `assistant` text events (missing `live_reply.md`
content), and `result`/`error` events (lost usage totals / error diagnostics). The fix below addresses all of these at
once.

## Fix design

### Step 1 — Root cause: line-buffer non-blocking reads in `stream_json_lines`

In `src/sase/llm_provider/_subprocess_stream.py`, keep a per-stream pending buffer and only dispatch **complete** lines
to `handle_stdout_line`:

- Append each `readline()` chunk to the buffer; dispatch and clear it only when the chunk ends with `"\n"` (non-blocking
  `readline()` never returns past a newline, so a returned chunk either completes a line or is an EAGAIN fragment).
- In the post-exit drain path (after `process.poll() is not None`), apply the same buffering and flush any non-empty
  remainder at EOF so a final unterminated line is still delivered.
- stderr needs no correctness change (fragments are concatenated via `"".join` and printed with `end=""`), but the
  stdout buffering must not disturb the existing stderr handling.

This is the shared loop used by the claude, codex, qwen, and opencode runners, so all stream-json runtimes are fixed
uniformly (the agy runtime reads trajectory files, not this loop, and is unaffected). Memory cost is bounded by the
largest single line (a few MB worst case), which the process already materializes today.

### Step 2 — Observability: stop dropping undecodable lines silently

In the per-runtime `_process_json_line` handlers, record a bounded diagnostic (reason + length + short preview) via the
existing `append_tool_call_collector_diagnostic` / `tool_calls_writer_errors.jsonl` machinery when a stdout line fails
`json.loads`, capped to a small number of records per run to avoid spam from non-JSON banner output. Any future event
loss becomes visible instead of silent.

### Step 3 — Reconcile provably-orphaned pending rows in the reader

Historical artifacts (including the runs on screen) already contain orphan `ToolUse` rows, and rare future losses (e.g.
a runtime killed mid-call) remain possible. Rather than filtering these out of the panel, reclassify them accurately
using a protocol invariant:

> Within one logical stream — same `(runtime, session_id, parent_tool_use_id)` — a runtime cannot emit a **new assistant
> message** until every earlier tool call has received its result. So a pending `ToolUse` is provably orphaned once a
> later `ToolUse` with a **different `message_id`** exists in the same stream.

Implementation sketch:

- Parse `message_id` (already present in schema-v2 records) into `ToolCallEntry`.
- After `collapse_tool_use_pairs` in `src/sase/ace/tui/tools/_parser.py`, run a reconciliation pass: a still-pending
  `ToolUse` that is superseded by a later assistant message in its stream gets a new derived status (e.g.
  `"incomplete"`) and a `completed_at` bound equal to that later message's `recorded_at`.
- Conservative by design: rows without `message_id`/`session_id` are left untouched, and results from **sibling calls in
  the same assistant message** do not orphan a pending call (a genuinely long-running parallel tool call must keep
  ticking).
- Display: `slow.py::select_slow_tool_calls` maps the new status to the existing `did_not_complete` presentation
  (bounded duration, "did not complete" label) instead of the ticking "running" state; `tools_panel.py` gets an
  icon/style mapping for the new status; `cache.py::cached_tool_calls_have_pending` keeps returning `False` for
  reconciled rows so the slow-call tick loop stops refreshing them.

This keeps the panel honest: the two stuck reads from the screenshot will render as "did not complete" (true — their
results were lost) rather than "running" or being hidden.

### Explicitly rejected: filtering stuck calls out of the panel

Filtering would hide real data-loss signals and leave `tool_calls.jsonl` wrong. The root cause is fixable at the stream
layer, and reconciliation (Step 3) handles pre-existing artifacts truthfully.

## Tests

- `tests/llm_provider/` — `stream_json_lines` regression tests:
  - deterministic fake-process test (scripted partial `readline()` chunks, patched `select`, matching the existing test
    style in `test_subprocess_utf8_decode.py`): fragments of one large JSON line are reassembled and dispatched exactly
    once;
  - end-to-end pipe test with a dribbling child process (the repro): all events survive, including a trailing line
    without a newline;
  - drain-path test: data still buffered when the process exits is flushed.
- `tests/llm_provider/` — handler test: an undecodable line writes a bounded collector diagnostic.
- `tests/ace/tui/tools/` — parser reconciliation tests:
  - orphan `ToolUse` superseded by a later assistant message → status `"incomplete"` with bounded `completed_at`;
  - pending call whose _sibling_ (same `message_id`) has a result → stays `pending`;
  - rows missing `message_id` → untouched.
- `tests/ace/tui/tools/test_slow_selection.py` — `"incomplete"` entries render as `did_not_complete` with a bounded
  duration and never tick as "running".
- Full `just check` (lint + mypy + tests, including PNG visual snapshots) before finalizing.

## Affected code (all Python in this repo; no sase-core changes)

- `src/sase/llm_provider/_subprocess_stream.py` — line buffering (root fix).
- `src/sase/llm_provider/_subprocess_claude.py`, `_subprocess_codex.py`, `_subprocess_qwen.py`,
  `_subprocess_opencode.py` — undecodable-line diagnostics.
- `src/sase/ace/tui/tools/_entry.py`, `_parser.py`, `_constants.py`, `slow.py`, `cache.py`,
  `src/sase/ace/tui/widgets/tools_panel.py` — `message_id` parsing, orphan reconciliation, and `"incomplete"` status
  display.

This is runner/reader glue and presentation state, not shared domain behavior, so it stays on the Python side of the
Rust core boundary.

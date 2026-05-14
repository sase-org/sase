---
create_time: 2026-05-14 19:42:52
status: done
prompt: sdd/prompts/202605/tools_panel_missing_calls.md
---
# Tools Panel Not Showing All Tool Calls — Root Cause + Fix Plan

## Problem

The "Tools" detail panel on the `sase ace` Agents tab is supposed to render the timeline of every tool call a Claude
agent makes, but in practice it shows nothing (or close to nothing) for real runs. A scan of
`~/.sase/projects/*/artifacts/ace-run/*/` confirms it empirically: across recent Claude agent runs there is **not a
single `tool_calls.jsonl` file**, and no `tool_calls_writer_errors.jsonl` either. The capture pipeline is silently
producing zero output.

This plan diagnoses the two compounding root causes, picks the right fix, and lays out the implementation and test work
to make the panel correctly reflect every tool call a Claude agent makes.

## Background — How the Capture Pipeline Is Wired Today

The Tools panel design (Strategy B from `sdd/research/202605/claude_tool_calls_panel_hooks.md`) intentionally avoids
installing Claude hooks. Instead the Claude CLI is invoked with `--include-hook-events`, hook lifecycle events arrive
inline on the existing `--output-format stream-json` pipe, and SASE captures them to a per-phase
`<SASE_ARTIFACTS_DIR>/tool_calls.jsonl` artifact, which the TUI reader (`src/sase/ace/tui/tools/reader.py`) aggregates
and renders via `AgentToolsPanel` (`src/sase/ace/tui/widgets/tools_panel.py`).

The argv at `src/sase/llm_provider/claude.py:183` already includes `--include-hook-events`. The stream parser at
`src/sase/llm_provider/_subprocess_claude.py:91` unconditionally forwards every parsed JSON event into
`append_claude_tool_call_event`. The writer (`src/sase/llm_provider/_tool_calls.py:36`) is meant to recognize the four
useful hook events (`PostToolUse`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`), normalize them, and append a
JSONL line.

So plumbing is in place end to end. Yet `tool_calls.jsonl` never gets created in practice.

## Root Causes

### Root Cause 1 (primary, deterministic): Wrong field name on the wire

The writer's normalizer at `_tool_calls.py:55` reads:

```python
event_name = event.get("hook_event_name")
if (
    not isinstance(event_name, str)
    or event_name not in SUPPORTED_CLAUDE_HOOK_EVENTS
):
    return None
```

A live capture from
`claude -p --verbose --output-format stream-json --include-hook-events --dangerously-skip-permissions` shows the actual
on-the-wire shape is **different from what the tests assume**:

```json
{"type":"system","subtype":"hook_started",
 "hook_id":"f5c2cb08-…","hook_name":"SessionStart:startup","hook_event":"SessionStart", …}

{"type":"system","subtype":"hook_response",
 "hook_id":"f5c2cb08-…","hook_name":"SessionStart:startup","hook_event":"SessionStart",
 "output":"","stdout":"","stderr":"","exit_code":0,"outcome":"success", …}
```

Claude emits the event name in the field `"hook_event"` — not `"hook_event_name"`. The fixture in
`tests/llm_provider/test_usage_parsing.py` (and the writer's tests in `tests/test_tool_calls_writer.py` style) uses the
documented hook-input field name (`hook_event_name`), which is what a hook **command** would see on stdin if SASE
installed one — but the in-band stream-json envelope uses a different field. Because the writer's check finds no
`hook_event_name`, **every event is silently rejected** with `return None`. Returning `None` is not raised as an
exception, so no diagnostic line ever lands in `tool_calls_writer_errors.jsonl` either. That is exactly the observed
symptom: `tool_calls.jsonl` never created, no error file, no signal anywhere.

There is also an envelope mismatch: hook events arrive as `type: "system"` with `subtype: "hook_started"` /
`subtype: "hook_response"`. There is no event whose top-level shape matches the test fixtures the writer was built
against. The two `hook_started` / `hook_response` events for one logical hook invocation also mean the writer would
double-count if we only fixed the field name without also handling subtype.

### Root Cause 2 (structural, even more important): `--include-hook-events` is _not_ a tool-call source

Even after fixing field names, `--include-hook-events` will _not_ surface most tool calls. The flag emits lifecycle
events **for hooks the user has actually registered**. In the live capture above, the only hook events emitted were
`SessionStart` (one matcher: `startup`) and `Stop` — because those are the only hooks the user has on disk. The Bash
tool clearly ran (it appears in the assistant and user messages, with `tool_use_id="toolu_01PBs…"` and a populated
`tool_result`), yet **no `PostToolUse`, `PostToolUseFailure`, or `PostToolBatch` event was emitted at all**. The Claude
CLI does not synthesize a hook lifecycle event for a hook the user has not registered.

This invalidates the foundational assumption of the original research doc, which read `--include-hook-events` as
emitting hook events for every tool call. Reality: hook lifecycle events fire only for registered hooks, so the Tools
panel as built can only ever show tool calls in two scenarios:

1. The user has happened to install a global `PostToolUse` hook (`disableAllHooks` and `allowManagedHooksOnly` make this
   even more fragile), in which case after fixing Root Cause 1 we get some coverage.
2. SASE itself installs the hook, which Strategy B explicitly was chosen to avoid.

So the strategy needs to change. Fortunately, the same stream-json output already carries every tool call inline, in
canonical Anthropic Messages API shape, **independent of any hook configuration**:

```json
{"type":"assistant","message":{"content":[
   {"type":"tool_use","id":"toolu_01PBs…","name":"Bash",
    "input":{"command":"ls -la /tmp | head -3 && echo done","description":"List /tmp contents and echo done"}}
]}, "parent_tool_use_id":null, "session_id":"…", "uuid":"…"}

{"type":"user","message":{"role":"user","content":[
   {"tool_use_id":"toolu_01PBs…","type":"tool_result",
    "content":"[/tmp/tmpnqlf82lw: No such file or directory (os error 2)]…\ndone","is_error":false}
]}, "parent_tool_use_id":null, "session_id":"…", "uuid":"…",
 "tool_use_result":{"stdout":"…","stderr":"","interrupted":false,"isImage":false,"noOutputExpected":false}}
```

These two events together carry everything the panel needs: `tool_name`, structured `tool_input`, `tool_use_id`,
structured Output via top-level `tool_use_result` (same shape as `PostToolUse.tool_response`), `is_error` /
`interrupted` for status, the assistant message id, parent tool use id for subagent grouping, session id, and turn
ordering via the surrounding event sequence. Subagents (`Task`/`Agent`) also surface here: the parent's assistant event
carries a `tool_use` for `Task`, and the child agent's tool calls arrive in subsequent `assistant`/`user` events with
`parent_tool_use_id` set.

Practically: the canonical source of truth for "every tool call this Claude agent made" is the in-band
`assistant.content[].tool_use` + `user.content[].tool_result` (plus `tool_use_result`) pairs, **not** hook events. Hook
events are useful only as supplemental signal (durations, subagent boundaries, permission denials, lifecycle hooks the
user happens to have installed).

## What "Showing All Tool Calls" Should Mean

Each tool call should appear in the panel exactly once with:

- tool name (built-in or `mcp__<server>__<tool>`)
- `tool_use_id`
- a redacted, bounded `tool_input_summary`
- a redacted, bounded `tool_response_summary` derived from the structured `tool_use_result`
- status: `success`, `failure` (when `is_error` is true or `tool_use_result.interrupted`), `interrupted`
- the assistant message timestamp / session id / parent_tool_use_id for subagent grouping
- optionally `duration_ms` if a `PostToolUse` hook event is observed for that `tool_use_id`

Calls that are still in flight (no `tool_result` yet) should not break the panel; they can either be omitted or shown
with status `pending`. Failures must appear, including:

- explicit `tool_result.is_error: true` content blocks
- `tool_use_result.interrupted: true` (e.g. timeouts, cancellation)
- `tool_use_result.is_error` or `success: false` where the structured form carries it

Subagent (`Task`/`Agent`) calls should be visible at the parent level by default, with child calls reachable through
`parent_tool_use_id` grouping in a later iteration.

## Plan

### Phase 1 — Replace the hook-event capture with assistant/user event capture

Rebuild `append_claude_tool_call_event` (or replace it with a new entry point and remove the old) so the writer:

1. Accepts the raw stream-json event from `_subprocess_claude._process_json_line`.
2. For `type == "assistant"`: walks `message.content` and for each `type == "tool_use"` block writes a
   "tool-call-started" row with a sentinel like `event: "ToolUse"` (runtime-neutral), capturing `tool_use_id`,
   `tool_name`, redacted `tool_input_summary`, `parent_tool_use_id`, `session_id`, and the assistant message id / uuid
   for ordering.
3. For `type == "user"`: walks `message.content` for each `type == "tool_result"` and pairs it with the matching
   `tool_use_id` from earlier in the run. Uses the top-level `tool_use_result` to derive a redacted
   `tool_response_summary` (same per-tool branching the writer already has for Bash / Read / Grep / Glob / Write / Edit
   / MultiEdit / WebFetch / WebSearch / Task / Agent). Derives status from `is_error` and `tool_use_result.interrupted`.
   Writes a "tool-call-completed" row.

This is a two-record-per-call pattern (started + completed), keyed by `tool_use_id`, so partial captures (interrupted
agent, killed subprocess, missing `tool_result`) still leave the started row visible. The reader can collapse matching
pairs into a single timeline entry; that logic belongs in the reader, not the writer.

Schema impact:

- Bump `schema_version` to `2`. The reader keeps reading v1 records (back-compat for existing artifacts) but the writer
  only emits v2 going forward.
- New `event` values: `"ToolUse"` (start) and `"ToolResult"` (end). Keep `"PostToolUse"`, `"PostToolUseFailure"`,
  `"SubagentStart"`, `"SubagentStop"` as valid v2 event names so we can still record them when they fire (see Phase 2).
  Update `derive_tool_call_status` to know about the new event names.
- Add `parent_tool_use_id` to the record (already present in the dataclass via an additional optional field).

### Phase 2 — Keep limited hook-event capture as a supplemental signal

Now that the field name on the wire is known to be `hook_event` (not `hook_event_name`) and the events arrive as
`type: "system"` with `subtype` in `{hook_started, hook_response}`, do the _much_ smaller version of the original
strategy:

- Detect `type == "system"` with `subtype == "hook_response"` and `hook_event` in
  `{"PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop"}`.
- Use it only to _augment_ an existing row keyed by `tool_use_id` (set `duration_ms`, refine status to
  `interrupted`/`failure`, fill `agent_id`/`agent_type` for subagents). If the matching row doesn't exist yet (the user
  did install a `PostToolUse` hook and we somehow missed the assistant/user pair), still write the hook-event row
  standalone so we are no worse than today.
- Ignore `subtype == "hook_started"` for tool events to avoid double-counting. For `SubagentStart`/`SubagentStop` the
  `_started` variant _is_ the boundary marker we want, so handle those two specifically.

This is the right way to spend hook-event coverage: as enrichment, not as the only source.

### Phase 3 — Reader and panel updates

- `reader.py`: extend `KNOWN_STATUSES` if needed, teach `derive_tool_call_status` about `ToolUse`/`ToolResult`, and
  collapse matching `ToolUse`/`ToolResult` pairs (same `tool_use_id`, same `session_id`) into a single `ToolCallEntry`
  for display. Keep raw rows available for diagnostics but the panel should show one row per call.
- `tools_panel.py`: no schema-shape changes required if the entry shape stays the same. Verify the cache key still
  changes when new entries arrive (so the panel refreshes mid-run).
- Add `parent_tool_use_id` rendering only as a follow-up; for the MVP fix, all tool calls (parent and child) show as
  flat rows in arrival order, which is already a strict improvement over "nothing".

### Phase 4 — Tests

The current `tests/test_tool_calls_writer.py`-style fixtures pass the documented hook-input shape, which is _not_ what
the stream emits. Replace and extend:

1. **New writer tests** in `tests/llm_provider/test_tool_calls_writer.py`:
   - Feed real-shape `type: "assistant"` events with `tool_use` blocks for Bash, Read, Edit, MultiEdit, Write, WebFetch,
     WebSearch, Task, Grep, Glob, an MCP tool, and an unknown tool. Assert one v2 `ToolUse` record per `tool_use` block
     with the correct summaries and redactions.
   - Feed paired `type: "user"` events with `tool_result` + top-level `tool_use_result`. Assert one v2 `ToolResult`
     record per result, with correct status derivation including `is_error: true` and
     `tool_use_result.interrupted: true`.
   - Feed `type: "system" subtype: "hook_response" hook_event: "PostToolUse"`. Assert it augments an existing
     `tool_use_id` and writes nothing duplicate, or stands alone if no prior row exists.
   - Feed `SubagentStart`/`SubagentStop` and assert subagent rows.
   - Feed garbage (non-mapping, missing fields, bad subtype) and assert silent ignore with no
     `tool_calls_writer_errors.jsonl` line (since these are well-formed non-matches, not errors).
   - Cover `SASE_TOOL_LOG_FULL=1` raw-capture mode.

2. **Stream integration test** at `tests/llm_provider/test_subprocess_claude.py`:
   - Drive `_process_json_line` end-to-end with a recorded sequence captured from a real Claude run (see "Fixture
     capture" below). Assert the resulting `tool_calls.jsonl` lines match a golden file.

3. **Reader tests** at `tests/ace/tui/tools/test_reader.py`:
   - Feed v2 mixed `ToolUse`/`ToolResult` rows and assert one merged entry per pair, correct status, correct ordering,
     and graceful handling of orphan `ToolUse` (no matching result yet).
   - Feed mixed v1 + v2 lines in the same file (back-compat).

4. **Panel test** at `tests/ace/tui/widgets/test_tools_panel.py`:
   - Add a "tool fires successfully" case asserting the row shows up. The existing test only covers absent/empty states;
     that is exactly the gap that let this regression ship silently.

5. **Live smoke test**:
   - Add a `tests/manual/`-style script (not in CI) that invokes the Claude CLI with the SASE argv against a scratch
     prompt and asserts that `tool_calls.jsonl` is non-empty. Useful for future flag-format drift.

### Phase 5 — Fixture capture and developer aid

Add a small script `scripts/capture_claude_stream.py` (or equivalent) that runs Claude with the SASE argv, captures the
stream-json line-by-line, and writes it to a fixture file. This pays for itself the next time Claude changes the wire
format. Use it once during Phase 4 to seed the stream integration golden file.

### Phase 6 — Documentation and decisions to record

- Update `sdd/research/202605/claude_tool_calls_panel_hooks.md` with an addendum: "Strategy B (as originally written) is
  insufficient on its own — `--include-hook-events` only surfaces hooks the user has registered. The capture layer reads
  `tool_use`/`tool_result` from the inline stream and uses `--include-hook-events` purely for enrichment."
- Update or remove the design rationale text in `_tool_calls.py:1-7` accordingly.
- Note in `memory/short/` (if appropriate, with user approval) that the Tools panel data source is the stream-json
  `assistant`/`user` blocks, not hook events. (Per the AGENTS.md rule, only update memory files with user approval.)

### Phase 7 — Cross-runtime parity (out of scope for this fix, but flagged)

Gemini, Codex, and Qwen each have their own stream-json mode. The capture pattern (assistant tool_use → user
tool_result, matched by id) is conceptually portable but the wire shapes differ. This plan keeps the writer
Claude-specific; runtime parity is a follow-up that belongs alongside the same wire-format reconnaissance for each
runtime.

## Risks / Decisions

- **Double-counting in flight**: emitting both a `ToolUse` and `ToolResult` row keeps partial state visible but requires
  the reader to dedupe. Alternative: hold the started row in memory and only flush on result. The two-record approach is
  safer because a killed subprocess (interrupt, crash, SIGKILL) still leaves a record on disk; this is a deliberate
  trade-off worth keeping.
- **Tool-input redaction**: the redaction policy already exists; we are reusing it. No new redaction surface.
- **Schema v2 vs v1**: keep the reader compatible with v1 indefinitely. The writer never emits v1 again, so ongoing
  maintenance is one branch in the reader, not two.
- **No memory file changes** in this plan unless explicitly approved by the user (per `AGENTS.md`).
- **PostToolBatch and PermissionDenied** continue to be out of scope for the MVP; they are not necessary once the
  primary source is the assistant/user pair.
- **Per-phase artifact aggregation** is already handled by `discover_related_tool_artifact_dirs`; nothing changes in
  that area.

## Acceptance Criteria

- For a real Claude agent run, `tool_calls.jsonl` is non-empty and contains one merged entry per tool call the agent
  made, observed in the Tools panel and confirmed by grepping the artifact file for the issuing `tool_use_id`s shown in
  the assistant transcript.
- A run that interrupts mid-tool still leaves a `ToolUse` row visible in the panel even without a matching `ToolResult`.
- Subagent calls (`Task`/`Agent`) show as a row in the parent's panel by default.
- `just check` passes (lint, mypy, tests).
- Manual smoke: stop into the Agents tab on a live run and confirm tool calls scroll in as they happen.

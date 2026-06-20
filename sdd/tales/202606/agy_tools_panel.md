---
create_time: 2026-06-20 10:02:16
status: done
prompt: sdd/prompts/202606/agy_tools_panel.md
---
# Plan: Tools Panel support for the Antigravity (`agy`) provider

## Goal / product context

The new Antigravity (`agy`) CLI provider currently runs as a plain-stdout provider: it writes `live_reply.md`, returns
`usage=None`, and emits **no** `tool_calls.jsonl`. As a result the ACE Agents-tab **Tools panel** is empty for every
`agy` run, while Claude/Codex/Qwen/OpenCode runs show a rich tool timeline (Bash/Read/Write/Edit calls, status,
durations, previews).

This plan adds Tools panel support for `agy` by giving the provider a trustworthy source of tool-use / tool-result
events and normalizing them into SASE's **existing** provider-neutral `tool_calls.jsonl` schema. The change is entirely
**producer-side**: no TUI/reader changes.

The approach follows the recommendation in `sdd/research/202606/agy_tools_panel_support_consolidated.md`: a guarded,
post-run extractor that reads Antigravity's local conversation trajectory database after `agy --print` exits.

## Why this approach (verified)

`agy 1.0.10` exposes **no** documented machine-readable stream (`--json` / `stream-json` / event stream), so we cannot
stream tool events live like Codex. The CLI status line JSON only gives coarse `agent_state`/`conversation_id`, not tool
details. CLI plugin hooks have no documented payload contract. The SDK is a separate runtime integration, not a drop-in
for the CLI provider.

However, `agy` persists a fully structured trajectory locally that is decodable today. I verified this directly against
the live local install:

- Trajectory DBs live at `~/.gemini/antigravity-cli/conversations/<uuid>.db` (18 present locally), plus a
  `cache/last_conversations.json` cwd→conversation map.
- Each DB is SQLite with a `steps` table:
  `idx, step_type, status, has_subtrajectory, metadata, error_details, permissions, task_details, render_info, step_payload, step_format`.
- `step_payload` is a protobuf message with a stable, walkable envelope: field 1 = `step_type`, field 4 = `status`,
  field 5 = common metadata, plus a type-specific sub-message field.
- **`step_type == 15` is the tool-use request** (each such step carries exactly one tool name in its payload:
  `run_command`, `view_file`, `read_file`, `write_file`, `list_dir`, `list_permissions`, `search`, ...). The following
  step (observed `step_type` 8/9/21/132) is the matching **tool result** with the output payload.
- `status` is a small enum (observed: 3 = success, 7 = other/needs-attention).
- Tool names, JSON-ish args, and command output appear as plain length-delimited fields; a ~20-line varint +
  length-delimited reader walks the payload without `protoc` and without any generated `.proto` code.

This confirms feasibility: the conversation DB is real structured trajectory data, not rendered TUI prose. The cost is
that the SQLite schema, `step_type` enum, and protobuf field numbers are **private, undocumented internals** that Google
can change without notice — so the implementation must be strictly guarded and fail safely (empty panel) on any drift.

## Existing contract we will reuse unchanged

- Providers append normalized rows to `SASE_ARTIFACTS_DIR/tool_calls.jsonl`.
- The shared envelope is built by `src/sase/llm_provider/_tool_call_common.py::base_stream_tool_call_record` with
  `summarize_tool_input` / `summarize_tool_response` for bounded, redacted summaries (secret redaction, preview
  truncation).
- The reader (`src/sase/ace/tui/tools/reader.py` + `_parser.py`) collapses a `ToolUse` row and a `ToolResult` row that
  share `(runtime, tool_use_id, scope)` into one timeline entry. `source` and a new value like `"trajectory"` flow
  through untouched; `schema_version: 2` is supported.

Implication: emit two rows per tool call (`ToolUse` then `ToolResult`) that share a synthetic `tool_use_id`; the reader
merges them with **no panel change**. The existing parity tests in `tests/ace/tui/tools/test_reader_agy.py` already
prove `runtime: "agy"` rows render through the neutral reader.

## High-level design

Add two producer-side modules plus a small version/locator helper; wire a single best-effort call into
`AgyProvider.invoke` after the subprocess finishes.

### 1. `src/sase/llm_provider/_tool_call_agy.py` (pure normalizer)

- A tiny protobuf-wire reader: decode only varints and length-delimited fields, ignore unknown fields/wire types. No
  `protoc`, no generated code.
- Map the verified envelope: read `step_type` (field 1) and `status` (field 4); dispatch on the fixture-proven
  type-specific payload field.
- Recognize only fixture-proven tool-use (`step_type 15`) and tool-result (`8/9/21/132`) shapes; everything else is
  skipped.
- Extract tool name + args from the request payload and output/error from the result payload.
- Map Antigravity tool names → SASE display names so existing summarizers apply: `run_command`→`Bash`,
  `view_file`/`read_file`→`Read`, `write_file`→`Write`, `edit_file`/`replace_file_content`→`Edit`,
  `grep`/`search`→`Grep`; pass unknown names through verbatim (they fall back to the generic key summary).
- Normalize args to the keys the summarizers expect (`command`, `file_path`, `content`, `pattern`, ...) then call
  `summarize_tool_input` / `summarize_tool_response` so output is bounded and secrets redacted exactly like other
  providers.
- Build rows via `base_stream_tool_call_record("agy", ..., source="trajectory")`. Pair request+result with a synthetic
  `tool_use_id = f"{conversation_id}:{idx}"` (request idx); set the same id on the matching result via adjacency. Map
  the `status` enum to `pending`/`success`/`failure`/`interrupted`.
- Pure and deterministic: input = decoded step rows, output = list of records. No env, no I/O — trivially
  fixture-testable.

### 2. `src/sase/llm_provider/_subprocess_agy.py` (locator + extractor I/O)

- `agy` version gate: read `agy --version` (cached), and only extract for an explicit supported-version allowlist
  (start: exactly `1.0.10`), overridable via an env var for testing/opt-in.
- Conversations dir resolution: default `~/.gemini/antigravity-cli/conversations` with an env override (e.g.
  `SASE_AGY_CONVERSATIONS_DIR`) so tests point at a fixture dir; honor any existing Antigravity-home override.
- Run→DB association (two signals, per research):
  1. Snapshot `conversations/*.db` paths+mtimes **before** the run; after exit, select DBs created/modified during the
     run window.
  2. Cross-check `cache/last_conversations.json` for the cwd→conversation id. Because SASE runs agents in distinct
     workspace clones, the cwd map is usually decisive; the mtime diff disambiguates shared-cwd races (resume /
     interrupt / finalizer). Multiple `agy --print` cycles (interrupt resume) → collect all touched DBs and concatenate
     their steps in chronological order.
- Open each resolved DB **read-only** (`file:<path>?mode=ro`) **after** `agy` exits,
  `SELECT idx, step_type, status, step_payload FROM steps ORDER BY idx`, hand rows to the normalizer, and append records
  to `tool_calls.jsonl` via the shared `append_jsonl` / writer-diagnostic helpers in `_tool_call_io.py`.
- Entire path is best-effort: wrap in try/except, emit a writer diagnostic on failure, and **never** raise into
  `invoke`.

### 3. Wire into `AgyProvider.invoke` (`src/sase/llm_provider/agy.py`)

- Before the interrupt `while` loop (before first `Popen`): snapshot the conversations-dir state if `SASE_ARTIFACTS_DIR`
  is set and the version gate passes.
- After the loop returns successfully (just before `return InvokeResult(...)`): call the extractor with the snapshot.
  Guard the whole thing so extraction failures cannot fail the agent run.
- No change to command construction, plain-stdout streaming, `live_reply.md`, argv-size guard, or `usage=None`.

## Safety rails (must-haves)

- **Version gating** on `agy --version`; unknown versions → no extraction, empty panel (current behavior).
- **Best-effort only**: missing DB, unknown schema, SQLite lock, malformed payload, or unmatched conversation →
  `tool_calls.jsonl` absent/partial; the agent run is unaffected.
- **No fabrication**: only emit rows decoded from recognized steps; never scrape `live_reply.md` / stdout / TUI prose.
  Keep the existing no-scraping tests green.
- **Bounded + redacted** summaries via the shared summarizers (honor the existing `SASE_TOOL_LOG_FULL=1` opt-in, nothing
  new).
- **Read-only, post-exit** DB access; never write to or migrate Antigravity state; never install global Antigravity
  hooks/plugins.
- **Loud drift detection** via golden fixtures (below): if field numbers / `step_type` enum change, tests fail rather
  than silently emitting garbage.

## Testing strategy

- **Normalizer unit tests** (pure, no DB): feed decoded step structures for `run_command` (Bash),
  `view_file`/`read_file` (Read), `write_file` (Write), edit, success, failure (`status`≠success), and an unknown
  `step_type`/unknown tool; assert correct SASE rows, name mapping, status, and redaction.
- **Golden wire-format fixtures**: commit a small number of **real-wire-format, benign-content** trajectory DBs captured
  from a controlled `agy` run that only performs innocuous actions (e.g. `echo`, `ls`, read a fixture file), verified to
  contain no sensitive data. These protect against real protobuf/schema drift (synthetic-only fixtures would only test
  our own assumptions). Add a small documented capture script under the fixtures dir; do not run it in normal CI.
- **Association tests**: cwd-map hit; shared-cwd disambiguation via pre/post mtime diff; multi-cycle (interrupt) DB
  collection.
- **Provider integration test**: extend the existing fake-`agy` pattern in `tests/test_llm_provider_agy.py` so the fake
  CLI also drops a fixture DB into a test conversations dir; assert `tool_calls.jsonl` now contains the expected
  `runtime: "agy"`, `source: "trajectory"` rows AND that extraction failure (corrupt/missing DB, unsupported version)
  leaves the run succeeding with no fabricated rows.
- **Reader parity**: keep `tests/ace/tui/tools/test_reader_agy.py`; add a case feeding real extractor output through
  `read_tool_calls_for_agent` to confirm ToolUse+ToolResult collapse into one entry with correct status/preview.
- `just check` (lint + mypy + tests) must pass; `_tool_call_agy.py` stays pure so it is cheap to type and test.

## Files

Add:

- `src/sase/llm_provider/_tool_call_agy.py` — pure trajectory→schema normalizer.
- `src/sase/llm_provider/_subprocess_agy.py` — version gate, DB locator, read-only extractor I/O.
- `tests/test_tool_call_agy.py` (or similar) — normalizer + fixture tests.
- `tests/fixtures/agy/…` — benign golden DB(s) + capture script + README.

Change:

- `src/sase/llm_provider/agy.py` — snapshot before run, best-effort extract after.
- `src/sase/llm_provider/_tool_calls.py` — re-export `append_agy_tool_call_events` for parity with other providers'
  import surface (optional, for consistency).
- `tests/test_llm_provider_agy.py` — extend fake-CLI test for extraction + failure fallback.

No changes to `src/sase/ace/tui/tools/*` or `tools_panel.py`.

## Rust core boundary

This is presentation-adjacent producer glue specific to one CLI's private local format, consumed only by SASE's own
artifact reader — it does not need to match across web/CLI/editor frontends. Per `memory/rust_core_backend_boundary.md`
it stays in this Python repo. If a documented, cross-frontend Antigravity trajectory contract ever appears, revisit
moving normalization into `sase-core`.

## Out of scope / rejected

- Scraping stdout / `live_reply.md` / TUI prose (explicitly tested against).
- Any ACE Tools panel / reader changes.
- Token usage (`usage.json`) and thinking artifacts for `agy` — separate effort; this plan is tools-only (though the
  trajectory has token counters, leave usage to a follow-up).
- Installing Antigravity CLI hooks/plugins or using the SDK — track as parallel spikes / upstream requests for an
  official typed event stream; the guarded DB reader is the best practical option for the current CLI provider now.

## Risks & rollback

- **Private-format drift** (highest risk): mitigated by version gating + golden fixtures (fail loud) + best-effort
  fallback to the empty panel. Rollback = tighten/empty the version allowlist; behavior reverts to today's empty panel.
- **Wrong-DB association**: mitigated by cwd map + mtime diff + distinct-clone cwds; worst case is missing/partial
  tools, never wrong-run contamination if we require the cwd match.
- **TUI performance**: all decode/SQLite work happens in the provider/subprocess path after exit, never on the Textual
  event loop (per `memory/tui_perf.md`).

## Milestones

1. Pure normalizer + unit tests (decoder, name/status mapping, redaction).
2. Version gate + DB locator + read-only extractor I/O + association tests.
3. Wire into `AgyProvider.invoke` (snapshot/extract, best-effort) + provider integration + reader-parity tests; capture
   benign golden fixtures.
4. `just check`, docs/comments noting the private-format dependency and fallback.

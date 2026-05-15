---
create_time: 2026-05-14 23:03:22
status: done
prompt: sdd/prompts/202605/codex_tools_panel_2.md
bead_id: sase-3k
tier: epic
---
# Plan: Codex Support For The Agents Tab Tools Panel

## Problem

The ACE Agents tab already has a Tools panel and a runtime-neutral reader for `tool_calls.jsonl`. Claude has a
hook-first path that writes pending/result pairs with useful status, response, duration, and retry-chain aggregation.
Codex support is only partial:

- `src/sase/llm_provider/_subprocess_codex.py` streams `codex exec --json` NDJSON and calls
  `append_codex_tool_call_event()` for every parsed event.
- `src/sase/llm_provider/_tool_calls.py` currently recognizes only `item.completed` events whose `item.type` is
  `function_call`.
- Those Codex records are written as one `FunctionCall` row with `status: success`, a summarized input, and no response
  summary.
- The reader and panel can display those rows, but the timeline cannot show pending tools, failures, interruptions,
  output previews, duration, or accurate start/result pairing for Codex.

Local reconnaissance found `codex-cli 0.130.0` and `codex exec --json` support. Existing tests already cover the current
parser and writer behavior, so the work should extend the artifact contract without breaking old artifacts.

## Goals

1. Make SASE-launched Codex agents populate the existing Agents tab Tools panel with useful per-tool timelines.
2. Preserve the shared `tool_calls.jsonl` reader contract used by the TUI.
3. Capture enough Codex stream detail to show pending/running calls while an agent is active and final status after a
   result is known.
4. Keep summaries bounded and redacted by default, using the existing `SASE_TOOL_LOG_FULL=1` escape hatch.
5. Add tests and docs that prevent future Codex CLI stream-shape drift from silently degrading the panel.

## Non-Goals

- Do not redesign the Tools panel UI.
- Do not move this into `../sase-core` unless a later frontend needs the same producer/consumer contract through the
  Rust boundary. This is currently Python provider/TUI glue.
- Do not install new global Codex hooks or mutate user `~/.codex` files for tool telemetry.
- Do not change keymaps or `src/sase/default_config.yml`.
- Do not modify `memory/` files.

## Design

Keep Codex tool telemetry stream-derived. Unlike Claude, Codex is already invoked with `--json`, and SASE already owns
the subprocess parser. The implementation should normalize Codex NDJSON into the same conceptual shape the reader
already understands:

- `ToolUse` records for call starts or first sighting of a call;
- `ToolResult` records when a matching output/result event is observed;
- old one-line `FunctionCall` records remain readable for compatibility;
- `runtime: "codex"` and `source: "stream"` identify the producer;
- `tool_use_id` should prefer `call_id`, falling back to stable item ids when needed;
- `recorded_at` should be wall-clock append time unless Codex exposes an event timestamp;
- `duration_ms` should be computed only when start and result timing can be paired in-process with confidence.

The exact Codex event names must be proven from fixtures before broad parser changes. The current tree has tests for
`item.completed/function_call`, but the plan expects Phase 1 to capture representative current `codex exec --json`
events for shell, read, edit/apply-patch, failed shell, interrupted/failed turn, and at least one unknown or MCP-style
tool. If current Codex only emits completed function-call items and no output events, later phases should still improve
schema/source naming and documentation, but should not invent result data.

## Phase 1 - Codex Stream Fixture Contract

Owner: one agent instance. No behavioral changes outside tests/fixtures unless a tiny helper is needed.

Scope:

- Capture or synthesize a representative fixture corpus for current Codex JSON output, clearly labeled with the local
  CLI version used for capture.
- Prefer small, deterministic prompts in a temp repo/workspace that exercise:
  - successful shell command;
  - failed shell command;
  - file read;
  - file edit or patch;
  - final assistant message after tool use;
  - turn failure or CLI error event;
  - unknown tool shape if available.
- Store fixture JSONL under an appropriate test fixture directory rather than depending on a live Codex call in normal
  tests.
- Add focused tests around `_process_codex_json_line()` and `_normalize_codex_tool_call_event()` that document every
  Codex event shape the later phases will support.
- Decide whether Codex exposes separate start/result events, only completed function-call events, or result output
  events under another item type.

Verification:

```bash
just install
pytest tests/test_llm_provider_codex_parser.py tests/llm_provider/test_usage_parsing.py
```

Phase prompt:

> Implement Phase 1 from `sase_plan_codex_tools_panel.md`: capture and codify current `codex exec --json` tool-event
> fixtures, add parser contract tests, and document which event shapes later phases must support.

## Phase 2 - Codex Normalization And Writer

Owner: one agent instance after Phase 1 lands.

Scope:

- Extend `src/sase/llm_provider/_tool_calls.py` so Codex normalization emits the richest safe normalized records that
  Phase 1 fixtures justify.
- If Codex has start/result events, emit `ToolUse` and `ToolResult` rows and let the existing reader collapse them.
- If Codex only exposes completed calls, keep a compatibility `FunctionCall` style row but add `source: "stream"` and
  improve status derivation where possible.
- Normalize common Codex tool names into existing display names:
  - shell/container execution -> `Bash`;
  - file reads -> `Read`;
  - write/edit/apply patch/diff -> `Write`, `Edit`, or `MultiEdit` as appropriate;
  - web/app/MCP tools preserve stable provider names when no local mapping is obvious.
- Preserve and extend existing redaction and bounded-summary behavior.
- Add diagnostics to `tool_calls_writer_errors.jsonl` for unsupported malformed shapes only when useful; irrelevant
  normal stream events should remain silent.
- Keep old schema-2 Codex artifacts readable.

Tests:

- Codex start/result pairing when fixture-supported.
- Successful and failing shell calls with useful command/result previews.
- Read/edit path summaries.
- Malformed arguments and unknown tools.
- `SASE_TOOL_LOG_FULL=1` behavior remains explicit.
- Existing Claude writer tests still pass.

Verification:

```bash
pytest tests/llm_provider/test_usage_parsing.py tests/test_llm_provider_codex_parser.py tests/llm_provider/test_tool_calls_writer.py
```

Phase prompt:

> Implement Phase 2 from `sase_plan_codex_tools_panel.md`: extend Codex tool-call normalization and JSONL writing from
> the Phase 1 fixtures while preserving the existing shared artifact contract and Claude behavior.

## Phase 3 - Reader And Panel Contract Hardening

Owner: one agent instance after Phase 2. Can overlap with Phase 4 only if it uses Phase 2 fixture records.

Scope:

- Update `src/sase/ace/tui/tools/reader.py` only where needed for richer Codex records.
- Ensure Codex `ToolUse`/`ToolResult` pairs collapse into one row with correct status, input summary, response summary,
  source, and duration.
- Ensure legacy Codex `FunctionCall` rows still display as successful call rows.
- Make status handling explicit for Codex failure/interruption records if Phase 1/2 introduce status values beyond the
  current known set.
- Preserve retry/follow-up aggregation across related artifact directories.
- Confirm cache invalidation in `src/sase/ace/tui/widgets/tools_panel.py` still works for live Codex writes.

Tests:

- Reader fixtures mixing legacy Codex rows and new Codex rows.
- Pending Codex row while no result has arrived.
- Failure/interrupted Codex detail rendering.
- Cross-phase aggregation for Codex retries.
- Markdown export includes Codex rows with compact targets.

Verification:

```bash
pytest tests/ace/tui/tools/test_reader.py tests/ace/tui/widgets/test_tools_panel.py tests/ace/tui/test_panel_mode_cycle_refresh.py
```

Phase prompt:

> Implement Phase 3 from `sase_plan_codex_tools_panel.md`: harden the Tools reader and panel for richer Codex records,
> while preserving legacy Codex artifacts and existing retry aggregation.

## Phase 4 - SASE Codex Integration Smoke Coverage

Owner: one agent instance after Phase 2, preferably after Phase 3.

Scope:

- Add an integration-style test or controlled smoke harness that exercises the Codex subprocess parser with fixture
  NDJSON and verifies `tool_calls.jsonl`, `live_reply.md`, and `codex_thinking.jsonl` can coexist.
- Verify `CodexProvider._run_subprocess()` still passes `SASE_ARTIFACTS_DIR` through the shadow `CODEX_HOME` environment
  path.
- Check that multi-cycle Codex invocations, such as interrupt continuation or commit fallback turns, append to the same
  tools artifact without truncating earlier rows.
- If a live Codex smoke is run manually, keep it outside normal automated tests and use a temporary workspace.

Tests:

- Fixture subprocess emits multiple Codex tool events and final assistant messages.
- Commit fallback parser cycle appends more tools instead of overwriting.
- Shadow-home tests still prove config/auth handling and do not require a real Codex network call.

Verification:

```bash
pytest tests/test_llm_provider_codex_parser.py tests/test_llm_provider_codex_shadow_home.py tests/test_llm_provider_codex_fallback.py
```

Phase prompt:

> Implement Phase 4 from `sase_plan_codex_tools_panel.md`: add integration smoke coverage proving SASE Codex runs append
> tool-call artifacts correctly alongside live replies, thinking summaries, shadow homes, and fallback turns.

## Phase 5 - Documentation And Visual Regression Coverage

Owner: one UI/docs agent after Phases 2-4 land.

Scope:

- Update `docs/llms.md` Codex section to describe Codex tool-call artifact capture, including its limits if Codex does
  not expose full result events.
- Update `docs/ace.md` Tools panel section if Codex has provider-specific caveats.
- Add or extend deterministic ACE visual snapshot coverage for a populated Tools panel that includes Codex rows.
- Keep visual fixtures synthetic; do not require Codex to run during visual tests.
- If visual snapshots change intentionally, inspect `.pytest_cache/sase-visual/` artifacts before accepting goldens.

Verification:

```bash
pytest tests/ace/tui/widgets/test_tools_panel.py
just test-visual
just docs-check
```

Phase prompt:

> Implement Phase 5 from `sase_plan_codex_tools_panel.md`: document Codex Tools-panel support and add deterministic
> visual/doc coverage for populated Codex tool timelines.

## Final Validation

The landing agent for the final phase should run the full repository check because this work touches provider parsing,
artifact readers, TUI rendering, and docs:

```bash
just install
just check
```

If only fixture/docs changes landed in a phase, the phase owner may run the narrower verification listed above, but the
final integration phase should run `just check` before handing back.

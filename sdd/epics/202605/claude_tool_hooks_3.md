---
create_time: 2026-05-14 21:01:44
status: done
prompt: sdd/prompts/202605/claude_tool_hooks_3.md
bead_id: sase-3j
tier: epic
---
# Plan: Claude Tool Call Capture via Hooks

## Context

The current tool-call implementation lives in `src/sase/llm_provider/_tool_calls.py` and captures Claude tool usage from
`--output-format stream-json` assistant/user messages, with `--include-hook-events` used only as supplemental signal.
The Tools panel then reads `tool_calls.jsonl` via `src/sase/ace/tui/tools/reader.py` and renders it in
`src/sase/ace/tui/widgets/tools_panel.py`.

The requested direction is to gather rich data about Claude tool calls with Claude Code hooks instead of depending on
the existing stream-derived implementation. Anthropic's current hook documentation says `PreToolUse` and `PostToolUse`
hooks receive structured JSON on stdin with `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `tool_name`,
`tool_input`, and for post-use events `tool_response`. Hook configuration is provided through Claude settings files,
with `PreToolUse`/`PostToolUse` matchers supporting `*`.

Important repo constraints:

- Do not modify SASE memory files.
- Preserve the runtime-neutral tool-call artifact contract where practical; do not encode assumptions that other SASE
  runtimes cannot support hooks.
- Keep shared backend/domain behavior in `../sase-core` if a change becomes a cross-frontend contract rather than
  Python/TUI glue.
- Add new PNG visual snapshot tests showing populated Tools panels.

## Target Design

Add a SASE-owned hook collector command that Claude can run for both `PreToolUse` and `PostToolUse` with matcher `*`.
The collector reads hook JSON from stdin, redacts/bounds it, appends normalized records to the selected agent's
`tool_calls.jsonl`, and optionally appends raw bounded diagnostics to a sibling debug artifact. The normalized artifact
should become hook-first and reader-friendly:

- `PreToolUse` creates the start/pending record with exact `tool_name`, `tool_input`, `session_id`, `transcript_path`,
  `cwd`, and a stable hook event id when available.
- `PostToolUse` updates or appends the completion record with `tool_response`, derived status, duration when derivable,
  and response previews.
- Existing schema-v1/v2 stream-derived records remain readable during migration.
- The old stream parser remains as a temporary fallback/diagnostic source, not the primary collection path.

Hook registration should be done by the SASE Claude provider when launching a SASE-managed agent. Prefer a generated,
per-agent or per-workspace Claude settings layer that is reversible and does not overwrite user/project hooks. If Claude
only supports settings files for hooks, merge SASE hook entries into `.claude/settings.local.json` in the agent
workspace, preserve existing settings, mark generated hook entries clearly, and restore or leave only safe local
workspace state. Home-mode/global settings must not be silently rewritten.

## Phase 1: Hook Collector Contract and Normalization

Owner: one agent instance.

Goals:

- Define the hook-first normalized artifact schema, likely schema v3, while preserving v1/v2 reader compatibility.
- Add a CLI/script entry point for a SASE tool-call hook collector that reads one hook JSON object from stdin and writes
  to `SASE_ARTIFACTS_DIR/tool_calls.jsonl`.
- Support at least `PreToolUse` and `PostToolUse` inputs. Treat unknown hook event names as diagnostics rather than hard
  failures.
- Keep collector failures non-blocking for Claude: exit 0 after writing a diagnostic when input is malformed or writing
  fails.
- Redact secrets and bound large payloads at write time. Keep the existing `SASE_TOOL_LOG_FULL=1` behavior only if it is
  still explicitly useful and safe enough.

Suggested files:

- `src/sase/llm_provider/_tool_calls.py` or a new focused module under `src/sase/llm_provider/`.
- `src/sase/scripts/...` plus `pyproject.toml` console script registration.
- `tests/llm_provider/...` for hook input fixtures and normalization tests.

Acceptance:

- Unit tests cover `PreToolUse`, `PostToolUse`, malformed stdin, missing `SASE_ARTIFACTS_DIR`, redaction, and large
  payload truncation.
- Existing stream-derived tests still pass or are updated to assert fallback/back-compat behavior.

## Phase 2: Claude Hook Registration During Agent Launch

Owner: separate agent instance.

Goals:

- Register the SASE collector for SASE-launched Claude agents without requiring users to manually configure `/hooks`.
- Use `PreToolUse` and `PostToolUse` with matcher `*` and a short timeout.
- Ensure the hook command receives the active `SASE_ARTIFACTS_DIR`, `SASE_AGENT_TIMESTAMP`, and other normal agent
  environment variables.
- Preserve user/project hook settings. Do not erase or reorder unrelated hook entries.
- Handle concurrent agents in separate workspaces and retry/follow-up phases. Each phase should write to the current
  phase artifact directory published by `_publish_phase_env`.
- For home-mode or any launch mode where settings-file mutation would touch user-global state, either find a safe
  temporary Claude settings mechanism or explicitly keep the old stream fallback with a visible diagnostic.

Suggested files:

- `src/sase/llm_provider/claude.py`
- `src/sase/axe/run_agent_exec.py`
- helper module for safe Claude settings merge/restore
- tests around Claude provider argument/env setup and settings preservation

Acceptance:

- Tests prove generated hook settings include both events and preserve existing hooks.
- Tests prove regular SASE workspace launches enable hooks by default.
- Tests prove home-mode/global settings are not silently modified.
- A killed/failed agent does not corrupt existing `.claude/settings.local.json`.

## Phase 3: Reader, Pairing, and Tools Panel Rich Display

Owner: separate agent instance.

Goals:

- Teach `read_tool_calls_for_agent()` to collapse hook-first `PreToolUse`/`PostToolUse` records into one display entry.
- Keep v1/v2 stream records readable, but prefer hook records when both exist for the same tool call.
- Render richer rows in the Tools panel: input target, response preview, status, duration if known, cwd/transcript hint
  when useful, and clear pending/failure/interrupted states.
- Avoid card-like UI or verbose explanatory in-app text; keep the panel dense and scan-friendly.
- Ensure cache invalidation still works when hook writes happen while an agent is running.

Suggested files:

- `src/sase/ace/tui/tools/reader.py`
- `src/sase/ace/tui/widgets/tools_panel.py`
- `tests/ace/tui/tools/test_reader.py`
- `tests/ace/tui/widgets/test_tools_panel.py`

Acceptance:

- Tests cover hook start/end pairing, orphan starts, orphan post-use records, duplicate stream+hook data, sorting, and
  related retry/phase artifact directories.
- Tools panel text tests show success, failure, pending, long command truncation, and rich response detail.

## Phase 4: PNG Snapshot Coverage for Populated Tools Panels

Owner: separate agent instance.

Goals:

- Add new PNG snapshot tests that show the Tools panel populated with realistic tool calls.
- Include at least one successful Bash/Read/Edit-style row and one failure or pending row so status styling is visible.
- Exercise the actual Agents tab panel flow, not only pure renderable text.
- Keep snapshots deterministic: fixed timestamps, fixed artifact directories, stable viewport sizes, existing visual
  helper patterns.

Suggested files:

- `tests/ace/tui/visual/test_ace_png_snapshots.py` or a focused new visual test module.
- `tests/ace/tui/visual/_ace_png_snapshot_helpers.py`
- new goldens in `tests/ace/tui/visual/snapshots/png/`.

Acceptance:

- At least one new golden PNG clearly shows a populated Tools panel.
- Prefer two snapshots if layout risk is meaningful: one standard `120x40`, one narrower or scrolled case.
- `just test-visual` passes locally after updating intended goldens.

## Phase 5: Rollout, Cleanup, and Documentation

Owner: separate agent instance.

Goals:

- Run an end-to-end Claude agent locally enough to prove hook artifacts are produced without manual hook setup.
- Add diagnostics that make hook setup failures obvious in artifacts without blocking the agent.
- Remove or downgrade obsolete stream-primary language in comments and tests.
- Decide whether any normalized tool-call schema belongs in `../sase-core`; if yes, move the shared contract there and
  update Python bindings/callers in this phase rather than leaving a split contract.
- Update relevant developer docs or inline comments so future runtime providers can implement the same hook collector
  contract.

Acceptance:

- `just install` and `just check` pass in the SASE workspace after implementation phases.
- A real or simulated Claude run creates hook-first `tool_calls.jsonl` records.
- The Tools panel reads the new records and snapshots cover the populated UI.
- Backward compatibility with existing artifacts is preserved for old runs.

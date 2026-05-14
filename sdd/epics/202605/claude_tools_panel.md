---
create_time: 2026-05-14 13:18:43
status: done
prompt: sdd/prompts/202605/claude_tools_panel.md
bead_id: sase-3g
tier: epic
---
# MVP Tools Panel For Claude

## Goal

Replace the Agents tab's current Thinking panel with a high-quality MVP Tools panel for Claude Code tool calls. The MVP
should capture tool activity from SASE-launched Claude sessions, persist it in per-phase artifacts, and render it as a
readable operational timeline in `sase ace`.

The implementation should favor the research document's Strategy B:

- Add `claude --include-hook-events` to SASE's existing `--output-format stream-json` invocation.
- Capture hook lifecycle events in-band from Claude stdout.
- Normalize selected events into a SASE-owned `tool_calls.jsonl` artifact.
- Keep the artifact schema runtime-neutral so Gemini, Codex, and Qwen can later write the same file without changing the
  TUI contract.

Strategy A, installing or injecting Claude command hooks, should stay out of the MVP unless Strategy B proves
impossible.

## Non-Goals

- Do not mutate user, project, or local Claude hook settings.
- Do not capture tool calls from non-SASE Claude sessions.
- Do not store full tool outputs by default.
- Do not implement live in-flight `PreToolUse` display.
- Do not migrate reusable parsing into `sase-core` yet; this MVP is presentation and artifact glue in Python. Revisit
  the Rust boundary if other frontends or daemon APIs need the same projection.
- Do not remove the old Thinking parser unless it becomes dead code after the UI migration and tests show it is safe.

## Product Shape

The Tools panel should be an operational timeline:

- Header: runtime-neutral label such as `TOOLS`, count, failures, and last refresh timestamp.
- Each entry: local time, status, tool name, compact target, duration, and one-line detail.
- Empty states: distinguish "no artifact yet" from "artifact exists but no tool calls".
- Export/edit-panel action: when the tools panel is visible, open a markdown/plain text rendering of the timeline.
- Panel cycling: keep the existing `]` / `[` machinery, but relabel the cycle from `file -> thinking -> collapsed` to
  `file -> tools -> collapsed`.

Initial status categories:

- `success`
- `failure`
- `interrupted`
- `subagent`

Initial display grouping can remain chronological. Subagent grouping can be deferred as long as `agent_id` and
`agent_type` are preserved in records.

## Artifact Contract

Write one normalized JSON object per line to:

```text
<SASE_ARTIFACTS_DIR>/tool_calls.jsonl
```

Use schema version `1`. Required fields:

- `schema_version`
- `recorded_at`
- `runtime`
- `event`
- `status`
- `tool_name` when present
- `tool_use_id` when present
- `tool_input_summary`
- `tool_response_summary`

Preserve correlation fields when Claude provides them:

- `session_id`
- `transcript_path`
- `cwd`
- `permission_mode`
- `agent_id`
- `agent_type`
- `duration_ms`
- `error`
- `is_interrupt`

Default storage policy:

- Keep names, timestamps, IDs, durations, status, cwd, and transcript path.
- Summarize tool input by tool type.
- Summarize tool response by tool type.
- Cap previews to small fixed limits.
- Redact obvious token-like shell assignments and avoid storing Write/Edit/MultiEdit full contents.
- Add a debug escape hatch such as `SASE_TOOL_LOG_FULL=1`, but keep it local-only and test the default safe path.

Writer failures must never fail the agent. On malformed events or write errors, swallow the error and best-effort append
small diagnostics to `tool_calls_writer_errors.jsonl`.

## Phase 1: Capture And Normalize

Owner: provider/artifact agent.

Implement the backend artifact producer.

Scope:

- Add `--include-hook-events` to the Claude argv in `src/sase/llm_provider/claude.py`.
- Extend `src/sase/llm_provider/_subprocess_claude.py` so it continues handling `assistant`, `error`, and `result`
  exactly as today, and additionally routes Claude hook events to a new tool-call artifact writer.
- Create a small module under `src/sase/llm_provider/` for tool-call normalization and appending.
- Capture at least:
  - `PostToolUse`
  - `PostToolUseFailure`
  - `SubagentStart`
  - `SubagentStop`
- Write to `SASE_ARTIFACTS_DIR/tool_calls.jsonl` only when `SASE_ARTIFACTS_DIR` is set.
- Use a lock-file append pattern if the writer can be called from more than one process in future, but keep Strategy B
  single-process behavior simple and testable.

Tests:

- Unit-test `_process_json_line` with Claude `PostToolUse` and `PostToolUseFailure` samples.
- Unit-test that assistant text extraction, usage totals, and error event collection are unchanged.
- Unit-test summarization/redaction for Bash, Read, Write/Edit-like inputs, unknown tools, and malformed events.
- Unit-test no-op behavior when `SASE_ARTIFACTS_DIR` is unset.

Acceptance:

- A SASE-launched Claude run with tool use creates `tool_calls.jsonl`.
- The file contains bounded, normalized, valid JSONL.
- Capture failures do not change Claude subprocess return behavior.

## Phase 2: Reader And Data Model

Owner: Tools data adapter agent.

Implement the runtime-neutral reader consumed by the TUI.

Scope:

- Add a `sase.ace.tui.tools` package or similarly named module with:
  - `ToolCallEntry`
  - `read_tool_calls_for_agent(agent)`
  - helpers for parsing and display summaries
- Resolve artifact directories from `agent.get_artifacts_dir()`.
- Aggregate related phase directories for one logical agent by `SASE_AGENT_ROOT_TIMESTAMP` / retry-chain metadata where
  available. For the MVP, at minimum read the current agent artifacts directory and add a small, well-tested helper for
  discovering sibling phase directories that share root metadata.
- Tolerate missing files, empty files, malformed lines, unknown schema versions, and partial writes.
- Sort records stably by `recorded_at`, then file order, then `tool_use_id`.
- Return `None` when no relevant artifact exists and `[]` when artifacts exist but contain no usable calls.

Tests:

- Current-directory read.
- Multi-phase aggregation.
- Malformed-line tolerance.
- Stable sorting.
- Unknown tool/event display fallback.
- Status derivation for success, failure, interrupt, and subagent events.

Acceptance:

- The TUI can ask for tool calls without knowing Claude-specific hook shapes.
- Bad artifact data cannot break the Agents tab.

## Phase 3: TUI Panel Migration

Owner: UI agent.

Replace the Thinking panel surface with the Tools panel while preserving the existing panel-mode ergonomics.

Scope:

- Rename or replace:
  - `AgentThinkingPanel` -> `AgentToolsPanel`
  - `ThinkingVisibilityChanged` -> `ToolsVisibilityChanged`
  - `DetailPanelMode.THINKING` -> `DetailPanelMode.TOOLS`
- Keep IDs stable only if changing them would create too much churn; otherwise migrate to `agent-tools-scroll` and
  `agent-tools-panel` together with tests.
- Reuse the existing background worker, stale-cache, scroll preservation, and visibility-message pattern.
- Render the timeline in Rich `Text` with restrained colors and no decorative card-heavy UI.
- Update:
  - footer labels
  - help modal text
  - action names and comments where user-facing
  - `src/sase/default_config.yml` comments and action labels if needed
  - export/edit-panel behavior so visible Tools content opens instead of Thinking content
- Preserve non-agent behavior: workflow rows without agent content still collapse/expand as today.

Tests:

- Panel cycle tests for `AUTO -> TOOLS -> INFO -> AUTO`.
- Visibility behavior when tools are missing, empty, and present.
- Export/edit-panel behavior.
- Help/footer label assertions where existing tests cover them.
- Update visual snapshots only after manual inspection of actual/diff artifacts.

Acceptance:

- The Agents tab no longer exposes a Thinking panel label.
- Claude tool calls are readable from the Tools panel for a running or completed agent.
- Existing file-panel behavior is not regressed.

## Phase 4: Hardening, Docs, And Verification

Owner: polish/verification agent.

Do the cross-cutting cleanup after the previous phases land.

Scope:

- Run `just install` if the workspace has not been initialized recently.
- Run focused tests from phases 1-3, then `just check`.
- Inspect changed UI text for stale "thinking" references that should now say "tools".
- Confirm old thinking-specific code is either still used by another feature or intentionally left as follow-up cleanup.
- Add a short developer note near the writer/reader explaining that Strategy B is intentional and Strategy A hook
  installation is not part of the MVP.
- If snapshot tests change, inspect `.pytest_cache/sase-visual/` before accepting updates.

Acceptance:

- `just check` passes.
- No user-facing Thinking panel references remain in the Agents tab.
- The implementation has tests for capture, parsing, and UI behavior.

## Sequencing Notes For Distinct Agent Instances

Each phase should be handled by a separate agent instance. To reduce merge friction:

- Phase 1 owns `src/sase/llm_provider/*` and provider-level tests.
- Phase 2 owns the new tools reader package and parser tests.
- Phase 3 owns `src/sase/ace/tui/widgets/*`, TUI action/help labels, config comments, and TUI tests.
- Phase 4 owns cleanup, snapshots, and final verification only.

Phase 3 should not start until Phase 2 has a stable reader API. Phase 4 should not start until all implementation phases
are merged or otherwise available in the same workspace.

## Key Risks

- Claude stream event shape may differ from the research samples. Keep the normalizer defensive and preserve raw event
  type metadata enough to debug without storing huge raw payloads.
- Tool inputs and outputs can contain secrets. Default summaries must be conservative.
- Multi-phase aggregation can become broader than intended. Prefer explicit root metadata and timestamp-scoped sibling
  discovery over scanning unrelated artifact trees.
- The old Thinking panel code is entangled with navigation and export actions. Keep Phase 3 focused on behavioral
  parity, not broad redesign.
- Runtime uniformity matters. The panel and reader should not assume Claude transcript paths are always present.

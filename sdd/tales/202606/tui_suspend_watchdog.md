---
create_time: 2026-06-26 12:37:58
status: done
prompt: sdd/prompts/202606/tui_suspend_watchdog.md
---
# Plan: make ACE suspend handoffs watchdog-aware

## Goal

Implement the solution recommended in `sdd/research/202606/tui_startup_freeze_consolidated_20260626.md`: intentional
terminal handoffs via Textual `suspend()` should not be reported as generic TUI event-loop freezes, and the
editor/artifact-viewer paths should leave useful telemetry and user feedback.

The reported minute-long "startup freeze" was an external editor wait entered from the Agents tab `e` / `edit_spec`
action. A later 15-second record was an artifact viewer wait. Both are intentional terminal ownership transfers. The
remaining Rust index records are real event-loop stalls and are a follow-up, not the target of this change.

## Design

1. Add explicit pause/resume support to `_EventLoopStallWatchdog`.
   - Track a lock-protected pause depth so nested suspend contexts are safe.
   - While paused, the watchdog loop should not schedule/interpret event-loop pings as stall evidence and should reset
     `_last_progress_mono` to the current monotonic time.
   - On resume, reset `_last_progress_mono`, `_ping_pending`, `_in_stall`, and `_stall_started_mono` so a completed
     suspend cannot produce an immediate synthetic recovery or stall record.
   - Preserve existing behavior for normal accidental blocks and for `SASE_TUI_STALL_DISABLE`.

2. Wire the watchdog to Textual suspend/resume lifecycle signals after startup creates it.
   - Subscribe to `app_suspend_signal` and `app_resume_signal` if present.
   - Use `immediate=True`; the installed Textual signal API otherwise posts the callback back to the app, which would
     run too late because `suspend()` blocks the loop immediately after publishing the signal.
   - Guard the hookup dynamically so older/newer Textual versions without these exact attributes keep working.
   - This global signal hook is the safety net for all existing `self.suspend()` and `self.app.suspend()` call sites,
     not just the two noisy paths from the research note.

3. Add a small external-tool wait helper for SASE-owned terminal handoffs.
   - Put it in a TUI utility module so app mixins and modal code can share it.
   - Wrap `app.suspend()` and record elapsed wall time in a separate `external_tool_wait` JSONL telemetry stream, rather
     than putting intentional waits in `tui_stalls.jsonl`.
   - Include low-cardinality metadata such as action, tool kind, command basename, path/artifact count, current tab, and
     current index. Avoid storing large stacks or full content.
   - Provide a pre-handoff terminal/status message where practical so an accidental `e` press is visible before the
     editor/viewer owns the terminal.
   - If the Textual signal hookup is unavailable, the helper should directly pause/resume the watchdog around its own
     suspend block as a fallback.

4. Surface the new telemetry through the existing logs registry.
   - Extend `sase.logs.tui_telemetry` with `tui_external_tools_jsonl_path()` and `log_tui_external_tool_wait()`.
   - Re-export those helpers from `sase.logs`.
   - Add a Log panel source such as `tui_external_tools` with JSONL rendering.
   - Leave `tui_stalls.jsonl` reserved for real stall records.

5. Migrate the immediate high-value call sites.
   - Agents tab chat editor: `src/sase/ace/tui/actions/agents/_panel_detail.py::_open_agent_chat_paths`.
   - Agents detail panel editor paths in the same file, so the editor behavior is consistent for visible files and
     temporary panel content.
   - Non-tmux artifact viewer paths: `src/sase/ace/tui/actions/agents/_panel_artifacts.py::_open_agent_artifact` and
     `_open_agent_artifacts`.
   - Do not change tmux-pane artifact viewing behavior; it does not suspend the Textual app in the same way.

## Tests

1. Extend `tests/ace/tui/util/test_stall_watchdog.py`.
   - A paused watchdog should emit no `tui_stall` record even if the event loop is blocked beyond the threshold.
   - After resume, a later real loop block should still emit exactly one stall.
   - Nested pause/resume should require the final resume before normal stall detection returns.

2. Add tests for startup signal wiring.
   - Use a tiny fake signal object to verify startup subscribes with `immediate=True`.
   - Verify missing signal attributes are tolerated.

3. Add helper/telemetry tests.
   - The external-tool helper should enter the app suspend context, resume the watchdog on success and exception, and
     append one `external_tool_wait` record with rounded elapsed seconds and supplied metadata.

4. Update existing focused action tests.
   - `tests/ace/tui/test_agent_bulk_chat_edit.py` should still assert one editor invocation and one suspend entry, plus
     the new helper metadata where practical.
   - `tests/ace/tui/actions/test_agent_artifact_image_open.py` should still assert viewer calls happen inside suspend,
     plus no generic stall dependency.
   - `tests/ace/tui/logs/test_sources.py` should include the new log source.

5. Verification commands.
   - Run `just install` first, per project memory for ephemeral workspaces.
   - Run focused pytest for the modified areas:
     `pytest tests/ace/tui/util/test_stall_watchdog.py tests/ace/tui/logs/test_sources.py tests/ace/tui/test_agent_bulk_chat_edit.py tests/ace/tui/actions/test_agent_artifact_image_open.py`.
   - Run `just check` before final response because implementation changes will touch repo files outside
     `sdd/research/`.

## Non-goals and follow-up

- Do not move Rust index maintenance off the event loop in this change. The research identified 9 genuine Rust-index
  stalls, but they are separate from the reported editor/viewer freeze and need the existing tracked/background task
  patterns.
- Do not rewrite every existing terminal action in this change. The Textual signal hookup prevents generic stall
  pollution globally; helper migration can continue opportunistically for richer external-tool telemetry.
- Do not alter key bindings or default configuration.

## Risks

- Textual signal APIs are not formally part of SASE's code, so the hookup must be guarded and covered by tests. The
  helper fallback keeps the reported paths protected even if the signal attributes change.
- Pausing the watchdog too broadly could hide real accidental stalls if the pause depth is not balanced. The
  implementation should keep pause/resume small, lock-protected, and tested for exception paths.
- Pre-suspend user feedback may not paint inside Textual before terminal ownership changes. Prefer terminal-safe output
  inside the suspended block, or keep the message best-effort rather than blocking the UI to force a paint.

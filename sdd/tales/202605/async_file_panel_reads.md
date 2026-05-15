---
create_time: 2026-05-14 22:20:34
status: done
prompt: sdd/prompts/202605/async_file_panel_reads.md
---
# Async File Panel Static Reads Plan

## Context

The TUI blocking audit identifies one remaining file-panel blocker: saved static files, saved static diffs, and
precomputed agent diff files are read synchronously on the Textual event loop. Active-agent live diffs already use
`AgentFilePanel.run_worker(..., thread=True)`, but completed agents commonly flow through
`AgentFilePanel.set_file_list() -> _display_file_at_current_index() -> display_static_file()`, which opens and reads the
selected file inline.

The precomputed diff case is partly hidden: `get_agent_diff()` reads `agent.diff_path` synchronously, but when called
from the file panel it already runs inside `_start_background_fetch()` for active/workspace fallback paths. The
still-blocking completed-agent path is `agent.all_files`, where `diff_path` becomes a static file selection. There is
also a direct `display_static_diff()` API that should be converted consistently.

## Goals

- Move static file and static diff disk reads off the Textual event loop.
- Preserve current file-panel behavior: file cycling, file-count messages, visibility messages, trim state, image
  handling, and live-diff worker behavior.
- Prevent stale worker results from overwriting a newer file selection.
- Keep rendering and Textual widget mutation on the UI thread.
- Add focused tests for worker scheduling and stale-result protection.

## Non-Goals

- Do not change the broader agent loader or detail-panel architecture.
- Do not move Rich syntax rendering itself into the worker in this pass; start with the disk-read blocker called out by
  the audit.
- Do not redesign size limiting/tail preview unless the current implementation exposes a natural narrow hook. A
  follow-up can add caps after async reads land.
- Do not change image preview rendering unless needed for correctness. Image previews do not read the full file as text
  through the blocking path.

## Design

1. Split static file rendering into two phases.
   - Worker phase: expand the path, detect whether it is an image, read text content for non-images, detect
     empty/missing/error states, and compute the lexer for normal files.
   - UI phase: consume the worker result and call existing render logic that updates Rich content, trim state,
     visibility messages, and file counters.

2. Introduce a small static-read result model in `file_panel/_display.py`.
   - Include fields such as request id, path, mode (`file` or `diff`), expanded path, content, lexer, status, and
     optional error classification.
   - Keep it local to the file panel to avoid turning this into core backend behavior.

3. Add an async-facing `display_static_file()` / `display_static_diff()` entry.
   - These public methods should schedule a Textual worker with `thread=True` and return quickly.
   - They should cancel or supersede older static-read workers.
   - They may show a lightweight loading state if the panel already has content, matching the existing live-diff
     behavior.

4. Extract current synchronous render code into UI-thread helpers.
   - For normal file content, render via a helper equivalent to the current `display_static_file()` body after the read
     succeeds.
   - For diff content, render via a helper equivalent to the current `display_static_diff()` body after the read
     succeeds.
   - Keep image display on the UI thread through `_display_static_image()`.

5. Guard against stale worker results.
   - Track a monotonically increasing static-read request id and the current static worker.
   - On `Worker.StateChanged`, ignore static-read completions whose request id is no longer current or whose worker is
     not the active static worker.
   - Ensure live-diff workers and static-read workers do not clobber each other. The existing live-diff handler already
     avoids overwriting static file selections; static-read completion should similarly verify that the selected path
     still matches the completed path.

6. Keep precomputed diff reads asynchronous through the file-panel route.
   - Completed agents with `agent.diff_path` appear in `agent.all_files`; after converting static file display, those
     reads happen in the static worker.
   - Leave `get_agent_diff()` synchronous as a worker-safe helper for now, because the file-panel live/fallback route
     already calls it inside a thread worker and other call sites may rely on its simple return value.
   - Add or adjust tests to document that `get_agent_diff()` precomputed reads remain safe when reached through
     `AgentFilePanel.update_display()` for the file panel.

## Test Plan

- Update existing `display_static_file` unit tests so they exercise the new render helper directly, or use a real
  `AgentFilePanel` worker flow where practical.
- Add a unit test that `display_static_file()` schedules a thread worker and does not synchronously call
  `open()`/`Path.read_text()`.
- Add a unit test for stale-result suppression: schedule file A, switch to file B, then ensure A's worker result is
  ignored.
- Add coverage for static diff success, empty, and missing/error states through the UI render helper or worker-result
  handler.
- Run focused tests:
  - `pytest tests/test_file_panel.py tests/ace/tui/test_file_panel_selection_preserved.py tests/ace/tui/widgets/file_panel/test_diff_cache.py`
- Because this repo requires it after code changes, run `just install` if needed and then `just check` before final
  response.

## Risks

- Tests that call `display_static_file()` on a `MagicMock` may need to bind the extracted render helper instead of
  expecting immediate render side effects.
- Textual worker events are shared between live diff and static reads, so the state-change handler must discriminate
  workers carefully.
- If the user cycles files rapidly, cancellation may race with success; request id validation is the primary correctness
  guard.

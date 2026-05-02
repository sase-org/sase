---
create_time: 2026-04-01 12:23:37
status: done
prompt: sdd/prompts/202604/task_queue_edit_keymap.md
---

# Plan: Add `e` (edit) keymap to Task Queue Modal

## Goal

Add a new `e` keybinding to the background task panel (`TaskQueueModal`, opened via `,t`) that writes the currently
selected task's output to a temporary file and opens it in `$EDITOR`.

## Context

The task queue modal (`src/sase/ace/tui/modals/task_queue_modal.py`) displays background task history with a left pane
(task list) and right pane (output viewer). Tasks store their output in `TaskInfo.output` (final) or
`TaskInfo.get_live_output()` (while running). The modal already has keybindings for dismiss (`d`/`D`) and scroll
(`Ctrl+D`/`Ctrl+U`).

Several other modals already implement the exact same editor-opening pattern:

- `AgentRunLogModal.action_open_chat()` — opens agent chat in editor
- `NotificationModal.action_open_in_editor()` — opens notification file in editor
- `XPromptBrowserActionsMixin.action_edit_xprompt()` — opens xprompt in editor

All use: `build_editor_args()` from `sase.ace.hints`, `self.app.suspend()`, `subprocess.run()`.

## Design Decisions

1. **Temp file vs persistent file**: Use `tempfile.mkstemp()` with a descriptive name prefix (e.g., `task_sync_CL-1_`).
   Task output is ephemeral (pruned after 1 hour), so a temp file aligns with the data lifecycle. The file is not
   cleaned up immediately — this allows the user to refer back to it if needed, and the OS will clean it up eventually.

2. **Running tasks**: Allow opening the editor for running tasks too — snapshot whatever live output is available at the
   moment. The user might want to search or copy from partial output.

3. **Empty output**: If the task has no output at all, show a notification and don't open the editor.

4. **File extension**: Use `.txt` since the output is ANSI-stripped text (task output goes through `Text.from_ansi()`
   for display, but the raw output in `TaskInfo.output` may contain ANSI escapes — we should write the raw output as-is
   and let the editor handle it, or strip ANSI). Actually, the output is stored as raw text (may contain ANSI codes from
   subprocess output). Use `.log` extension to hint that this is log-like content.

## Changes

### 1. `src/sase/ace/tui/modals/task_queue_modal.py`

- Add `("e", "edit_output", "Edit")` to `BINDINGS`
- Add `action_edit_output()` method:
  - Get selected task via `_get_selected_task()`
  - Get output: `task.get_live_output()` (covers both running and completed)
  - If empty, `self.notify("No output available", severity="warning")` and return
  - Write to temp file via `tempfile.mkstemp(suffix=".log", prefix=f"task_{task.task_type}_{task.cl_name}_")`
  - Open in editor using the established pattern (`build_editor_args`, `self.app.suspend()`, `subprocess.run`)
  - After editor exits, refresh the output display (output may have changed if task was running)
- Update the hints label to include `e: edit`
- Add required imports: `os`, `subprocess`, `tempfile`, and `build_editor_args` from `sase.ace.hints`

### 2. Tests

No new tests needed — the existing test file covers the `TaskQueue` data model only, not the modal UI. The modal action
follows the exact same pattern as the other editor-opening actions which are also untested at the unit level (they
require a running Textual app). The `e2e` approach for this would be manual testing via `sase ace`.

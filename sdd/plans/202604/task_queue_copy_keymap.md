---
create_time: 2026-04-01 12:29:11
status: done
prompt: sdd/prompts/202604/task_queue_copy_keymap.md
---

# Plan: Add `y` (copy) keymap to Task Queue Modal

## Goal

Add a new `y` keybinding to the Task Queue Modal (`,t`) that copies the currently selected task's output to the system
clipboard.

## Context

The task queue modal (`src/sase/ace/tui/modals/task_queue_modal.py`) already has an `e` keybinding that opens task
output in `$EDITOR`. Adding `y` to copy output to clipboard is the natural complement — quick access without leaving the
TUI.

The codebase already provides `copy_to_system_clipboard()` in `sase.ace.tui.actions.clipboard`, which handles macOS
(`pbcopy`) and Linux (`xclip`). Multiple modals already use this:

- `PlanApprovalModal` uses `y` → `action_copy_plan` (direct copy, no prefix)
- `PromptHistoryModal` uses `ctrl+y` → `action_copy_and_cancel`
- The main app uses `%` copy mode for tab-specific multi-key copies

The `PlanApprovalModal` pattern (direct `y` binding, no copy mode prefix) is the right precedent here — this is a modal
with a single thing worth copying.

## Design Decisions

1. **Direct `y` binding** (not `%` copy mode): The task queue modal has exactly one copyable thing (the task output), so
   a direct binding is simpler and consistent with `PlanApprovalModal`.

2. **Copy raw output**: Use `task.get_live_output()` which works for both running and completed tasks (same source as
   the `e` edit action). Copy the raw text, not ANSI-stripped — this matches what `e` writes to the temp file.

3. **Empty output**: Show a warning notification, same pattern as the `e` action.

4. **Notification**: Show line count in the notification (e.g., "Copied: task output (42 lines)") to confirm what was
   copied. This matches the pattern in `_copy_axe_output`.

## Changes

### 1. `src/sase/ace/tui/modals/task_queue_modal.py`

- Add `("y", "copy_output", "Copy")` to `BINDINGS`
- Add `action_copy_output()` method:
  - Get selected task via `_get_selected_task()`
  - If no task selected, return
  - Get output via `task.get_live_output()`
  - If empty, `self.notify("No output available", severity="warning")` and return
  - Call `copy_to_system_clipboard(output)`
  - Show success/failure notification
- Update hints label to include `y: copy`
- Add import: `copy_to_system_clipboard` from `..actions.clipboard`

### 2. Tests

No new tests — same rationale as the `e` keymap (modal UI actions require a running Textual app; the clipboard function
itself is already battle-tested across the codebase).

---
create_time: 2026-04-12 00:19:11
status: done
prompt: sdd/prompts/202604/quit_confirm_background_tasks.md
---

# Plan: Quit Confirmation When Background Tasks Are Running

## Problem

When the user presses `q` to quit the TUI, the app exits immediately — even if background tasks are still running. This
can lead to orphaned processes (bgcmd slots) or interrupted in-process work (task queue workers like sync/mail/accept).
The user should be warned and asked to confirm.

## Design

Modify `action_quit()` in `lifecycle.py` to check for running tasks before quitting. If any are found, show a
`ConfirmActionModal`. On confirmation, kill everything and proceed with the normal quit flow. On cancellation, stay in
the TUI.

There are two independent task systems to check:

1. **TaskQueue workers** — in-process Textual workers. Count via `self._task_queue.running_count`. Kill each via
   `self._kill_background_task(task_id)`.
2. **Background commands (bgcmd)** — external subprocesses in slots 1-9. Check via `is_slot_running(slot)`. Stop via
   `stop_background_command(slot)`.

## Implementation

### Step 1: Add helper methods to `LifecycleMixin` (`lifecycle.py`)

Add `_count_running_tasks()` that returns the total count of running tasks across both systems (task queue + bgcmd
slots).

Add `_kill_all_running_tasks()` that iterates both systems and kills/stops everything:

- For task queue: iterate `self._task_queue.get_all()`, call `self._kill_background_task(task_id)` for each running task
- For bgcmd: iterate slots 1-9, call `stop_background_command(slot)` for each running slot

### Step 2: Modify `action_quit()` in `lifecycle.py`

Change the flow to:

1. Count running tasks via `_count_running_tasks()`
2. If zero → proceed with current quit logic (no change)
3. If nonzero → push `ConfirmActionModal` with title "Quit" and message like "2 background task(s) still running. Quit
   and kill them?"
4. In the confirmation callback:
   - If confirmed → call `_kill_all_running_tasks()`, then run the existing quit logic (save selection, cleanup activity
     files, exit)
   - If cancelled → no-op (return to TUI)

Extract the existing quit cleanup into a `_do_quit()` private method to avoid duplication between the immediate-quit and
confirmed-quit paths.

### Step 3: Update `action_stop_axe_and_quit()` in `axe.py`

The `Q` (uppercase) binding already stops the axe daemon and quits. It should also kill background tasks for consistency
— call the same `_kill_all_running_tasks()` before exiting. No confirmation needed here since the user explicitly chose
the "stop & quit" action.

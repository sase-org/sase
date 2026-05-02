---
create_time: 2026-04-02 13:19:41
status: done
prompt: sdd/prompts/202604/task_kill_keymap.md
---

# Plan: Add `k` keymap to kill tasks in the Task Queue Modal

## Context

The task queue modal (`TaskQueueModal`, opened via `,t`) displays background tasks (sync, mail, accept, etc.) with
vim-style `j`/`k` navigation, dismiss, edit, and copy actions. There is no way to kill a running task from this modal.

## Key Conflict: `k` is already navigation

`k` is currently bound to `prev_option` (navigate up) via `OptionListNavigationMixin.NAVIGATION_BINDINGS`. Using `k` for
kill would break vim-style navigation. Two options:

1. **Use `K` (shift+k)** for kill, preserving `k` for navigation
2. **Override `k`** and rely on `up` arrow / other bindings for navigation

**Recommendation**: Use `K` (shift+K) since it parallels the existing `D` (shift+D for "dismiss all done") convention
and preserves the standard vim `j`/`k` navigation that users expect.

## Design

### Kill mechanism

Background tasks run as thread-based Textual workers (`run_worker(thread=True)`). Thread workers support cooperative
cancellation via `worker.cancel()`. The approach:

1. Call `worker.cancel()` on the Textual worker to request cancellation
2. Mark the task as error/killed in the `TaskQueue` (status="error", error message indicating it was killed)
3. Clean up the worker tracking in `_task_workers`
4. Notify the user and update the UI

Since thread cancellation is cooperative (the underlying thread may continue briefly), the task will be marked as killed
in the UI immediately even if the thread hasn't fully stopped yet.

### Confirmation flow

Use the existing `ConfirmActionModal` (y/n prompt) pattern, reusing it directly since it already provides the exact
interface needed (title, message, y/n/escape bindings).

### Communication between modal and app

The `TaskQueueModal` currently only receives a `TaskQueue` reference. To kill a worker, it needs access to the app's
`_task_workers` dict. Approach: pass a `kill_callback: Callable[[str], None]` to the modal that the app creates as a
closure capturing its own state.

## Changes

### Phase 1: Add kill infrastructure to `TaskActionsMixin`

**File**: `src/sase/ace/tui/actions/task_actions.py`

- Add `_kill_background_task(self, task_id: str) -> bool` method that:
  - Looks up the worker in `_task_workers`
  - Calls `worker.cancel()`
  - Marks the task as error with message "Killed by user" via `_task_queue.complete()`
  - Cleans up `_task_workers` and `_task_success_callbacks`
  - Calls `_update_task_indicator()`
  - Returns True if the task was found and killed

### Phase 2: Wire up the keymap in `TaskQueueModal`

**File**: `src/sase/ace/tui/modals/task_queue_modal.py`

- Accept `kill_callback: Callable[[str], None] | None = None` in `__init__`
- Add binding `("K", "kill_task", "Kill")` to BINDINGS
- Add `action_kill_task()` that:
  - Gets the selected task
  - Returns early if task is not "running" or no kill_callback
  - Pushes `ConfirmActionModal` with title "Kill Task" and message describing the task
  - On confirmation, calls `kill_callback(task.task_id)`, refreshes the task list, and notifies

### Phase 3: Pass the callback from app to modal

**File**: `src/sase/ace/tui/actions/task_actions.py`

- Update `_show_task_queue_modal()` to pass `kill_callback=self._kill_background_task` to the modal

### Phase 4: Update hints and help

**File**: `src/sase/ace/tui/modals/task_queue_modal.py`

- Update the bottom hint label to include `K: kill`

**File**: `src/sase/ace/tui/modals/help_modal.py` (if task queue keys are documented there)

- Add `K` kill binding to help docs

### Phase 5: Tests

- Test `_kill_background_task` method: kills a running worker, marks task as error, cleans up tracking
- Test `action_kill_task` in modal: only works on running tasks, triggers confirmation, calls callback
- Test that non-running tasks are not killable (no-op)

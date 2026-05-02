---
create_time: 2026-03-31 19:26:12
status: done
prompt: sdd/prompts/202603/task_queue_live_output.md
---

# Plan: Live Output for Running Tasks in Task Queue Modal

## Problem

The task queue viewer modal (`,t`) shows "Task is running..." for running tasks instead of live output. The output panel
on the right side of the modal is empty until the task completes.

## Root Cause

Two gaps in the current implementation:

1. **No intermediate output access**: `capture_output()` creates a StringIO buffer inside `_wrapped()` in
   `task_actions.py`, but the buffer reference is never exposed to `TaskInfo`. The `TaskInfo.output` field is only
   populated when `task_queue.complete()` is called after the task finishes. While the task runs, `TaskInfo.output`
   remains `""`.

2. **No live refresh**: `TaskQueueModal` takes a snapshot of tasks at construction
   (`self._tasks = self._task_queue.get_all()`) and never polls for updates. There is no timer to re-read output for
   running tasks.

## Design

### Phase 1: Expose the live buffer on TaskInfo

Add an optional `_live_buffer: io.StringIO | None` field to `TaskInfo`. When `_submit_background_task` creates the
wrapped callable, it will create the StringIO buffer _before_ the closure and store a reference on the `TaskInfo`. This
lets external code (the modal) call `buf.getvalue()` at any time to read partial output.

Add a `get_live_output()` method to `TaskInfo` that returns `_live_buffer.getvalue()` if the task is running and has a
buffer, otherwise falls back to `self.output`.

**Files**: `task_queue.py`, `task_actions.py`

### Phase 2: Add periodic refresh to TaskQueueModal

Use `self.set_interval(1, self._refresh_running_output)` to poll every 1 second. The callback will:

- Re-fetch the task list from the queue (to pick up newly completed tasks and status changes)
- Rebuild the option list if task statuses have changed (to update icons from running to success/error)
- Update the output pane for the currently selected task using `get_live_output()`
- Auto-scroll to bottom for running tasks (so new output is visible)

Stop the timer on unmount.

**Files**: `task_queue_modal.py`

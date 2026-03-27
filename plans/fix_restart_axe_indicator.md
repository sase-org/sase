---
create_time: 2026-03-27 13:32:35
status: wip
---

# Plan: Fix `--restart-axe` missing TaskIndicator and success notification

## Problem

When `sase ace --restart-axe` is used, two things don't work:

1. **No TaskIndicator icon** — The ⚙ gear icon in the top bar never appears during axe restart. The TaskIndicator is
   driven solely by `_task_queue.running_count` (in `_update_task_indicator()`), but axe start/stop/restart operations
   use a separate `_axe_worker` mechanism that doesn't go through the task queue.

2. **No success notification** — `_on_axe_worker_done()` only calls `self.notify()` on failure. On success, it silently
   updates the status. The user expects to see something like "Axe restarted (pid 1234)".

Both issues also affect `_start_axe()` and `_stop_axe()`, not just `--restart-axe`.

## Changes

### 1. `src/sase/ace/tui/actions/task_actions.py` — Include `_axe_worker` in task count

Modify `_update_task_indicator()` to account for the axe worker in addition to the task queue:

```python
def _update_task_indicator(self) -> None:
    """Update the top-bar task indicator with the current running count."""
    try:
        indicator = self.query_one("#task-indicator", TaskIndicator)
        count = self._task_queue.running_count
        if getattr(self, "_axe_worker", None) is not None:
            count += 1
        indicator.set_count(count)
    except Exception:
        pass
```

### 2. `src/sase/ace/tui/actions/axe.py` — Add success notification and TaskIndicator updates

**a) Add success notification in `_on_axe_worker_done`:**

Change from only notifying on failure to notifying on both success and failure:

```python
if state == WorkerState.SUCCESS and worker.result is not None:
    success, message = worker.result
    self.notify(message, severity="information" if success else "error")
```

**b) Call `_update_task_indicator()` when axe worker starts and finishes:**

Add `self._update_task_indicator()` at the end of `_start_axe()`, `_stop_axe()`, and `_restart_axe_daemon()` (after
setting `self._axe_worker`), and in `_on_axe_worker_done()` (after clearing `self._axe_worker`).

## Files Modified

1. `src/sase/ace/tui/actions/task_actions.py` — Include `_axe_worker` in task indicator count
2. `src/sase/ace/tui/actions/axe.py` — Add success notification; call `_update_task_indicator()` on worker start/finish

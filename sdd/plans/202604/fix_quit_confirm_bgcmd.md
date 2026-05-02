---
create_time: 2026-04-13 12:40:39
status: done
prompt: sdd/prompts/202604/fix_quit_confirm_bgcmd.md
---

# Plan: Fix TUI quit confirmation to only trigger for background tasks

## Problem

When pressing `q` to quit the TUI, the confirmation dialog ("N background task(s) still running. Quit and kill them?")
appears if a background command (triggered via the `!` keymap) is running. The confirmation should ONLY appear when a
background **task** is running (e.g., the `Y` keymap sync, mail, reword, etc.).

Background commands (`!`) are user-initiated shell commands that run as detached subprocesses — they survive
independently and don't need TUI lifecycle management. Background tasks are TUI-managed workers that should be
explicitly acknowledged before quitting.

## Root Cause

In `src/sase/ace/tui/actions/lifecycle.py`, both `_count_running_tasks()` and `_kill_all_running_tasks()` conflate bgcmd
slots (from the `!` keymap) with task queue workers:

- `_count_running_tasks()` sums `task_queue.running_count` + running bgcmd slots
- `_kill_all_running_tasks()` kills task queue workers + stops bgcmd slots

The quit confirmation checks `_count_running_tasks() > 0`, so a running bgcmd incorrectly triggers it.

## Changes

### 1. Simplify `_count_running_tasks()` (lifecycle.py:72-80)

Remove the bgcmd slot counting loop. The method becomes a simple delegation to the task queue:

```python
def _count_running_tasks(self) -> int:
    """Return the count of running background tasks."""
    return self._task_queue.running_count
```

### 2. Simplify `_kill_all_running_tasks()` (lifecycle.py:82-91)

Remove the bgcmd slot killing loop. Only kill task queue workers:

```python
def _kill_all_running_tasks(self) -> None:
    """Kill all running background tasks."""
    for task in self._task_queue.get_all():
        if task.status == "running":
            self._kill_background_task(task.task_id)
```

## Scope

Two methods in one file. No new files, no config changes, no UI changes beyond the corrected confirmation behavior.

---
create_time: 2026-04-14 17:28:42
status: done
prompt: sdd/prompts/202604/rewind_background_task.md
---

# Plan: Run Rewind as a Background Task

## Problem

The `R` (rewind) TUI action currently blocks the entire TUI by running inside `self.suspend()`. This suspends the
terminal, runs the `RewindWorkflow` in the foreground, then resumes — making the UI unresponsive for the duration of the
operation. The `a` (accept) action already runs as a non-blocking background task via `_submit_background_task`, and
rewind should follow the same pattern.

## Design

The conversion is straightforward because:

- `RewindWorkflow.run()` already returns `tuple[bool, str]`, which is the exact signature `_submit_background_task`
  expects.
- The workflow already saves/restores `os.getcwd()` in a `finally` block, making it safe to run in a background thread.
- The `TaskActionsMixin` handles all post-completion concerns (notifications, error handling, TUI reload) automatically.

### Changes

**File: `src/sase/ace/tui/actions/hints/_rewind.py`**

1. Add a module-level `_rewind_task()` function (following the `_accept_task()` pattern in `proposal_rebase.py:108`).
   This function takes plain data arguments (no `self`), creates a `RewindWorkflow`, and returns `tuple[bool, str]`.

2. Rewrite `_run_rewind_workflow()` to:
   - Build a `task_callable` closure that calls `_rewind_task()`
   - Call `self._submit_background_task("rewind", cl_name, project_file, task_callable)`
   - Show an in-progress notification only if submission succeeded
   - Remove the `self.suspend()` block, manual success/failure notifications, and manual `_reload_and_reposition()` call
     (all handled by `TaskActionsMixin`)

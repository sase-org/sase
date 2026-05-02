---
create_time: 2026-04-14 19:50:54
status: done
prompt: sdd/prompts/202604/status_background_task.md
---

# Plan: Run Status Change TUI Actions as Background Tasks

## Problem

The `s` (status change) keymap on the CLs tab blocks the entire TUI whenever the transition involves git/VCS operations.
Five of the status branches use `self.suspend()`, which suspends the terminal for the duration of the operation — making
the UI unresponsive. The most noticeable case is "Submitted" (which checks out the PR branch, merges, and pushes), but
Reverted, Archived, Restore-from-Reverted, and Draft→Ready-with-sibling-reverts all exhibit the same blocking behavior.

The `R` (rewind) and `a` (accept) actions have already been migrated to non-blocking background tasks via
`_submit_background_task()`. Status changes should follow the same pattern.

## Scope

Migrate the five `self.suspend()` code paths in `StatusActionsMixin._apply_status_change()` to background tasks. The two
synchronous paths (WIP kill-processes and standard `transition_changespec_status()` without console) are fast and do not
need migration.

## Design

### Which transitions to migrate

| Branch                  | Current pattern                                                        | Migration? |
| ----------------------- | ---------------------------------------------------------------------- | ---------- |
| Reverted                | `self.suspend()` → `revert_changespec()`                               | Yes        |
| Submitted (git/gh)      | `self.suspend()` → `submit_changespec()`                               | Yes        |
| Archived                | `self.suspend()` → `archive_changespec()`                              | Yes        |
| Restore from Reverted   | `self.suspend()` → `restore_changespec()` + optional second transition | Yes        |
| Draft→Ready with suffix | `self.suspend()` → `transition_changespec_status(console=...)`         | Yes        |
| WIP (kill processes)    | synchronous, fast                                                      | No         |
| Standard transitions    | synchronous, fast                                                      | No         |

### Task function pattern

Following the `_rewind_task()` / `_accept_task()` pattern: each blocking branch gets a module-level pure function that
takes plain data arguments (no `self`), runs the workflow, and returns `tuple[bool, str]`.

The existing workflow functions return `tuple[bool, str | None]`, so each task wrapper converts `None` to an appropriate
success message string (e.g., `"Reverted {cl_name}"`).

### File: `src/sase/ace/tui/actions/status.py`

1. Add five module-level task functions at the top of the file:
   - `_revert_task(file_path, name) -> tuple[bool, str]` — calls `revert_changespec()`
   - `_submit_task(file_path, name, project_basename) -> tuple[bool, str]` — calls `submit_changespec()`
   - `_archive_task(file_path, name) -> tuple[bool, str]` — calls `archive_changespec()`
   - `_restore_task(file_path, name, target_status) -> tuple[bool, str]` — calls `restore_changespec()`, then optionally
     calls `transition_changespec_status()` if `target_status` is Draft or Ready. This combines the two-step restore
     flow into a single background task.
   - `_transition_with_siblings_task(file_path, name, new_status) -> tuple[bool, str]` — calls
     `transition_changespec_status(console=Console())` for the Draft→Ready-with-suffix case. Console output is captured
     automatically by `capture_output()`.

2. Rewrite each `self.suspend()` block in `_apply_status_change()` to:
   - Build a `task_callable` closure calling the corresponding task function
   - Call `self._submit_background_task(task_type, cl_name, project_file, task_callable)`
   - Show an in-progress notification if submission succeeded
   - Remove `self.suspend()`, manual error notifications, and manual `_reload_and_reposition()` (all handled by
     `TaskActionsMixin`)

### Task type strings

Use descriptive task type names: `"revert"`, `"submit"`, `"archive"`, `"restore"`, `"status"`. These appear in the task
queue modal and notifications.

### Restore-from-Reverted complexity

The current code does restore first, then looks up the restored ChangeSpec to do a second transition. In the background
task version, the `_restore_task()` function handles both steps internally — the task function can call
`parse_project_file()` and `transition_changespec_status()` after the restore succeeds, since it runs in a thread with
full filesystem access. This avoids needing chained tasks or `on_success` callbacks for what is logically one operation.

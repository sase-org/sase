---
create_time: 2026-03-23 19:13:52
status: done
prompt: sdd/prompts/202603/edit_project_lock.md
---

# Plan: Project File Edit Locking

## Problem

When the user presses `e` in the CLs tab to edit a project spec file in `$EDITOR`, `sase axe` can concurrently modify
the same file (via chop scripts, agent chops, or check cycles). This creates race conditions where axe writes are
silently overwritten when the user saves in the editor, or the editor shows stale content after axe modifies the file
underneath it.

## Goal

While the editor is open on a project file, `sase axe` should skip all changespecs belonging to that project file. The
lock must be per-project-file (not global) so other projects are unaffected.

## Design

### Sentinel file approach

Use a simple sentinel file (`{project_file}.edit_lock`) rather than extending `fcntl.flock()`. Reasons:

- `fcntl.flock()` via `changespec_lock()` is designed for short atomic operations (seconds). An editor session can last
  hours. Holding an flock for that long would block hooks, comments, and status transitions — not just axe.
- A sentinel file lets axe check-and-skip without blocking, while other subsystems (hooks, status transitions) can still
  perform their short atomic writes via the existing `changespec_lock()`.
- Sentinel files survive process crashes better when combined with PID validation.

### Lock file contents

The `.edit_lock` file contains the PID of the process that created it, enabling stale lock detection:

```
12345
```

### Stale lock cleanup

Before honoring an edit lock, validate the PID is still alive via `os.kill(pid, 0)`. If the process is dead, remove the
stale lock file and treat the project as unlocked.

## Implementation

### Phase 1: Edit lock utilities in `src/sase/ace/changespec/locking.py`

Add three functions:

```python
def acquire_edit_lock(project_file: str) -> None:
    """Create a .edit_lock sentinel file containing the current PID."""

def release_edit_lock(project_file: str) -> None:
    """Remove the .edit_lock sentinel file."""

def is_edit_locked(project_file: str) -> bool:
    """Check if a project file has an active edit lock.

    Returns True if .edit_lock exists AND the PID within is still alive.
    Removes stale lock files (dead PID) and returns False.
    """
```

### Phase 2: Wrap editor invocation in `src/sase/ace/tui/actions/changespec.py`

Modify `_open_spec_in_editor()` to acquire/release the edit lock around the `subprocess.run()` call:

```python
def _open_spec_in_editor(self, changespec: ChangeSpec) -> None:
    ...
    file_path = os.path.expanduser(changespec.file_path)
    acquire_edit_lock(file_path)
    try:
        with self.suspend():
            subprocess.run(args, check=False)
    finally:
        release_edit_lock(file_path)
```

The `finally` block ensures the lock is released even if the editor subprocess raises an exception.

### Phase 3: Filter edit-locked changespecs in axe

Modify `get_filtered_changespecs()` in `src/sase/axe/check_cycles.py` to exclude changespecs whose `file_path` is
edit-locked. This is the single chokepoint through which all lumberjack processing flows — both chop scripts and check
cycles use this method.

```python
def get_filtered_changespecs(self, all_changespecs=None):
    if all_changespecs is None:
        all_changespecs = find_all_changespecs()

    # Remove changespecs from edit-locked project files
    all_changespecs = [
        cs for cs in all_changespecs
        if not is_edit_locked(cs.file_path)
    ]

    if not self.parsed_query:
        return all_changespecs
    return [cs for cs in all_changespecs if evaluate_query(...)]
```

Also add a log message when changespecs are skipped due to edit lock, so lumberjack logs show why processing was paused.

### Phase 4: Tests

Add tests in `tests/ace/changespec/test_locking.py` (or a new file `test_edit_lock.py`):

1. `test_acquire_creates_lock_file` — verify `.edit_lock` is created with correct PID
2. `test_release_removes_lock_file` — verify cleanup
3. `test_is_edit_locked_returns_true_for_active_lock` — happy path
4. `test_is_edit_locked_cleans_stale_lock` — dead PID → removes file, returns False
5. `test_is_edit_locked_returns_false_when_no_lock` — no lock file exists

## Files to modify

| File                                     | Change                                                         |
| ---------------------------------------- | -------------------------------------------------------------- |
| `src/sase/ace/changespec/locking.py`     | Add `acquire_edit_lock`, `release_edit_lock`, `is_edit_locked` |
| `src/sase/ace/changespec/__init__.py`    | Re-export the new functions                                    |
| `src/sase/ace/tui/actions/changespec.py` | Wrap `_open_spec_in_editor` with edit lock                     |
| `src/sase/axe/check_cycles.py`           | Filter edit-locked changespecs in `get_filtered_changespecs`   |
| `tests/ace/changespec/test_edit_lock.py` | New test file for edit lock functions                          |

## Edge cases

- **Multiple editors**: If the user opens the same project file twice, the second `acquire_edit_lock` overwrites the PID
  (both are the same TUI process anyway). `release_edit_lock` from the first close removes the lock. This is acceptable
  — the second editor is still open but the lock is gone. This is unlikely in practice since the TUI blocks on
  `subprocess.run()`.
- **TUI crash**: Stale lock is cleaned up by PID validation on next axe tick.
- **Archive files**: `changespec.file_path` can be either the main `.gp` or the `-archive.gp`. The lock is
  per-file-path, so only the specific file being edited is locked.

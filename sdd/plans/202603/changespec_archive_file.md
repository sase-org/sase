---
create_time: 2026-03-23 18:43:08
status: done
prompt: sdd/prompts/202603/changespec_archive_file.md
---

# Plan: Move ChangeSpecs to Archive File on Terminal Status

## Goal

When a ChangeSpec transitions to Submitted, Archived, or Reverted, move its entire text block from
`~/.sase/projects/<project>/<project>.gp` to `~/.sase/projects/<project>/<project>-archive.gp`. Move it back if the
status ever changes to a non-terminal status. Also read both files everywhere ChangeSpecs are discovered.

## Architecture Overview

### Central Hook Point

`transition_changespec_status()` in `src/sase/status_state_machine/transitions.py` is the single function through which
ALL status changes flow. Every code path that modifies STATUS ultimately calls this function:

| Caller                                | Transition                             | File                                              |
| ------------------------------------- | -------------------------------------- | ------------------------------------------------- |
| `archive_changespec()`                | → Archived                             | `src/sase/ace/archive.py`                         |
| `revert_changespec()`                 | → Reverted                             | `src/sase/ace/revert.py`                          |
| `finalize_submission()`               | → Submitted                            | `src/sase/workspace_provider/submission_utils.py` |
| `mail_execute_task()`                 | → Mailed                               | `src/sase/ace/handlers/mail.py`                   |
| TUI status actions                    | Any                                    | `src/sase/ace/tui/actions/status.py`              |
| `execute_change_action()`             | promote/accept/reject                  | `src/sase/ace/change_actions.py`                  |
| `_revert_sibling_draft_changespecs()` | → Reverted (via `revert_changespec()`) | `transitions.py`                                  |

The one exception is `restore_changespec()` (`src/sase/ace/restore.py`), which renames a Reverted/Archived ChangeSpec
and then calls `sase commit` to create a brand new ChangeSpec. The old ChangeSpec retains its terminal status in the
archive file; the new one is created fresh in the main file by `sase commit`. So no move-back is needed for restore.

### Archive Statuses

```python
ARCHIVE_STATUSES = {"Submitted", "Archived", "Reverted"}
```

### Move Rules

- **Move TO archive**: When `transition_changespec_status()` successfully transitions to an archive status AND the
  ChangeSpec is currently in the main file.
- **Move FROM archive**: When `transition_changespec_status()` successfully transitions from an archive status to a
  non-archive status AND the ChangeSpec is currently in the archive file. (Currently no valid transition path exists for
  this since terminal statuses have empty transition maps, but `validate=False` bypasses this. Handle it for
  robustness.)

### Locking Strategy

The move should happen OUTSIDE the existing lock in `transition_changespec_status()`, similar to how suffix strip/append
operations are handled. The pattern is:

1. Inside the lock: perform the status update, record that a move is needed
2. Outside the lock: perform the move with its own lock ordering

For the move itself, to avoid a window where the ChangeSpec is missing from both files:

- **Add** to destination file first (under destination lock)
- **Remove** from source file second (under source lock)

This means the ChangeSpec temporarily exists in both files (safe) rather than neither (unsafe).

## Implementation Phases

### Phase 1: Core Infrastructure

**New file: `src/sase/ace/changespec/archive.py`**

Functions:

1. `get_archive_file_path(project_file: str) -> str`
   - Input: `~/.sase/projects/sase/sase.gp`
   - Output: `~/.sase/projects/sase/sase-archive.gp`
   - Simple string manipulation: replace `.gp` suffix with `-archive.gp`

2. `get_main_file_path(archive_file: str) -> str`
   - Input: `~/.sase/projects/sase/sase-archive.gp`
   - Output: `~/.sase/projects/sase/sase.gp`
   - Replace `-archive.gp` suffix with `.gp`

3. `is_archive_file(file_path: str) -> bool`
   - Returns `file_path.endswith("-archive.gp")`

4. `extract_changespec_block(lines: list[str], changespec_name: str) -> tuple[list[str] | None, list[str]]`
   - Finds the ChangeSpec named `changespec_name` in the file lines
   - Returns `(extracted_lines, remaining_lines)` where:
     - `extracted_lines`: the raw lines of the ChangeSpec block (including any preceding `## ChangeSpec` header and
       trailing blank line separator), or None if not found
     - `remaining_lines`: the file lines with the ChangeSpec removed
   - Must handle: `## ChangeSpec` headers, NAME-delimited blocks, trailing blank separators

5. `move_changespec_to_file(source_file: str, dest_file: str, changespec_name: str) -> bool`
   - Atomic move operation:
     1. Lock and read source file, extract the ChangeSpec block
     2. Lock dest file, append the ChangeSpec block
     3. Lock source file again, remove the ChangeSpec block (re-read to handle concurrent modifications)
   - Creates dest file if it doesn't exist
   - Returns True on success

**Update `src/sase/ace/changespec/__init__.py`**:

- Export `get_archive_file_path`, `is_archive_file`, `move_changespec_to_file` from `archive.py`

### Phase 2: Hook into `transition_changespec_status()`

**File: `src/sase/status_state_machine/transitions.py`**

In `transition_changespec_status()`, after the lock scope and after suffix operations:

```python
# Move ChangeSpec between main and archive files based on status change
if result[0]:  # success
    old_status_val = result[1]
    old_is_archive = old_status_val in ARCHIVE_STATUSES if old_status_val else False
    new_is_archive = new_status in ARCHIVE_STATUSES

    if new_is_archive and not old_is_archive:
        # Moving TO archive: source is main file, dest is archive file
        archive_file = get_archive_file_path(project_file)
        move_changespec_to_file(project_file, archive_file, changespec_name)

    elif old_is_archive and not new_is_archive:
        # Moving FROM archive: source is archive file, dest is main file
        main_file = get_main_file_path(project_file)
        move_changespec_to_file(project_file, main_file, changespec_name)
```

**Important edge case for the name**: After archive/revert/submit, the ChangeSpec has already been renamed (e.g.,
`foo__20260323_151429` for submit, `foo__1` for archive/revert). The rename happens BEFORE
`transition_changespec_status()` is called. So `changespec_name` is already the renamed version. No suffix operations
happen for terminal transitions (suffix_strip_info and suffix_append_info will be None). So we can just use
`changespec_name` directly.

### Phase 3: Update File Discovery

**File: `src/sase/ace/changespec/__init__.py`**

Update `find_all_changespecs()`:

```python
def find_all_changespecs() -> list[ChangeSpec]:
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return []

    all_changespecs: list[ChangeSpec] = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        # Read main project file
        gp_file = project_dir / f"{project_name}.gp"
        if gp_file.exists():
            all_changespecs.extend(parse_project_file(str(gp_file)))

        # Also read archive file
        archive_file = project_dir / f"{project_name}-archive.gp"
        if archive_file.exists():
            all_changespecs.extend(parse_project_file(str(archive_file)))

    return all_changespecs
```

**File: `src/sase/ace/tui/modals/project_select_modal.py`** (line ~270)

Also read archive files when listing ChangeSpecs for a project. Check how `gp_path` is constructed and add archive file
reading alongside it.

**File: `src/sase/workflows/commit/changespec_operations.py`** (line ~132)

In `add_changespec_to_project_file()`, when scanning for existing names (to compute suffix), also scan the archive file.
This prevents name collisions with archived ChangeSpecs:

```python
# Also check archive file for existing names
archive_file = get_archive_file_path(project_file)
if os.path.isfile(archive_file):
    with open(archive_file, encoding="utf-8") as f:
        for line in f.readlines():
            if line.startswith("NAME: "):
                existing_names.add(line[6:].strip())
```

### Phase 4: Update Constants

**File: `src/sase/status_state_machine/constants.py`**

Add the `ARCHIVE_STATUSES` constant here (canonical location alongside `VALID_STATUSES` and `VALID_TRANSITIONS`):

```python
ARCHIVE_STATUSES = frozenset({"Submitted", "Archived", "Reverted"})
```

### Phase 5: Tests

**New file: `tests/ace/changespec/test_archive.py`**

Test cases:

1. `test_get_archive_file_path` - path conversion
2. `test_get_main_file_path` - reverse path conversion
3. `test_is_archive_file` - detection
4. `test_extract_changespec_block` - extraction with various formats (with/without `## ChangeSpec` header, multiple
   ChangeSpecs in file, single ChangeSpec)
5. `test_extract_changespec_block_not_found` - name not in file
6. `test_move_changespec_to_archive` - end-to-end move from main to archive
7. `test_move_changespec_from_archive` - end-to-end move from archive to main
8. `test_move_creates_dest_file` - archive file doesn't exist yet
9. `test_find_all_changespecs_reads_archive` - verify both files are read

**Update existing tests** that test `transition_changespec_status()` to verify ChangeSpecs are moved to/from the archive
file after terminal status transitions.

## Files Changed (Summary)

| File                                                 | Change                                       |
| ---------------------------------------------------- | -------------------------------------------- |
| `src/sase/ace/changespec/archive.py`                 | **NEW** - Core archive move functions        |
| `src/sase/ace/changespec/__init__.py`                | Update `find_all_changespecs()`, add exports |
| `src/sase/status_state_machine/constants.py`         | Add `ARCHIVE_STATUSES`                       |
| `src/sase/status_state_machine/transitions.py`       | Hook move logic after status change          |
| `src/sase/ace/tui/modals/project_select_modal.py`    | Read archive files in project listing        |
| `src/sase/workflows/commit/changespec_operations.py` | Check archive for name collisions            |
| `tests/ace/changespec/test_archive.py`               | **NEW** - Tests for archive functionality    |

## Risks / Edge Cases

1. **ChangeSpec temporarily in both files**: During the move, the ChangeSpec exists in both files briefly. This is safe
   because `find_all_changespecs()` deduplicates by name and both copies have the same content.
2. **Archive file doesn't exist**: `move_changespec_to_file()` creates it. `parse_project_file()` on a non-existent file
   returns `[]` (already handles this).
3. **PARENT references across files**: If a parent is archived, child lookups via `parse_project_file(project_file)` on
   the main file won't find it. This is fine - the parent validation in `_handle_ready_transition()` only blocks if the
   parent is WIP/Draft, and archived parents are neither.
4. **RUNNING field**: The RUNNING field stays in the main `.gp` file and is never moved. ChangeSpec text blocks are the
   only things that move.
5. **Concurrent access**: The locking strategy (add-then-remove, separate locks) is consistent with existing patterns in
   the codebase.

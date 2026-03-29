---
create_time: 2026-03-29 17:50:50
status: done
---
# Plan: Fix Missing TIMESTAMPS for Initial ChangeSpec Creation

## Problem

When a new ChangeSpec is created via the `#pr` xprompt (or any `create_pull_request` commit method), no TIMESTAMPS
entry is recorded for the initial COMMITS entry `(1) [run] Initial Commit`. This means every new ChangeSpec starts
with an empty audit trail — the first TIMESTAMPS entry only appears on the *second* commit, status change, sync, or
reword.

### Root Cause

`add_changespec_to_project_file()` in `changespec_operations.py` builds the initial COMMITS block **inline** as part
of the ChangeSpec block string and writes it via `write_changespec_atomic()`. It never calls
`add_timestamp_entry_atomic()`. The COMMIT timestamp recording only exists in `add_commit_entry_with_id()` and
`add_proposed_commit_entry()` in `entries.py`, which handle subsequent commits to *existing* ChangeSpecs.

### Data Flow

```
#pr xprompt → sase commit → CommitWorkflow.run()
  → _create_changespec()
    → create_changespec_for_workflow()      [workspace_provider/changespec.py]
      → add_changespec_to_project_file()    [workflows/commit/changespec_operations.py]
        → builds COMMITS block inline       ← NO timestamp recorded here
        → write_changespec_atomic()
```

## Fix

Add a call to `add_timestamp_entry_atomic()` in `add_changespec_to_project_file()` after the lock context completes
and the ChangeSpec (with its initial commits) has been written. This follows the exact same pattern already used in
`add_commit_entry_with_id()` (entries.py lines 489-492) and `add_proposed_commit_entry()` (entries.py lines 346-349).

### Production Change: `src/sase/workflows/commit/changespec_operations.py`

After the `with changespec_lock` block (line ~285), before `return cl_name`, record a COMMIT timestamp for each
initial commit entry:

```python
        # Record COMMIT timestamps for initial commits (outside lock — uses its own lock)
        if initial_commits:
            from sase.ace.timestamps.recording import add_timestamp_entry_atomic

            for commit_tuple in initial_commits:
                num = commit_tuple[0]
                add_timestamp_entry_atomic(project_file, cl_name, "COMMIT", f"({num})")

        return cl_name
```

### Test: `tests/ace/changespec/test_timestamps.py`

Add a test that creates a ChangeSpec with initial commits via `add_changespec_to_project_file()` and verifies a
TIMESTAMPS section with a COMMIT entry is present in the resulting file.

## Scope

- **1 production file** (`changespec_operations.py`) — 5 lines added
- **1 test file** (`test_timestamps.py`) — 1 test case added
- No changes to parsing, formatting, TUI, or fold logic — the existing TIMESTAMPS infrastructure handles everything
  once the entry is recorded

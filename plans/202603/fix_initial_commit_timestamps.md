---
status: done
create_time: 2026-03-30
---

# Fix Missing TIMESTAMPS for Initial COMMITS Entries

## Problem

When a new ChangeSpec is created via `add_changespec_to_project_file()`, any `initial_commits` entries are written
directly into the ChangeSpec block as text — but no corresponding TIMESTAMPS entries are recorded. This means every
newly created ChangeSpec starts life without a TIMESTAMPS section, even though it has COMMITS entries.

Subsequent commits (via `add_commit_entry_with_id()` or `add_proposed_commit_entry()` in `entries.py`) DO call
`add_timestamp_entry_atomic()`, so later commits get timestamped. But the initial `(1) [run] Initial Commit` entry
created at ChangeSpec birth is silently missing from the audit trail.

## Root Cause

`add_changespec_to_project_file()` in `changespec_operations.py` builds COMMITS entries inline (lines 244-267) rather
than delegating to the `entries.py` functions that include timestamp recording. The function never calls
`add_timestamp_entry_atomic()`.

Its sole caller for real workflows, `create_changespec_for_workflow()` in `workspace_provider/changespec.py`, also does
not add timestamps after the call.

## Fix

Add TIMESTAMPS recording in `add_changespec_to_project_file()` after the successful atomic write, outside the lock
(matching the pattern used by `add_commit_entry_with_id()`). Loop over `initial_commits` and record a `COMMIT` timestamp
entry for each.

### Changes

1. **`src/sase/workflows/commit/changespec_operations.py`** — After `write_changespec_atomic()` succeeds and the
   `changespec_lock` context exits, call `add_timestamp_entry_atomic()` for each entry in `initial_commits`.

2. **`tests/test_changespec_operations.py`** — Add a test that verifies `add_changespec_to_project_file()` with
   `initial_commits` produces a TIMESTAMPS section with a COMMIT entry for each initial commit.

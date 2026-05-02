---
create_time: 2026-03-30 11:15:36
status: done
---

# Plan: Fix Missing TIMESTAMPS When ChangeSpecs Are Created With Initial COMMITS

## Problem Summary

Some ChangeSpecs are created with a first `COMMITS` entry but no `TIMESTAMPS` section. This violates the expected
invariant that creating the first commits entry should also create the first timestamp entry.

## Root Cause Hypothesis

There are two distinct paths that add commit entries:

1. **Post-commit append path** (`add_commit_entry_with_id` / `add_proposed_commit_entry` in `commit_utils/entries.py`)
   - Appends a `COMMITS` entry.
   - Then calls `add_timestamp_entry_atomic(..., "COMMIT", "(<entry_id>)")`.

2. **ChangeSpec creation path with `initial_commits`** (`add_changespec_to_project_file` in
   `commit/changespec_operations.py`)
   - Inlines the `COMMITS` block at creation time.
   - Does **not** create any `TIMESTAMPS` entries.

`create_changespec_for_workflow(...)` uses the second path with `initial_commits=[(1, "[run] Initial Commit", ...)]`,
which explains why newly created ChangeSpecs can have `COMMITS` but no `TIMESTAMPS`.

## Desired Behavior

- Whenever a ChangeSpec is created with one or more `initial_commits`, the created ChangeSpec should include a
  `TIMESTAMPS:` section containing corresponding `COMMIT` entries.
- Behavior should match timestamp formatting conventions already used by `add_timestamp_entry_atomic`
  (`[YYYY-MM-DD HH:MM:SS] EVENT detail`).

## Implementation Plan

1. **Add TIMESTAMPS generation in ChangeSpec creation flow**
   - Update `add_changespec_to_project_file` to build a `TIMESTAMPS` block when `initial_commits` is provided.
   - For each initial commit tuple, add a timestamp detail of the form `(<entry_id>)`, where `entry_id` supports numeric
     and alphanumeric ids (e.g., `1`, `0a`, `2b`).
   - Reuse existing timestamp formatting helpers to avoid divergence.

2. **Keep section ordering consistent**
   - Ensure `TIMESTAMPS` is emitted in the standard position (after other sections, currently expected as final section
     in a ChangeSpec).

3. **Add/extend tests**
   - Add tests in `tests/test_changespec_operations.py` that cover:
     - Creating a ChangeSpec with `initial_commits` yields a `TIMESTAMPS` section.
     - The first timestamp includes a `COMMIT` event with detail matching the initial commit entry id (`(1)` etc.).
     - Multiple initial commits produce multiple COMMIT timestamp lines in order.

4. **Regression check related commit-entry path**
   - Add a small test in `tests/workflows/test_commit_add.py` to assert `add_commit_entry_with_id` result includes
     `TIMESTAMPS` (guard existing behavior).

5. **Validate**
   - Run targeted tests first:
     - `tests/test_changespec_operations.py`
     - `tests/workflows/test_commit_add.py`
   - Run full required checks per repo instructions:
     - `just install`
     - `just check`

## Risk Notes

- Timestamp content uses current time, so tests should assert structural invariants (section exists, event type and
  detail text), not exact time strings.
- Avoid calling `add_timestamp_entry_atomic` from inside `add_changespec_to_project_file` after writing; this would
  require a second write cycle and can create ordering/concurrency issues. Prefer emitting timestamps in the same atomic
  write used to create the new ChangeSpec.

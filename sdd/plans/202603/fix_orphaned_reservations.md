---
status: done
create_time: 2026-03-30 18:52:52
prompt: sdd/prompts/202603/fix_orphaned_reservations.md
---

# Fix Orphaned "Reserved" ChangeSpec Entries

## Problem

Agent `@c.1` ran with `#pr:fix_merged_agents` and successfully pushed code to GitHub, but its ChangeSpec was left in
`STATUS: Reserved` state (never promoted to a full ChangeSpec). Additionally, a sibling ChangeSpec was also
corrupted/cleared down to minimal fields.

## Root Cause

There are two bugs in `CommitWorkflow.run()` (`src/sase/workflows/commit/workflow.py`):

### Bug 1: Missing reservation cleanup when ChangeSpec creation fails

The reservation lifecycle has a gap:

```
compute_suffixed_cl_name()  →  writes "Reserved" stub to .gp file
dispatch()                  →  pushes PR to GitHub
_create_changespec()        →  FAILS (returns None or throws)
                               ↑ NO cleanup of the "Reserved" stub
```

`_cleanup_reservation()` is **only** called when the VCS dispatch fails (line 151). When dispatch succeeds but
`_create_changespec()` returns None (e.g. `_get_commits_ahead()` can't resolve the branch ref) or throws, the
reservation is orphaned forever.

### Bug 2: Orphaned reservation corrupts sibling during subsequent operations

When an orphaned reservation sits in the `.gp` file and a **concurrent** or **subsequent** agent run calls
`add_changespec_to_project_file()` with `reserved_name` for a different entry, the `_remove_reservation_lines()`
function strips the targeted reservation and its surrounding blank lines. This is correct in isolation, but when the
file is then re-read by a third operation, the orphaned sibling reservation (still in the file) can cause
`compute_suffixed_cl_name()` to skip that slot, leading to double-suffixed names (`_1_1`, `_2_1`) and minimal/empty
ChangeSpec entries that later get archived as "Reverted" with no useful content.

The real damage is that orphaned reservations occupy name slots permanently, and any manual or automated attempt to
create a ChangeSpec for the same base name produces confusing double-suffixed entries.

## Fix

### Change 1: Clean up reservation when `_create_changespec()` fails

In `CommitWorkflow.run()`, after the `_create_changespec()` call returns None:

```python
cs_name: str | None = None
if self._method == "create_pull_request":
    cs_name = self._create_changespec(cl_url=result)
    if cs_name is None:
        self._cleanup_reservation()
```

This ensures the reservation is always removed when the full ChangeSpec can't be created, regardless of whether it was
the VCS dispatch or the ChangeSpec creation that failed.

### Change 2: Add test coverage

Add a test in `tests/test_changespec_operations.py` that verifies:

- A reservation is created by `compute_suffixed_cl_name()`
- When `add_changespec_to_project_file()` is called with `reserved_name` and succeeds, the reservation is replaced
- When ChangeSpec creation fails, calling `remove_reservation()` correctly cleans up the stub
- After cleanup, `compute_suffixed_cl_name()` can reuse the same suffix slot

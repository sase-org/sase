---
create_time: 2026-03-30 09:42:23
status: done
---

# Fix: TIMESTAMPS field overwritten when hooks are updated

## Problem

The TIMESTAMPS section in ChangeSpec `.gp` files is silently destroyed whenever hooks are added or started. Users lose
their commit/status/sync timestamp history each time a hook operation writes to the file.

## Root Cause

`apply_hooks_update()` in `src/sase/ace/hooks/formatting.py` replaces the HOOKS section by scanning forward past old
content until it reaches a recognized field header. The field header constant `_CHANGESPEC_FIELD_HEADERS` (line 12) is
missing `"TIMESTAMPS:"`, so if TIMESTAMPS follows HOOKS in the file, the skip loop treats `TIMESTAMPS:` and all its
entries as unrecognized/corrupt lines and discards them.

A secondary instance of the same omission exists in `src/sase/status_state_machine/field_updates.py` (line 287,
`_FIELD_HEADERS`), which could cause the same data loss during description updates.

## Fix

### 1. Add `"TIMESTAMPS:"` to both field header tuples

- `src/sase/ace/hooks/formatting.py` — add to `_CHANGESPEC_FIELD_HEADERS`
- `src/sase/status_state_machine/field_updates.py` — add to `_FIELD_HEADERS`

### 2. Add regression tests

- `tests/test_hooks_operations.py` — test that `apply_hooks_update()` preserves a TIMESTAMPS section appearing after
  HOOKS
- `tests/test_status_state_machine_field_updates.py` — test that `_apply_description_update()` preserves a TIMESTAMPS
  section appearing after DESCRIPTION

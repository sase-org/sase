---
create_time: 2026-04-04 19:46:50
status: done
prompt: sdd/prompts/202604/rename_timestamps.md
---

# Plan: Add RENAME Timestamps to ChangeSpec

## Problem

When a ChangeSpec is renamed via the `n` keymap on the CLs tab, no TIMESTAMPS entry is recorded. This is a gap in the
audit trail — every other significant lifecycle event (COMMIT, STATUS, SYNC, REWORD, REWIND) leaves a timestamp, but
renames are silent.

## Design

### RENAME Entry Format

The arrow notation (`->`) is already established by STATUS entries for "before → after" transitions. RENAME fits this
pattern naturally:

```
TIMESTAMPS:
  260329_143022 COMMIT  (1)
  260329_143510 STATUS  WIP -> Draft
  260404_120000 RENAME  old-name -> new-name
```

- **Event type**: `RENAME` (6 chars, pads to 7 — aligns perfectly with existing events)
- **Detail**: `{old_name} -> {new_name}` (mirrors STATUS's `Old -> New` convention)

### Where to Record

`_execute_rename()` in `rename.py` has two success paths:

1. **Reverted CLs** (line ~118) — skip VCS, just update spec references
2. **Active CLs** (line ~210) — full VCS rename + spec update

Both paths must record the RENAME timestamp. The call goes **after** `update_changespec_name_atomic()` succeeds (since
NAME is already changed to `new_name` at that point), using `new_name` as the lookup key.

## Changes

### 1. `src/sase/ace/tui/actions/rename.py`

Add `add_timestamp_entry_atomic(project_file, new_name, "RENAME", f"{old_name} -> {new_name}")` in both success paths —
after spec references are updated, before returning the success tuple.

### 2. `src/sase/ace/changespec/models.py`

Update `TimestampEntry` docstring to include the RENAME format line:

```
[YYYY-MM-DD HH:MM:SS] RENAME  old-name -> new-name
```

### 3. `src/sase/ace/timestamps/recording.py`

Update `add_timestamp_entry_atomic()` docstring's `event_type` param to list RENAME alongside the existing events.

### 4. `tests/ace/changespec/test_timestamps.py`

- Add a parsing test: verify a RENAME entry round-trips correctly through parse → model
- Add an atomic recording test: verify `add_timestamp_entry_atomic` with event_type="RENAME" writes correctly

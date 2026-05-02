---
create_time: 2026-04-03 11:40:42
status: done
prompt: sdd/prompts/202604/fix_status_timestamp_after_suffix_rename.md
---

# Fix: TIMESTAMPS entry not recorded on STATUS transitions with suffix rename

## Problem

When changing a ChangeSpec STATUS from Draft to Ready (or Ready to Draft), the TIMESTAMPS section does not receive a
STATUS entry. The `sase ace` snapshot shows only a COMMIT timestamp but no STATUS timestamp after a Draft→Ready
transition.

## Root Cause

In `src/sase/status_state_machine/transitions.py`, the timestamp recording at lines 152-161 uses the **original**
`changespec_name` parameter. However, suffix operations that run earlier (lines 111-121) rename the NAME field in the
`.gp` file:

- **Draft→Ready** (`handle_suffix_strip`): renames `foo_1` → `foo` in the file, but timestamp recording still searches
  for `foo_1` → `_find_timestamps_insert_point` returns `None` → silent failure.
- **Ready→Draft** (`handle_suffix_append`): renames `foo` → `foo_1` in the file, but timestamp recording still searches
  for `foo` → same silent failure.

The timestamp recording function `add_timestamp_entry_atomic` tries to find the ChangeSpec by matching `NAME: <cl_name>`
in the file. After a suffix rename, the name no longer matches, so the function returns `False` silently (with only a
stderr message).

## Fix

### Phase 1: Use the post-rename name for timestamp recording

**File**: `src/sase/status_state_machine/transitions.py`

After suffix operations complete (line ~121) and before timestamp recording (line ~152), compute the correct ChangeSpec
name:

```python
# Determine correct name for timestamp recording after suffix operations
ts_cl_name = changespec_name
if suffix_strip_info is not None:
    ts_cl_name = suffix_strip_info[1]  # base_name (suffix was stripped)
elif suffix_append_info is not None:
    ts_cl_name = suffix_append_info[1]  # suffixed_name (suffix was appended)
```

Then pass `ts_cl_name` to `add_timestamp_entry_atomic` instead of `changespec_name`.

### Phase 2: Add test coverage

**File**: `tests/ace/changespec/test_timestamps.py`

Add two tests:

1. `test_add_timestamp_entry_atomic_after_name_change`: Simulates the suffix-strip scenario by writing a `.gp` file with
   `NAME: foo` (post-strip), then calling `add_timestamp_entry_atomic` with `cl_name="foo"` and verifying the STATUS
   entry appears. This validates the fix works end-to-end at the recording layer.

2. A unit test in the transitions module test file that mocks the suffix and timestamp operations to verify
   `add_timestamp_entry_atomic` is called with the **base name** (not the suffixed name) after a Draft→Ready transition.

---
create_time: 2026-04-03 20:11:22
status: done
prompt: sdd/prompts/202604/fix_hg_diff_mentor_matching.md
---

# Fix: MENTORS not added for Mercurial ChangeSpecs

## Problem

On the Google/Mercurial machine, the `pat_fix_pg_view_details` ChangeSpec has STATUS: Ready, COMMITS with entry (1), and
HOOKS running/passed — but no MENTORS line is ever added.

## Root Cause

The `_extract_changed_files_from_diff()` function in `src/sase/ace/scheduler/mentor_profile_matching.py` cannot parse
`hg diff -c .` output, which uses a **double `-r`** header format.

### The regex bug

The current hg diff regex:

```python
hg_match = re.match(r"^diff -r [a-f0-9]+ (\S+)", line)
```

Only handles `hg diff` (uncommitted changes) format:

```
diff -r abc123 path/to/file.dart
```

But `hg diff -c .` (committed changeset diff) produces:

```
diff -r abc123 -r def456 path/to/file.dart
```

With the double-`-r` format, the capture group `(\S+)` matches the literal string `-r` instead of the filepath. Since
`-r` doesn't match any file glob like `**/*.dart`, no mentor profiles match, and no MENTORS line is added.

### Why this only affects initial ChangeSpec commits

The diff file creation path differs:

- **Regular commits** (`CommitWorkflow._capture_pre_commit_diff`): Uses `provider.diff()` = `hg diff` → single `-r`
  format → works
- **Initial [run] commits** (`_save_committed_diff` in `workspace_provider/changespec.py`): Tries `git diff` first
  (fails on hg machines), falls back to `provider.committed_diff()` = `hg diff -c .` → double `-r` format → broken

This explains why `pat_ui_integration` (which has subsequent manual commits with working diffs) has mentors, while
`pat_fix_pg_view_details` (only an initial `[run]` commit) does not.

## Fix

### 1. Update the hg diff regex to handle both formats

**File**: `src/sase/ace/scheduler/mentor_profile_matching.py`, function `_extract_changed_files_from_diff`

```python
# Old:
hg_match = re.match(r"^diff -r [a-f0-9]+ (\S+)", line)

# New — optional second -r hash:
hg_match = re.match(r"^diff -r [a-f0-9]+(?: -r [a-f0-9]+)? (\S+)", line)
```

### 2. Add test for double-`-r` format

**File**: `tests/test_mentor_profile_matching.py`

Add a test `test_extract_changed_files_from_diff_hg_changeset_format()` that verifies the double-`-r` format is parsed
correctly.

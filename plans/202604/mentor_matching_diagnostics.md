---
create_time: 2026-04-03 20:47:56
status: done
---

# Fix: Add diagnostic logging to mentor profile matching

## Problem

On the Google/Mercurial machine, `pat_fix_pg_view_details` has STATUS: Ready, COMMITS with entry (1), and HOOKS passed —
but no MENTORS line is ever added.

## Root Cause Analysis

The previous fix (commit 06fcff70) correctly updated the hg diff regex to handle the double-`-r` format from
`hg diff -c .`. However, examining the logpack at ~/tmp/260403_202234/ reveals a deeper observability problem:

1. **No diagnostic logging exists in the mentor matching path.** The `add_matching_profiles_upfront()` function silently
   returns an empty list when no profiles match. There is ZERO logging for:
   - How many profiles were loaded (could be 0 if config loading silently fails)
   - How many commits are being checked
   - Why each profile doesn't match (project scope mismatch, diff file not found, no file_glob match, etc.)
   - When the overall result is "no matches"

2. **The hooks log confirms the silence.** Between 19:31:29 (status → Ready) and 20:18:42 (shutdown), the hooks worker
   ran hundreds of cycles with zero mentor-related log entries for `pat_fix_pg_view_details`. Since
   `add_matching_profiles_upfront()` only logs when profiles ARE added, we get zero visibility into WHY matching failed.

3. **Profile matching hasn't produced "Added profile" log entries since March 22** — across 160K+ lines of hooks log,
   zero new profiles have been matched for ANY changespec since that date. This suggests a systemic issue that may go
   beyond the regex fix.

4. **The `trace_profile_matching()` function already exists** (mentor_profile_matching.py:468-485) with detailed
   per-criterion matching traces, but it's never called from the regular `add_matching_profiles_upfront()` flow.

## Fix Plan

### 1. Add diagnostic logging to `add_matching_profiles_upfront()` when no profiles match

**File**: `src/sase/ace/scheduler/mentor_profile_matching.py`, function `add_matching_profiles_upfront`

When `matching_profiles` is empty and the changespec HAS eligible commits to check, use the existing
`trace_profile_matching()` function to generate a diagnostic summary and log it. This leverages the already-built
tracing infrastructure without duplicating logic.

The log output should include:

- A summary line: `"No mentor profiles matched (N evaluated)"` for quick scanning
- For each profile: which criteria were checked and what happened (project scope skip, diff file not found, 0 file
  matches, no regex match, first_commit not set, etc.)

**Noise control**: Only emit this diagnostic logging on the FIRST check after a new commit is added (not every tick).
Add a module-level cache of `(changespec_name, latest_entry_id)` tuples that have already been diagnosed, and skip
re-logging for the same pair.

### 2. Add test for diagnostic logging behavior

**File**: `tests/test_mentor_profile_matching.py`

Add a test that verifies the diagnostic log callback is invoked with trace details when profiles are loaded but none
match (e.g., file_globs don't match any files in the diff).

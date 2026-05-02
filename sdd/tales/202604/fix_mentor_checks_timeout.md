---
create_time: 2026-04-08 19:19:41
status: done
prompt: sdd/prompts/202604/fix_mentor_checks_timeout.md
---

# Plan: Fix mentor_checks chop timeout (repeated VCS diff loading)

## Problem

The `mentor_checks` chop in the `hooks` lumberjack consistently times out after 30s. All 6 errors in the digest are
identical: `sase_chop_mentor_checks` exceeds its 30s `chop_timeout`.

## Root Cause

`_load_latest_diff_from_vcs()` is called **once per mentor profile** instead of once per changespec. The call chain:

1. `_get_matching_profiles_for_entry()` loops over all mentor profiles (line 322)
2. For each profile, calls `profile_matches_any_commit()` (line 333)
3. `profile_matches_any_commit()` calls `_load_latest_diff_from_vcs()` when the local diff file is missing and the
   profile has `file_globs` or `diff_regexes` (line 230)
4. `_load_latest_diff_from_vcs()` calls `resolve_revision()` which, when local refs don't match, runs
   **`git fetch origin`** — a network operation (`_git_query_ops.py:108`)

The `_UNSET` sentinel caches within a single `profile_matches_any_commit()` call, but each profile gets its own call, so
the cache doesn't carry across profiles. With N profiles, this triggers up to N `git fetch origin` calls.

Three call sites have this N-times-per-changespec pattern:

- `_get_matching_profiles_for_entry()` at `mentor_profile_matching.py:333`
- `clear_mentor_draft_flags()` at `entries.py:143`
- `trace_profile_matching()` at `mentor_profile_matching.py:623` (via `_trace_profile_match`)

## Fix

### Phase 1: Add preloading helper and parameter

In `mentor_profile_matching.py`:

1. Add `_preload_vcs_fallback_diff(changespec, commits) -> str | None` — checks if the latest commit's local diff file
   is missing and, if so, calls `_load_latest_diff_from_vcs()` once.

2. Add `preloaded_vcs_fallback: str | None | object = _UNSET` parameter to `profile_matches_any_commit()`. When not
   `_UNSET`, skip the VCS loading and use this value directly.

3. Add `preloaded_vcs_fallback` parameter to `_trace_profile_match()` with the same semantics.

### Phase 2: Update callers to pre-load once

1. `_get_matching_profiles_for_entry()`: call `_preload_vcs_fallback_diff()` before the profile loop, pass result to
   each `profile_matches_any_commit()` call.

2. `clear_mentor_draft_flags()` in `entries.py`: same pattern — pre-load once, pass to each call.

3. `trace_profile_matching()`: pre-load once, pass to each `_trace_profile_match()` call.

### What NOT to change

- The `chop_timeout` value (30s is appropriate; the repeated VCS calls are the bug)
- The `_load_latest_diff_from_vcs()` implementation (correct behavior, just called too many times)

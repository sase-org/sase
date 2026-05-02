---
create_time: 2026-04-08 21:08:05
status: done
prompt: sdd/prompts/202604/mentor_checks_digest_20260408_210034.md
---

# Plan: Fix `sase axe` hook timeouts in digest_20260408_210034

## Problem

The digest at `.sase/home/.sase/axe/error_digests/digest_20260408_210034.txt` shows a sustained failure pattern:

- 99/100 errors are `hooks -> mentor_checks -> timed out after 30s`
- 1/100 error is `run_every -> sase_refresh_docs -> Failed to claim workspace #103`

The primary issue is the repeating `mentor_checks` timeout, which causes cycle starvation and secondary churn.

## Root Cause Hypothesis (validated against code paths)

`mentor_checks` still performs expensive repeated work in hot paths:

1. **Repeated mentor profile loading/parsing**
   - `check_mentors()` loads profiles directly.
   - `add_matching_profiles_upfront()` loads profiles again.
   - `_get_mentor_profiles_to_run()` loads profiles again.
   - This repeats per ChangeSpec in each hook cycle.

2. **Repeated diff file reads and parsing per profile**
   - Matching logic re-reads commit diffs and re-extracts changed files for each profile.
   - With many profiles and large diffs, this scales poorly and can exceed the 30s chop timeout.

The prior VCS fallback dedup improvement (single fallback load per invocation) exists, but it does not eliminate these
remaining O(profiles _ commits _ diff_size) costs.

## Implementation Strategy

### 1. Add intra-cycle profile reuse

- Extend mentor matching/check APIs to accept an optional preloaded profile list.
- In `HookJobRunner.run_mentor_checks()`, load mentor profiles once per chop execution and pass them through all
  `check_mentors()` calls.
- Keep default behavior unchanged when no list is provided.

### 2. Add per-invocation commit artifact caching for matching

In `mentor_profile_matching.py`:

- Build a cached commit artifact model once per matching invocation containing:
  - commit entry id
  - amend note
  - diff content (local or fallback)
  - extracted changed file list
- Update profile matching/tracing loops to consume cached artifacts instead of re-reading/re-parsing per profile.
- Preserve matching semantics (first_commit, project scope, file_globs, diff_regexes, amend_note_regexes).

### 3. Wire caching through all hot call sites

- `_get_matching_profiles_for_entry()`
- `trace_profile_matching()`
- Any helper in the same module currently re-reading diff data repeatedly.

### 4. Tests

Add/adjust tests to verify:

- Profile list reuse path behaves identically to current behavior.
- Diff fallback still applies only to latest commit.
- New caching path does not change match outcomes.
- Regression guard: expensive fallback/diff reads are invoked at most once per invocation where applicable.

### 5. Validation

- Run `just install` (workspace requirement)
- Run targeted tests for mentor matching/check paths
- Run `just check` before final response

## Non-goals

- Do not change chop timeout values.
- Do not add runtime-specific behavior by agent runtime.
- Do not modify workspace-claiming logic for unrelated workflows unless reproducing evidence points to that as primary.

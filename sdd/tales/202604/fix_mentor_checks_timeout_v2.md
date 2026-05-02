---
create_time: 2026-04-08 21:15:00
status: pending
---

# Plan: Fix persistent mentor_checks timeout (VCS fallback budget)

## Problem

The `mentor_checks` chop in the `hooks` lumberjack consistently times out after 30s — 99 out of 100 errors in the digest
are this same timeout. A previous fix (commit 96e1af92) reduced VCS fallback calls from N-per-changespec to
1-per-changespec via `preload_vcs_fallback_diff()`, but timeouts persist.

## Root Cause

The previous fix was correct but insufficient. Even a **single** call to `_load_latest_diff_from_vcs()` can exceed 30s:

1. `_load_latest_diff_from_vcs()` iterates over up to 2 revision candidates (`changespec.name` and `changespec.cl`)
2. For each candidate, calls `provider.resolve_revision()`
3. `resolve_revision()` in `_git_query_ops.py:100-108` tries local refs first (fast), then on failure runs
   `git fetch origin` with a **600s timeout**
4. A single `git fetch origin` on a slow network or large repo easily takes 15-30+ seconds
5. With 2 candidates that both miss locally, we get up to **2 `git fetch` calls** — easily exceeding 30s
6. `run_mentor_checks()` iterates over multiple changespecs, compounding the issue further

The 99 consecutive timeouts confirm a persistent condition: at least one changespec has a missing local diff and its
branch doesn't resolve locally, triggering slow `git fetch` operations every ~35s.

## Fix

Add a hard timeout to `_load_latest_diff_from_vcs()` so VCS operations are capped at ~10 seconds. The VCS fallback is
best-effort — mentor_checks proceeds correctly without it (profiles just won't match on `file_globs`/`diff_regexes`
until the local diff file appears).

### Phase 1: Timeout wrapper on `_load_latest_diff_from_vcs()`

In `src/sase/ace/scheduler/mentor_profile_matching.py`:

1. Extract the current body of `_load_latest_diff_from_vcs()` into `_load_latest_diff_from_vcs_inner()`
2. Rewrite `_load_latest_diff_from_vcs()` to run the inner function via `concurrent.futures.ThreadPoolExecutor` with a
   10-second timeout
3. On `TimeoutError`, log a warning and return `None`

This keeps the VCS provider code unchanged (the 600s timeout on `git fetch` is correct for other callers like checkout
and push).

### What NOT to change

- The `chop_timeout` (30s is appropriate; the VCS fallback is the outlier)
- The `resolve_revision()` implementation or its 600s fetch timeout
- The preload mechanism from commit 96e1af92 (still correct and useful for deduplication)

### Secondary error

Error 8/100 is `sase_refresh_docs` failing to claim workspace #103. This is a transient workspace-lock issue unrelated
to the mentor_checks timeout pattern — no code change needed.

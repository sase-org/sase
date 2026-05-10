---
create_time: 2026-04-14 00:03:08
status: done
prompt: sdd/prompts/202604/fix_hg_amend_diff.md
---

# Fix: hg.yml Diff Step Shows Entire CL Instead of Incremental Changes on Amend

## Problem

When a sase agent on the Google/hg machine commits to an **existing** CL (via `retired_mercurial_plugin_amend`), the file panel on
the Agents tab shows the diff of the entire CL rather than just the changes from that single amend.

New CLs are unaffected because the first changeset's full diff IS the agent's changes.

## Root Cause

The `hg.yml` diff step (retired Mercurial plugin, line 72) runs `hg diff -c .` after the commit. In Mercurial, `hg amend` replaces
the current changeset with a new one that includes **all** accumulated changes (old + new). So `hg diff -c .` after an
amend produces the entire CL's diff, not just the incremental delta.

This differs from git where `git diff HEAD~1 HEAD` (used in `gh.yml` line 139) always shows just the last discrete
commit, because git never mutates previous commits.

### Why the correct diff exists but gets overwritten

The `CommitWorkflow.run()` already captures the right diff:

1. `capture_pre_commit_diff()` (commit_tracking.py:147) saves `provider.diff(cwd)` = `hg diff` (just the uncommitted
   changes) to `$SASE_ARTIFACTS_DIR/commit_diff.diff` **before** the amend
2. `write_result_marker()` (workflow.py:172) writes `commit_result.json` with `diff_path` pointing to that pre-commit
   diff

But then the `hg.yml` diff step runs **after** the commit and overwrites with `hg diff -c .` (full CL). Since
`extract_step_output_and_diff_path()` (run_agent_helpers.py:76) searches workflow steps first and only falls back to
`commit_result.json` when no step provides a `diff_path`, the full-CL diff wins.

## Fix

### Phase 1: Prefer pre-commit diff in `hg.yml` diff step (retired Mercurial plugin)

**File**: `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/hg.yml` (diff step, lines 61-91)

When commits were made (`head_now != head_before`), check `commit_result.json` for an existing `diff_path` first. If it
exists and the file it points to is non-empty, use that instead of `hg diff -c .`. Fall back to `hg diff -c .` only when
`commit_result.json` doesn't provide a usable diff (e.g., manual amends outside the commit workflow).

The logic change in the bash diff step:

```bash
if [ "$head_now" != "$head_before" ]; then
  cr_file="${SASE_ARTIFACTS_DIR:-}/commit_result.json"
  cr_diff=""
  if [ -n "${SASE_ARTIFACTS_DIR:-}" ] && [ -f "$cr_file" ]; then
    cr_diff=$(python3 -c "..." "$cr_file")  # extract diff_path
    commit_msg=$(python3 -c "..." "$cr_file")  # extract message (existing)
  fi
  if [ -n "$cr_diff" ] && [ -s "$cr_diff" ]; then
    cp "$cr_diff" "$diff_file"
  else
    hg diff -c . > "$diff_file" 2>/dev/null
  fi
  # ... commit_msg fallback to hg log (existing)
fi
```

### Phase 2: Tests

**File**: `../retired Mercurial plugin/tests/test_hg_xprompts.py` (or equivalent test file)

Verify the diff step behavior with:

1. Amend to existing CL with `commit_result.json` present -> uses pre-commit diff
2. New CL with `commit_result.json` present -> uses pre-commit diff (same result either way)
3. Commit without `commit_result.json` -> falls back to `hg diff -c .`

### Notes

- The `gh.yml` and `git.yml` diff steps are unaffected because `git diff HEAD~1 HEAD` already produces the correct
  single-commit diff regardless of branch history.
- The `_save_committed_diff()` function in `changespec.py` also falls back to `provider.committed_diff()` =
  `hg diff -c .` for the ChangeSpec COMMITS entry. This is intentional there -- the ChangeSpec entry should show the
  full CL scope, not just the last amend. No change needed.

---
create_time: 2026-06-24 07:05:13
status: done
prompt: sdd/prompts/202606/archive_git_worktree_delete.md
---
# Fix Git Archive Branch Deletion From Checked-Out Worktrees

## Problem

Archiving a PR/ChangeSpec from `sase ace` can fail after the archive task checks out the target branch in its claimed
workspace and then calls the shared git VCS archive operation. The current git archive implementation creates
`archive/<revision>` and immediately runs `git branch -D <revision>`. Git refuses to delete a branch that is checked out
in any worktree, including the worktree the archive task just used. A failed attempt can also leave the archive tag
behind, so a retry can fail on tag creation before it reaches branch deletion.

## Root Cause

The shared git archive operation is not worktree-aware and is not idempotent after a partial archive:

- It deletes the target local branch while the caller may still have that branch checked out.
- It treats an already-existing `archive/<revision>` tag as an unconditional failure, even when that tag already points
  to the same commit that is being archived.

## Plan

1. Update the shared git VCS archive implementation so it can safely archive the currently checked-out branch:
   - Normalize `origin/<branch>` inputs to the local branch name for local branch deletion.
   - Resolve the target revision commit before creating or validating the archive tag.
   - If `archive/<branch>` already exists, accept it only when it points to the same commit; otherwise fail with a clear
     conflict message.
   - If the current worktree is on the target branch, check out the default branch before deleting the target branch.
   - Continue surfacing normal git command failures with the existing `(False, error)` provider contract.

2. Add focused unit coverage for the edge cases:
   - Happy path still tags and deletes the branch.
   - Existing matching archive tag is treated as idempotent and still deletes the branch.
   - Existing conflicting archive tag fails before branch deletion.
   - Current-branch archive checks out the default branch before `git branch -D`.
   - Checkout failure while moving off the target branch returns a clear failure.

3. Add a real-git integration test that archives a branch while that branch is currently checked out, then verifies:
   - The archive operation succeeds.
   - The archive tag exists.
   - The local branch is gone.
   - The worktree is left on a non-deleted default branch.

4. Run the targeted VCS tests first, then run the repository check command required for SASE code changes.

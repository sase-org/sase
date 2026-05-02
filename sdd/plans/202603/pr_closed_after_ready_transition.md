---
create_time: 2026-03-26 18:12:34
status: done
prompt: sdd/prompts/202603/pr_closed_after_ready_transition.md
---

# Plan: Diagnose and Fix PR Closing After Draft→Ready Transition

## Problem Summary

A GitHub PR is being closed unexpectedly around the time a ChangeSpec transitions from `Draft` to `Ready`. Later,
attempting `Submitted` fails with:

`GitHub project has no PR for this branch. Create a PR first with #pr.`

## Confirmed Facts / Evidence

1. `~/.sase/projects/sase/sase.gp` currently shows:
   - `NAME: sase_feedback_prompt_input_bar`
   - `PR: https://github.com/sase-org/sase/pull/26`
   - `STATUS: Ready`
2. Live GitHub data confirms PR 26 is closed and unmerged:
   - `state: CLOSED`
   - `mergedAt: null`
   - `headRefName: sase_feedback_prompt_input_bar_1`
   - `closedAt: 2026-03-26T21:55:28Z`
3. Remote branches confirm the PR head branch is gone, while renamed branch exists:
   - Missing: `refs/heads/sase_feedback_prompt_input_bar_1`
   - Present: `refs/heads/feedback-prompt-input-bar`
4. Code path for Draft→Ready suffix stripping (`src/sase/status_state_machine/suffix.py`) renames branch and then
   deletes old remote branch via `_push_branch_rename(... git push origin --delete <old>)`.
5. GitHub submit path in `../sase-github/src/sase_github/workspace_plugin.py` checks PR existence only for _current
   branch_ (`gh pr view --json number` without explicit PR id/URL), so if PR is closed or tied to a different head
   branch, submit fails with the exact error seen.

## Root Cause

`Draft -> Ready` suffix stripping triggers git branch rename logic that deletes the original remote branch. For
GitHub-hosted changes with an open PR on the old branch name, deleting that branch causes PR disruption (in this case,
PR 26 ended up closed). Afterwards, submit checks for an open PR on the current branch and reports “no PR for this
branch”.

The `Ready` status transition itself is not directly “submitting”; the branch-rename side effect during the transition
is the actual trigger.

## Fix Strategy

Implement a two-part fix to both prevent this state and make submission robust.

### Part A: Prevent PR breakage during suffix transitions (core repo)

1. Update `src/sase/status_state_machine/suffix.py` to make branch rename behavior VCS-aware.
2. For GitHub repos (`detect_vcs(...) == "github"`), do **not** perform destructive remote rename/delete during suffix
   strip/append.
3. Keep current behavior for bare git/non-GitHub where rename/delete is expected.
4. Add a clear log line when GitHub-safe behavior is used (for diagnosability).

### Part B: Make GitHub submit independent of current branch heuristics (plugin repo)

1. In `../sase-github/src/sase_github/workspace_plugin.py`, stop relying solely on `gh pr view` for current branch.
2. Prefer the ChangeSpec’s recorded PR (`changespec.cl` URL/number) when present:
   - Validate PR exists/open using `gh pr view <pr>`.
   - Submit via `gh pr merge <pr> --merge --delete-branch`.
3. Keep branch-based fallback only when no PR is recorded.
4. Improve error text to distinguish:
   - no PR recorded,
   - PR recorded but already closed,
   - PR recorded but not mergeable.

### Part C: Ensure revision resolution remains stable when names diverge

1. Add fallback in git revision resolution (`src/sase/vcs_provider/plugins/_git_common.py`) so a Ready/base ChangeSpec
   name can resolve a unique suffixed branch when exact branch candidates are missing.
2. This avoids workflow breakage if a ChangeSpec name no longer exactly matches branch name.

## Tests

### Core (`sase_101`)

1. Add unit tests for suffix handling to assert GitHub mode skips remote delete behavior.
2. Add unit tests for `vcs_resolve_revision` fallback (base name resolving to unique suffixed branch).

### Plugin (`../sase-github`)

1. Add tests for `ws_submit` that:
   - uses recorded PR URL/number,
   - handles closed PR with a precise error,
   - still supports branch-based fallback.
2. Add regression test reproducing this failure pattern (suffixed PR head + renamed local branch).

## Validation Steps

1. Recreate scenario with a Draft suffixed ChangeSpec and open PR.
2. Transition Draft→Ready.
3. Verify PR remains open and head branch usable.
4. Run submit transition to `Submitted` and verify successful merge path.
5. Run `just lint` and targeted tests in both repos.

## Rollout / Backout

1. Land plugin + core changes together (or plugin first with defensive submit-by-PR-id path).
2. If any regressions appear, temporarily disable GitHub-safe rename changes and keep submit-by-PR-id fix (lower risk,
   high value).

## User-Facing Behavior After Fix

1. Changing `Draft` to `Ready` will no longer silently invalidate/close GitHub PRs.
2. `Submitted` transition will use the recorded PR directly when available, instead of failing due to branch-name drift.

---
create_time: 2026-03-30 17:25:50
status: done
prompt: sdd/prompts/202603/fix_pr_diff.md
---

# Fix `d` Keymap to Show Full PR Diff (Git/GitHub)

## Problem

The `d` keymap on the "Cls" tab of `sase ace` TUI only shows the diff of the last commit instead of the entire PR diff.
This affects Git and GitHub VCS providers.

## Root Cause

`vcs_diff_revision()` in `src/sase/vcs_provider/plugins/_git_common.py:41-47` uses:

```
git diff {revision}~1 {revision}
```

This computes a single-commit diff (parent → commit), not the full branch diff against the default branch.

When the TUI's `d` key handler (`src/sase/ace/handlers/show_diff.py`) resolves a changespec to a branch name and calls
`diff_revision()`, the user sees only the tip commit's changes — not the cumulative PR diff they expect.

## Fix

Change `vcs_diff_revision()` to use three-dot merge-base diff syntax:

```
git diff origin/main...{revision}
```

This shows all changes the branch introduces relative to its fork point — the full PR diff.

The `_get_default_branch()` helper already exists in `GitCommon` and correctly detects `main` vs `master`.

### Fallback Chain

1. **Primary**: `git diff origin/<default>...{revision}` — full PR diff
2. **Fallback 1**: `git diff {revision}~1 {revision}` — single-commit diff (for detached HEAD, orphan branches, or when
   the remote ref is missing)
3. **Fallback 2**: `git show --format= --patch {revision}` — patch display (root commits with no parent)

### Files to Change

1. **`src/sase/vcs_provider/plugins/_git_common.py`** — Update `vcs_diff_revision()` to use merge-base diff with
   fallbacks
2. **`tests/test_vcs_provider_git_core.py`** — Update existing tests for the new primary command; add test for fallback
   to single-commit diff when merge-base fails

### Scope

- Only `GitCommon` is affected (shared base for `bare_git` and `github` providers)
- Mercurial providers have their own `diff_revision` — unaffected
- `vcs_diff_revision` is only called from the `show_diff` handler — narrow blast radius

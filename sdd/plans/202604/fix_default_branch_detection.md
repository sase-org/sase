---
create_time: 2026-04-09 15:28:57
status: done
prompt: sdd/prompts/202604/fix_default_branch_detection.md
---

# Plan: Fix default branch detection fallback

## Problem

When `git symbolic-ref refs/remotes/origin/HEAD` fails (common in bare repos, fresh clones, or repos where `origin/HEAD`
hasn't been advertised), two functions silently fall back to hardcoded `"main"`. For repos that use `master`, this
causes workspace preparation to fail:

```
sase_hg_update failed: git checkout failed: error: pathspec 'main' did not match any file(s) known to git
```

The agent never starts — it fails at workspace setup with duration 0s.

## Root Cause

Two independent `get_default_branch` implementations share the same bug: they trust `symbolic-ref` and use a blind
`"main"` fallback without verifying the branch exists. A third call site (`_git_commit_dispatch.py`) already has the
correct probe logic but doesn't share it.

## Affected Code

| File                                                          | Function                        | Fallback         |
| ------------------------------------------------------------- | ------------------------------- | ---------------- |
| `src/sase/vcs_provider/plugins/_git_core_ops.py:184-192`      | `_get_default_branch()`         | `"main"`         |
| `src/sase/workspace_provider/utils.py:18-39`                  | `get_default_branch()`          | `"origin/main"`  |
| `src/sase/vcs_provider/plugins/_git_commit_dispatch.py:50-65` | `_merge_with_master()` (inline) | probes correctly |

## Fix

### Phase 1: Fix `_git_core_ops.py._get_default_branch()`

Add a `git show-ref --verify --quiet` probe fallback after `symbolic-ref` fails. Try `master` first, then `main`
(matching the order in `_git_commit_dispatch.py`). Keep `"main"` as the ultimate fallback if neither ref exists (e.g.
empty repo with no remote branches yet).

### Phase 2: Fix `workspace_provider/utils.py.get_default_branch()`

Apply the same probe pattern. This is a standalone function (not on a mixin), so it calls `subprocess.run` directly —
duplicate the probe logic rather than trying to share code across the mixin/standalone boundary.

### Phase 3: DRY up `_git_commit_dispatch.py._merge_with_master()`

`GitCommitDispatchMixin` and `GitCoreOpsMixin` are separate mixins on `CommandRunner`, but they're composed into the
same concrete plugin class at runtime. So `self._get_default_branch()` is available. Replace the inline 6-line probe
block with a call to it.

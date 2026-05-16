---
create_time: 2026-05-16 10:20:18
status: done
prompt: sdd/prompts/202605/pylimit_split_stale_workspace.md
---
# Plan: Stop `sase_pylimit_split` From Re-Scanning Stale Workspaces

## Problem

The `sase_pylimit_split` chop can repeatedly pick the same oversized file even after a previous chop-launched agent
committed a split for that file. The likely stale point is before the workflow runs `tools/pylimit_files-260227`:
candidate generation happens inside the outer `#!sase/pylimit_split` workflow, so it trusts the contents of the
workspace that the outer chop agent is running in.

The chop configuration currently launches:

```yaml
agent: "#gh:sase %g:chop #!sase/pylimit_split %approve"
```

When `#gh:sase` resolves through the normal workspace-backed path, SASE already pre-claims an axe workspace before
spawning the outer agent. The child runner then calls `prepare_workspace_if_needed()` before changing into that
workspace and executing the standalone workflow. That is the right place to guarantee freshness before `pylimit_files`
runs.

The gap is that `prepare_workspace()` currently:

1. stashes/cleans local changes,
2. resolves `VCS_DEFAULT_REVISION` to something like `origin/master`, and
3. checks out that revision.

For git, checkout strips `origin/` to use the local branch name. That can leave an existing axe workspace on a local
`master` that is behind the remote because no fetch/rebase happens in this path. The next `pylimit_files` scan can
therefore see the old, oversized file even though the fix has already landed on the default branch.

## Goals

- Preserve the intended ordering: claim workspace first, make it current with the default parent, then run the workflow
  command that generates the split candidate list.
- Fix the shared default-parent workspace preparation path so other workspace-backed agent launches do not inherit the
  same stale-default issue.
- Keep non-default-target launches unchanged; if a caller explicitly asks for a branch or revision, do not add an
  unexpected sync step.
- Add focused tests that fail on the current behavior and prove the default parent is synced before workflow execution
  can proceed.

## Implementation

1. Update `src/sase/axe/runner_utils.py`.
   - Track whether `update_target` was the `VCS_DEFAULT_REVISION` sentinel.
   - Keep the existing clean step first.
   - Resolve the sentinel via `provider.get_default_parent_revision()` and perform the existing checkout.
   - After a successful checkout of the default parent, call `provider.sync_workspace(workspace_dir)`.
   - If sync fails, print the provider error and return `False`, so the agent runner fails before executing the
     workflow.
   - If a provider does not implement `sync_workspace`, leave the previous checkout-only behavior intact rather than
     breaking non-git providers.

2. Extend `tests/test_axe_runner_utils.py`.
   - Add coverage that `prepare_workspace(..., VCS_DEFAULT_REVISION, ...)` calls `checkout(default_parent)` and then
     `sync_workspace(workspace_dir)`.
   - Add coverage that a sync failure makes `prepare_workspace()` return `False`.
   - Tighten the existing non-sentinel test to assert `sync_workspace()` is not called.

3. Validate with targeted tests first.
   - Run `pytest tests/test_axe_runner_utils.py -q`.

4. Run the repository check after edits.
   - Per local memory, run `just install` first if needed for this workspace.
   - Run `just check` before replying.

## Notes

- I do not plan to change `xprompts/pylimit_split.yml` for this bug. The workflow should be able to assume its process
  has already been launched in a prepared workspace.
- I also do not plan to change the chezmoi chop config unless verification shows the live config has drifted to `#cd:`
  again. A `#cd` launch intentionally bypasses workspace claims and prep, but the current applied and source config both
  use `#gh:sase`.

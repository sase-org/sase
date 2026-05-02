---
create_time: 2026-04-29 13:21:29
status: done
prompt: sdd/prompts/202604/fix_wait_agent_vcs_sync.md
---
# Plan: Prepare Deferred Workspaces After `%wait`

## Problem

Agents launched with `%wait` intentionally defer real workspace allocation until their dependencies finish. This keeps
waiting agents visible in the Agents tab without reserving scarce workspaces.

The current post-wait path is incomplete: once dependencies are satisfied, `claim_deferred_workspace()` allocates and
claims a real workspace, then only `chdir`s into it. It does not run the normal workspace preparation path for that
newly allocated workspace. For Git-backed workspaces this means the agent may start from whatever revision the clone
already had, missing commits pushed by the agents it waited for.

There is also a secondary ordering issue: if a deferred agent has an `update_target`, `run_agent_runner.py` can run
`prepare_workspace()` before the wait, against the placeholder/primary workspace rather than the eventual real
workspace. That preparation is stale by the time the wait resolves and does not help the workspace that the agent
actually uses.

## Desired Behavior

For non-home agents with `%wait` and deferred workspace allocation:

- While waiting, keep the placeholder workspace claim (`workspace_num=0`) and do not prepare a real workspace.
- After dependencies and time waits resolve, allocate the real workspace.
- Immediately prepare that real workspace before executing the agent prompt, using the same `prepare_workspace()` logic
  normal non-wait agents use.
- Preserve retry-spawn behavior: retry children still must not prepare/clean the inherited workspace.
- Keep provider-specific behavior encapsulated behind the existing VCS provider abstraction.

## Implementation

1. Add a small helper in `src/sase/axe/run_agent_runner.py` to centralize "should prepare now" and the preparation call.
   It should skip home mode and retry-spawn children, and it should require a non-empty `update_target`.

2. Change the early preparation block in `run_agent_runner.py` so deferred workspace agents skip pre-wait preparation.
   This avoids preparing the placeholder workspace and documents why deferred agents are handled later.

3. After `claim_deferred_workspace()` returns, run the centralized preparation helper on the newly allocated
   `workspace_dir` / `workspace_num`. This is the behavior that closes the bug.

4. Add focused tests around the runner phase:
   - `claim_deferred_workspace()` still claims and returns the real workspace as before.
   - The runner invokes workspace preparation after a deferred wait resolves, using the post-wait workspace directory.
   - The runner does not prepare before the wait for deferred workspace agents.

5. Run targeted tests first, then `just install` if needed and `just check` as required by repo memory.

## Risk Notes

- The normal `prepare_workspace()` implementation currently checks out the provider's default parent revision but does
  not itself call the provider `sync_workspace()` abstraction. If Git freshness still depends on an explicit fetch/pull,
  the correct follow-up is to strengthen provider-level preparation semantics, not special-case `%wait`.
- Multi-prompt and repeat launchers already mark wait segments with `deferred_workspace=True`; fixing the runner covers
  all launch sites consistently.

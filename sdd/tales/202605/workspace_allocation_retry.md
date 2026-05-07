---
create_time: 2026-05-07 15:05:30
status: done
prompt: sdd/prompts/202605/workspace_allocation_retry.md
---
# Workspace Allocation Retry Plan

## Problem

Agent launches can select a workspace that looked available during preflight allocation, then fail to claim it after the
child process is spawned. This can happen because workspace allocation and workspace claiming are separate operations,
and `get_first_available_axe_workspace()` also falls back to the minimum workspace number when every slot is already
claimed. The result is a launch path that can attempt to start an agent against an unavailable workspace instead of
continuing to search for a free one or failing with a clear exhaustion error.

## Relevant Code Paths

- `src/sase/running_field/_workspace.py`
  - `get_first_available_axe_workspace()` scans RUNNING claims and returns the first free number, but falls back to
    `min_workspace` when the entire range is claimed.
- `src/sase/agent/launch_executor.py`
  - `_resolve_slot_workspace()` is the shared workspace resolver for fan-out slots when the workspace is not already
    preallocated.
  - `execute_launch_plan()` is used by CLI, mobile, TUI single launches, multi-prompt, repeat, model fan-out, and alt
    fan-out.
- `src/sase/agent/launcher.py`
  - `spawn_agent_subprocess()` claims the selected workspace in the child-spawn callback and raises
    `RuntimeError("Failed to claim workspace #...")` when the claim is rejected.
  - `launch_agents_from_cwd()` still preallocates workspace context for single-agent launches before delegating to
    `execute_launch_plan()`.
- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`
  - TUI single-agent launch similarly passes `use_preallocated_workspace=True`, which prevents shared executor retry.
- `src/sase/axe/run_agent_phases.py`
  - Deferred `%wait` agents claim a real workspace later, after dependencies resolve, and need the same retry/exhaustion
    behavior.

## Design

1. Introduce a shared, launch-specific retry policy in `src/sase/agent/launch_executor.py`.
   - Add a small retry loop around workspace resolution plus spawning for non-home, non-deferred, non-explicitly
     preallocated launches.
   - On a workspace claim failure from `spawn_agent_subprocess()`, resolve again and retry until the max attempt count
     is reached.
   - Use a clear default cap, for example `SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES` with a conservative fallback
     default, so launch does not spin forever.
   - When retries are exhausted, raise a message like:
     `Failed to claim an available workspace for <project/ref> after <N> attempts; axe workspaces may all be claimed or racing with other launches.`

2. Stop preallocating ordinary single-agent launches before `execute_launch_plan()`.
   - For CLI/mobile `launch_agents_from_cwd()`, keep explicit workspace contexts for home mode, `%wait`, and VCS
     providers that already resolved a concrete workspace directory.
   - For normal workspace-backed launches, pass a context without `workspace_num/workspace_dir` and let
     `execute_launch_plan()` allocate and retry.
   - Apply the same adjustment to TUI single-agent launch in `_agent_launch.py`.

3. Keep genuinely preallocated workspaces preallocated.
   - Known VCS ref resolution and provider-specific resolution currently pass preallocated env vars so the runner and
     workflow agree on one workspace. Preserve that behavior when a concrete workspace was intentionally resolved.
   - Do not retry spawn-on-retry workspace transfers by allocating a different workspace; transfer failure should remain
     a hard error because the child must inherit the parent's existing workspace.
   - Leave home-mode and `workspace_num=0` deferred placeholders alone.

4. Make “all workspaces claimed” fail clearly at allocation time.
   - Update `get_first_available_axe_workspace()` to raise when the configured range is exhausted instead of returning
     `min_workspace` as a duplicate fallback.
   - Consider leaving `get_first_available_workspace()` behavior unchanged unless tests or adjacent regular-workspace
     callers show the same launch bug applies there.
   - Ensure callers that are not agent launch paths now surface the new error instead of silently attempting a duplicate
     claim.

5. Add deferred workspace retry.
   - Update `claim_deferred_workspace()` in `src/sase/axe/run_agent_phases.py` to retry allocation/claim instead of
     trying a fixed fallback workspace.
   - Its final error should explain that no real workspace could be claimed after dependencies completed.

## Tests

- Add executor tests covering:
  - first claim failure retries with a newly allocated workspace and succeeds;
  - max retry exhaustion raises the clear allocation error;
  - home mode, deferred `workspace_num=0`, and explicitly preallocated contexts do not retry into a different workspace.
- Add running-field tests covering:
  - `get_first_available_axe_workspace()` raises when the full axe range is claimed;
  - it still returns the first gap when one exists.
- Add or update TUI/CLI launch tests to assert ordinary single-agent launches delegate allocation to the executor rather
  than freezing a preallocated workspace before spawn.
- Add deferred `%wait` runner tests for retry and exhaustion.

## Verification

After implementation:

```bash
just install
just test tests/test_agent_launch_executor.py tests/test_running_field_operations.py tests/test_axe_run_agent_runner_retry.py
just check
```

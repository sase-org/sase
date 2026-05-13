---
create_time: 2026-05-13 19:10:37
status: done
prompt: sdd/prompts/202605/deferred_workspace_env_leak.md
---
# Fix Deferred Workspace Env Leak

## Problem

Normal child agents are failing with:

```text
RuntimeError: SASE_AGENT_DEFERRED_WORKSPACE=1 but extracted wait metadata is empty; refusing to continue in the placeholder workspace
```

Recent failed artifacts show submitted prompts such as:

```text
#gh:sase
%name:sase-3e.3.1
%group:sase-3e
%approve
#bd/work_phase_bead:sase-3e.3.1
```

That prompt has no live `%wait` or `%time` directive, and `agent_meta.json` confirms the runner extracted no wait
metadata. The launch/runtime mismatch is therefore not the already-fixed fenced/disabled directive parser bug. It is an
environment inheritance bug: `spawn_agent_subprocess()` builds child environment from `os.environ`, so an agent that was
itself launched with `SASE_AGENT_DEFERRED_WORKSPACE=1` can leak that flag into normal child agents.

## Introducer

The deferred workspace mechanism was introduced by commit `828677c31`
(`feat: Defer workspace claiming for WAITING agents`). That commit added `SASE_AGENT_DEFERRED_WORKSPACE` as a
launch-control env var but did not add spawn-boundary scrubbing for descendants.

Commit `6dac49cb6` (`fix: align quick directive detection with extraction`) introduced the fail-fast guard that now
exposes the latent leak. The guard is correct and should remain: without it, children with leaked deferred state could
skip workspace prep and continue in workspace `0`.

Commit `336bc7e86` fixed a similar spawn-boundary leak for project-dir and preallocation env vars, but it did not
include `SASE_AGENT_DEFERRED_WORKSPACE` or its companion `SASE_AGENT_VCS_WORKFLOW_TYPE`.

## Plan

1. Add a small spawn-boundary sanitizer in `src/sase/agent/launch_spawn.py` for inherited deferred-workspace
   launch-control env vars.
   - Remove `SASE_AGENT_DEFERRED_WORKSPACE`.
   - Remove `SASE_AGENT_VCS_WORKFLOW_TYPE`.
   - Run this before `subprocess_env.update(prepared.env_delta)` so real deferred launches still receive fresh values
     from the prepared launch request.

2. Add regression coverage in `tests/test_cd_spawn_env.py`.
   - Simulate a parent process with stale `SASE_AGENT_DEFERRED_WORKSPACE=1` and `SASE_AGENT_VCS_WORKFLOW_TYPE=gh`.
   - Spawn a normal non-deferred child and assert both stale vars are absent.
   - Spawn a real deferred child and assert the prepared env re-adds both values.

3. Keep existing runtime guard and directive parser alignment tests unchanged.
   - The guard prevents silent placeholder-workspace execution.
   - The parser alignment remains necessary for fenced/disabled prompt text.

4. Verify targeted behavior first, then run repo checks.
   - `just install`
   - `just test tests/test_cd_spawn_env.py tests/test_axe_run_agent_runner_deferred_workspace.py tests/test_directives_has_helpers.py`
   - `just check`

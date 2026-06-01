---
create_time: 2026-06-01 10:48:30
status: done
prompt: sdd/prompts/202606/pylimit_split_chop_workspace_claim_1.md
---
# Plan: Fix `sase_pylimit_split` Workspace Claim Races

## Problem

The live `sase_pylimit_split` run_every chop is failing during outer-agent launch:

```text
Failed to claim an available workspace for sase after 6 attempts:
Failed to claim workspace #10: workspace #10 is already claimed
```

The configured chop is:

```yaml
agent: "%n:sase_pylimit_split-@ #gh:sase %g:chop #!sase/pylimit_split %approve"
```

This is a single normal `#gh:sase` launch that later executes the bundled `#!sase/pylimit_split` workflow. The failure
occurs before the workflow body runs.

## Diagnosis

The stack shows `spawn_slot_with_workspace_retry()` retrying, but every retry uses the same workspace number (`#10`).
That means the launch context is being treated as a fixed/preallocated workspace instead of as a regular axe workspace
allocation.

The relevant current path is:

1. `run_agent_chop_once()` calls `launch_agent_from_cwd(chop.agent, extra_env=...)`.
2. `launch_agents_from_cwd()` sees `#gh:sase`.
3. `resolve_ref_from_prompt()` calls `get_first_available_axe_workspace()` and computes a workspace directory before the
   child is spawned.
4. `launch_agents_from_cwd()` sets `use_preallocated_workspace=True`.
5. `execute_launch_plan()` skips its atomic preclaim path.
6. The detached child tries to claim the observed workspace number directly.
7. If another process claimed that number between observation and child claim, the child fails. The retry loop repeats
   the same fixed workspace number, so retry cannot recover.

This explains the snapshot: `WorkspaceClaimError` is raised from the direct `claim_workspace()` branch, not the transfer
branch. A healthy retryable launch would have `transfer_from_pid` set and would atomically transfer a parent-held claim
to the child.

## Design

Make regular VCS-backed launches use the shared launch executor's atomic workspace preclaim path.

Concretely:

- Keep `#cd` directory launches as fixed workspace launches (`workspace_num=0`, direct target directory, no claim).
- Keep `%wait` launches as deferred workspace launches (`workspace_num=0`, primary workspace while waiting, real
  workspace claimed after dependencies).
- For normal workspace-backed VCS launches such as `#gh:sase`, `#git:home`, and multi-prompt VCS segments:
  - resolve project/ref metadata (`project_file`, `project_name`, `vcs_ref`, `cl_name`, `history_sort_key`,
    `update_target`);
  - do not treat the workspace number returned during ref resolution as a fixed launch slot;
  - leave `workspace_num` and `workspace_dir` unset in `LaunchExecutionContext`;
  - let `spawn_slot_with_workspace_retry()` call `claim_next_axe_workspace()`, resolve the workspace directory from the
    claimed number, and pass `transfer_from_pid` into `spawn_agent_subprocess()`.

This preserves the existing preallocated child environment behavior because `spawn_agent_subprocess()` already receives
the final claimed `workspace_num`, `workspace_dir`, and `vcs_ref`, and uses those to set `SASE_GH_*` / `SASE_GIT_*` env
vars for workflow execution inside the child.

## Implementation Steps

1. Refactor the launch context construction in `src/sase/agent/launch_cwd.py` so a normal resolved VCS ref does not set
   `use_preallocated_workspace=True` merely because ref resolution produced a workspace directory.

2. Apply the same rule to TUI launch construction in `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`: only
   fixed modes (`#cd`, `%wait`, explicit true preallocation) should bypass executor preclaim.

3. Update multi-prompt segment handling in `src/sase/agent/multi_prompt_vcs.py` /
   `src/sase/agent/multi_prompt_launcher.py` so normal VCS segments also rely on executor preclaim. Multi-prompt
   segments with `%wait` should remain deferred.

4. Consider a small helper or explicit boolean on `SegmentVcsContext` if it keeps the distinction clear:
   - `fixed_workspace` / `use_preallocated_workspace` for true fixed modes;
   - unset workspace for regular VCS allocation.

5. Add regression coverage:
   - `launch_agent_from_cwd("#gh:sase ...")` or equivalent provider-backed path calls `claim_next_axe_workspace()`,
     passes `retry_transfer_from_pid`, and does not use `get_first_available_axe_workspace()` as the launch claim.
   - a `WorkspaceClaimError` on the first spawn attempt for a VCS launch retries with a newly claimed workspace.
   - TUI launch body forwards `retry_transfer_from_pid` for resolved VCS refs.
   - Multi-prompt VCS segments retain per-segment project/ref metadata while using executor preclaim.

6. Run targeted tests first:

```bash
just install
uv run pytest tests/test_agent_launch_executor.py tests/test_cd_launch_from_cwd.py tests/ace/tui/test_agent_launch_vcs.py tests/test_multi_prompt_launcher_launch.py tests/test_multi_prompt_launcher_fork.py
```

7. Because this repo requires it after file changes, run:

```bash
just check
```

## Success Criteria

- The `sase_pylimit_split` chop no longer retries the same already-claimed workspace number.
- Direct `#gh:sase` / `#git:home` launches use atomic parent preclaim plus parent-to-child transfer.
- Fixed directory and deferred `%wait` semantics remain unchanged.
- Existing preallocated workspace env (`SASE_GH_*`, `SASE_GIT_*`) is still set inside spawned children for the actual
  claimed workspace.

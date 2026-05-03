---
create_time: 2026-05-02 22:13:49
status: done
prompt: sdd/prompts/202605/axe_run_every_workspace_claims.md
---
# Plan: Stop recurring `run_every` axe workspace-claim errors

## Problem

Recent priority axe notifications from 2026-05-02 show repeated `run_every` errors for:

- `sase_pylimit_split`
- `sase_fix_just`

The attached digests all contain variants of:

```text
Error in <chop>: Failed to claim workspace #100
```

The `run_every` lumberjack log shows the pattern clearly. After an axe/lumberjack restart, both configured agent chops
become eligible together. The lumberjack runs all eligible chops through a `ThreadPoolExecutor`, so both agent launches
enter `launch_agent_from_cwd()` concurrently. That launch path resolves `get_first_available_axe_workspace()` before the
later `claim_workspace()` call, so both launches can pick workspace `#100`; one or both fail when the RUNNING field
claim is finally attempted. A later tick usually succeeds, which explains why the user sees recurring alerts but the
agents eventually launch.

The user config confirms the affected chops are both agent chops under the same `run_every` lumberjack and both have
`run_every: 60m`.

## Goal

Eliminate the noisy, recurring startup/restart failures without changing the intended scheduling semantics:

- eligible script chops may still run concurrently;
- eligible agent chops should still launch promptly;
- multiple agent chops from the same lumberjack should not race each other for the same workspace;
- live agent chop registry/dedup behavior should remain intact across restarts.

## Proposed Design

Change `Lumberjack._run_tick()` so it splits eligible chops into two execution groups:

1. **Script chops** (`chop.agent is None`) continue to run concurrently through the existing `ThreadPoolExecutor`.
2. **Agent chops** (`chop.agent is not None`) run sequentially in the lumberjack process after eligibility is
   determined.

This is intentionally scoped to the observed failure. Agent launches are usually cheap because they only spawn detached
runner processes; the heavy work happens in those child agents. Sequentializing only the launch phase prevents same-tick
workspace allocation races while preserving actual parallel agent execution after launch.

Keep result aggregation centralized. The sequential agent launches should still produce `_ChopResult` values and flow
through the existing metrics, timestamp updates, `_agent_pids`, logging, and error handling.

## Implementation Steps

1. Refactor the eligible-chop section in `src/sase/axe/lumberjack.py`:
   - build `eligible_script_chops` and `eligible_agent_chops`;
   - run script chops with the existing executor;
   - run agent chops sequentially with `_run_single_chop()`;
   - append all `_ChopResult` values to the same `results` list.

2. Keep eligibility checks in the main thread as they are now. This is important because `_is_agent_eligible()` mutates
   `_agent_pids` and consults the durable agent-chop registry.

3. Add focused tests in `tests/test_axe_lumberjack_agent_chops.py`:
   - two eligible agent chops are launched sequentially in config order;
   - when the first mocked launch simulates a workspace claim becoming visible, the second launch sees the updated state
     instead of racing with the same workspace;
   - script chop concurrency remains covered by existing multi-chop tests, or add a minimal guard if the refactor makes
     that contract less obvious.

4. Run focused tests first:

```bash
just install
uv run pytest tests/test_axe_lumberjack_agent_chops.py tests/test_axe_lumberjack.py
```

5. Run the repo-required verification after code changes:

```bash
just check
```

## Non-Goals

This plan does not attempt a broad launch-pipeline redesign. There is a deeper TOCTOU issue in generic workspace
allocation paths that call `get_first_available_axe_workspace()` separately from `claim_workspace()`. That deserves a
separate change, likely by introducing a pre-spawn reservation/transfer flow or making launch preparation support a
dynamic atomic allocation callback. The immediate axe notifications are caused by same-lumberjack concurrent agent chop
launches, so this fix should stop the recurring alerts with a small, low-risk behavioral change.

## Validation

Success criteria:

- a `run_every` tick with both `sase_pylimit_split` and `sase_fix_just` eligible no longer produces
  `Failed to claim workspace #100`;
- both agents are still launched and tracked in the chop registry;
- run_every timestamps update only for successful launches, preserving retry behavior on real failures;
- `just check` passes.

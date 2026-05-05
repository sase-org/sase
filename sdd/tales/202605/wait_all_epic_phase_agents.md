---
create_time: 2026-05-05 10:00:59
status: done
prompt: sdd/prompts/202605/wait_all_epic_phase_agents.md
---
# Wait for All Epic Phase Agents

## Context

`sase bead work <epic_id>` builds an `EpicWorkPlan` in the Rust core and the Python layer renders that plan into a
multi-prompt. Each phase segment gets a stable agent name equal to the phase bead id. The land segment gets the epic id
as its agent name and waits on `plan.land_waits_on`.

The current Rust planner computes `land_waits_on` as the leaf phase agents: open phases that no other open phase depends
on. That is enough when the dependency graph fully represents every required phase ordering relationship, but it does
not match the desired product behavior: the landing agent should not start until every launched phase agent has
completed, even when several phase agents were running concurrently and a leaf or final-wave agent completes before
another parallel phase agent.

## Goal

Make epic landing agents wait on every launched phase agent, not only the final or leaf phase agents.

## Proposed Approach

1. Update the shared Rust planner contract in `../sase-core/crates/sase_core/src/bead/work.rs`.

   `build_epic_work_plan_from_issues` should populate `land_waits_on` from all non-closed phase ids included in the
   plan, mapped through `phase_agent_name`, in the same deterministic ordering already used for phase scheduling. This
   keeps the behavior consistent for Python, CLI, TUI, editor integrations, and any future caller of the core planner.

2. Keep phase-to-phase waits unchanged.

   Phase agents should still wait only on their explicit in-epic open blockers. The change is only the land agent's
   barrier: it should become a full launched phase barrier.

3. Update Python-facing expectations and snapshots.

   Adjust `tests/test_bead/test_work.py` cases that currently assert leaf-only land waits. In linear chains, diamond
   DAGs, and ChangeSpec rendering, the land prompt should now render `%w:` with all launched phase agent names. Existing
   independent fan-out behavior already expects all phases and should remain a useful guard.

4. Update Rust unit coverage.

   Change the core diamond planner test to assert all phase agents are included in `land_waits_on`. Add or adjust a
   mixed-DAG test where a late leaf can finish before an unrelated earlier-wave phase; the expected land wait list
   should include both branches and their intermediate phases.

5. Refresh user-facing descriptions.

   Update docstrings or CLI summary wording that says the land segment waits on leaf phase agents. Keep the dry-run and
   launch summaries accurate by relying on `plan.land_waits_on`.

## Ordering and Compatibility

The wait list should be stable and readable. The safest ordering is the existing planner's phase order: wave order, with
phase order inside each wave sorted by created time then bead id. This mirrors the rendered multi-prompt order and
avoids surprising churn from set ordering.

This broadens the wait condition but should not break valid workflows. If a phase agent has already completed before the
land agent reaches its wait check, the existing `%w` dependency resolution should treat it as satisfied. The main
behavioral impact is that landing waits longer in cases where a non-leaf or parallel phase is still running, which is
the requested fix.

## Verification

Run focused tests first:

```bash
just install
pytest tests/test_bead/test_work.py tests/test_bead/test_cli_work_epic.py
```

Run Rust core tests for the changed planner:

```bash
cargo test -p sase_core bead::work
```

Because this repo's guidance requires it after changes, finish with:

```bash
just check
```

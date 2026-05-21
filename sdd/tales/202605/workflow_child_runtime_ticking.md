---
create_time: 2026-05-21 15:31:49
status: done
prompt: sdd/prompts/202605/workflow_child_runtime_ticking.md
---
# Fix Workflow Plan/Code Child Runtime Ticking on the Agents Tab

## Symptom

In the user's `sase ace` snapshot, the `#sase` workflow root and its workflow children render their runtime
inconsistently:

```
≡ 🎭 sase (TALE APPROVED) ×6 −3 @axq.cld         14:49:20 · 🏃‍♂️ 6m27s   ← frozen, never ticks
  └─ 1/1-plan 🎭 main (RUNNING) @axq.cld-plan   14:49:20 · 🏃‍♂️ 6m27s   ← frozen, identical to root
  └─ 1/1-code 🎭 sase (TALE APPROVED) @axq.cld-code                       ← no runtime suffix at all
  └─ 1e/1 🐚 diff (DONE) ▼#gh
```

Two distinct bugs are visible here:

1. The root row shows the `🏃‍♂️` running emoji and a frozen `6m27s` value. The row IS being patched every second (because
   at least one descendant ticks), but the computed value never changes — so the runtime looks frozen.
2. The `1/1-code` workflow child has status "TALE APPROVED" — meaning the coder agent is actively implementing the
   approved plan — yet no runtime suffix is rendered. It should show a ticking `🏃‍♂️ <elapsed>` like its sibling.

## Root Cause Analysis

All affected logic lives in `src/sase/ace/tui/models/agent_time.py`. The Rust core is not involved — runtime computation
for the Agents tab is a pure Python presentation concern in `sase-org/sase_10`.

### Bug 1 — `1/1-plan` row freezes at plan submission while the planner is still RUNNING

`_is_planner_phase_row()` (line 118) returns `True` for any workflow agent step whose `step_name == "plan"`,
**regardless of status**:

```python
def _is_planner_phase_row(agent: "Agent") -> bool:
    if agent.status in {"PLAN DONE", "TALE DONE"}:
        return True
    if agent.parent_workflow is None or agent.step_type != "agent":
        return False
    if canonical_plan_chain_suffix(agent.role_suffix) == PLAN_CHAIN_PLAN_SUFFIX:
        return True
    return agent.step_name in _WORKFLOW_PLAN_STEP_NAMES or (
        agent.cl_name in _WORKFLOW_PLAN_STEP_NAMES
    )
```

For `1/1-plan` (parent_workflow set, step_type="agent", step_name="plan", status="RUNNING", `plan_times=[14:49:20]`):

- `_is_planner_phase_row()` returns True via the `step_name == "plan"` fallback even though the planner is still
  RUNNING.
- `_row_runtime_terminal_time()` returns `max(plan_times)` = 14:49:20 — a frozen terminal time.
- `_leaf_runtime_interval()` builds an interval with `active=False`, elapsed locked at plan‑time − run_start_time.
- The row is therefore treated as "finished at the planner phase" and the value never changes on each refresh.

Prior tales (`sdd/tales/202605/plan_step_runtime_1.md`, `plan_approved_runtime_parent_child.md`) introduced this "freeze
planner row at PLAN" behavior — but only validated the **completed** case (status `PLAN DONE` / `TALE DONE`) and the
top-level `.plan` plan-chain row. The regression here is that the workflow-child fallback (`step_name == "plan"`) also
fires while the planner is still actively RUNNING, which was never the intent.

### Bug 1 cascades to the root via `_aggregate_runtime`

The workflow root has `runtime_children = [1/1-plan, 1/1-code, 1e/1 diff]`. `_aggregate_runtime()` sums child intervals:
the plan child contributes a frozen `(terminal=14:49:20, active=False, elapsed=6m27s)`, the code child contributes
nothing (Bug 2), and the diff bash step is terminal/None. The aggregate therefore inherits
`active=False, terminal=14:49:20` and the root row also freezes.

`runtime_suffix_ticks(root)` still returns True (because `runtime_suffix_ticks(1/1-plan)` returns True for status
RUNNING + run_start_time), so the row is patched every second — but each patch produces the same string, which is why
the user sees `🏃‍♂️` but a frozen duration.

### Bug 2 — `1/1-code` row has no runtime suffix at all

The coder workflow child has status "TALE APPROVED" (inherited / enriched from the family root's plan-approval metadata)
and presumably its own `run_start_time` set when the coder process started at 15:06:24. Tracing through
`_leaf_runtime_interval()`:

- `_row_runtime_terminal_time()` returns None (not in `{PLAN DONE, TALE DONE}`, no stop_time, status not in
  PLAN/QUESTION).
- `_segmented_followup_runtime_interval()` matches the status but bails immediately: it requires both
  `agent.code_time is not None` and `agent.plan_times` to be non-empty. Those fields live on the **planner** (the
  `.plan` chain agent), not on a workflow's code-step child, so this returns None for `1/1-code`.
- Status "TALE APPROVED" is not in `_ACTIVE_LEAF_STATUSES = {"RUNNING", "RETRYING"}`.

Result: the leaf interval is None, no runtime renders, no `🏃‍♂️` appears, even though the coder is genuinely running.
`runtime_suffix_ticks()` likewise returns False for this row.

### Why the existing PLAN APPROVED / TALE APPROVED handling doesn't cover the workflow case

`_SEGMENTED_FOLLOWUP_RUNTIME_STATUSES = {"PLAN APPROVED", "TALE APPROVED"}` and the segmented interval was designed for
the **family-style** flow:

- a single top-level `.plan` agent that has submitted a plan, then has a separate `.code` follow-up child running;
- its runtime is "RUN→PLAN" (planning) plus "CODE→now" (coding), skipping the approval gap.

In the **workflow-style** flow (`#sase` YAML workflow), the planner and coder are independent workflow children with
their own `start_time` / `run_start_time` / `stop_time`. They should not depend on the planner's `plan_times` /
`code_time` aggregation. The TALE APPROVED status on the coder child is essentially an "actively running" indicator with
the parent's plan‑approval color/label, but the runtime logic has no path for it.

## Proposed Fix

All changes are in `src/sase/ace/tui/models/agent_time.py`. Tests live alongside the existing runtime tests in
`tests/ace/tui/widgets/test_agent_list_runtime_model.py` (and `_rendering.py`).

### 1. Narrow `_is_planner_phase_row` so it doesn't freeze actively-RUNNING planner rows

The function should only treat a row as "planner phase, terminal at PLAN" when the planner phase has actually ended. The
current implementation conflates "this row represents the planning phase" with "this row is done planning". Tighten the
workflow-child fallback so it only fires once the row has truly stopped or is in a "plan‑done" terminal status.

Concretely, gate the workflow-child fallback on at least one of:

- `agent.stop_time is not None` (planner has exited), OR
- `agent.status` in a small set of "planning is over" statuses (the existing `{PLAN DONE, TALE DONE}` plus `DONE`,
  `FAILED`, `FAILED (RETRIED)`, `PLAN REJECTED`).

Top-level rows with `role_suffix == .plan` should keep the same gating — an actively RUNNING / PLAN APPROVED top-level
plan-chain row must not freeze either. (The existing `PLAN APPROVED` / `TALE APPROVED` segmented‑runtime path already
handles its case; making it terminate at PLAN would re-introduce the bug fixed in
`plan_approved_runtime_parent_child.md`.)

When this fix lands, the `1/1-plan` row will no longer have `terminal_time` set while RUNNING:

- `_leaf_runtime_interval()` falls through to the `_ACTIVE_LEAF_STATUSES` branch (status="RUNNING"),
- returns `(elapsed=now - run_start_time, terminal=None, active=True)`,
- the row renders a live ticking `🏃‍♂️ <elapsed>`.

The root then aggregates an **active** plan-child interval, so the root row also ticks.

### 2. Add a runtime path for actively running workflow code children with `(PLAN|TALE) APPROVED` status

Add a fallback inside `_leaf_runtime_interval()` (or just before the existing `_ACTIVE_LEAF_STATUSES` check) that covers
the workflow-coder case:

- Triggered when `agent.status` ∈ `_SEGMENTED_FOLLOWUP_RUNTIME_STATUSES` AND the row is a workflow agent child
  (`agent.parent_workflow is not None`, `agent.step_type == "agent"`) AND `agent.stop_time is None` AND
  `agent.run_start_time is not None`,
- Returns a simple active interval anchored at `run_start_time`:
  `(elapsed=now-run_start_time, terminal=None, active=True)`.

This is intentionally narrow — it does not affect family-style top-level `.plan` rows (the existing segmented followup
path keeps owning those) and does not touch DONE rows.

### 3. Mirror the fix in `runtime_suffix_ticks`

`runtime_suffix_ticks()` (line 292) needs the same fallback so the row is actually patched on each tick. Add:

- If status ∈ `_SEGMENTED_FOLLOWUP_RUNTIME_STATUSES` AND the agent is a workflow agent child AND `stop_time is None` AND
  `run_start_time is not None`, return True.

Without this, the new runtime would render once but not tick.

### 4. Optional: cleanup the dead `cl_name in _WORKFLOW_PLAN_STEP_NAMES` branch

The `cl_name in _WORKFLOW_PLAN_STEP_NAMES` fallback in `_is_planner_phase_row` looks like a defensive remnant; if the
tightened gate makes it dead code, drop it to keep the predicate honest. Confirm with grep / tests before removing.

## Test Plan

Add focused regressions to `tests/ace/tui/widgets/test_agent_list_runtime_model.py` (or a sibling file) that mirror the
user's snapshot exactly:

1. **Active planner workflow child does NOT freeze at plan_time.**
   - Build a workflow root + child `Agent` with `parent_workflow`, `step_type="agent"`, `step_name="plan"`,
     `status="RUNNING"`, `start_time`, `run_start_time`, `plan_times=[T]`, `stop_time=None`.
   - Assert `compute_row_runtime(child, now=T + 60s)` returns `(None, "...")` with elapsed > the PLAN-locked value
     (`active=True`, no terminal timestamp).
   - Assert `runtime_suffix_ticks(child)` is True.

2. **Completed planner workflow child still freezes at plan_time (regression guard).**
   - Same shape, but with `status="PLAN DONE"` (or stop_time set).
   - Assert terminal_time == max(plan_times), elapsed == plan_time − run_start_time, `active=False`.

3. **Workflow coder child with TALE APPROVED ticks from its own run_start_time.**
   - Build a workflow code child with `step_name="code"`, `step_type="agent"`, `status="TALE APPROVED"`, `start_time`,
     `run_start_time`, `stop_time=None`, no `code_time`/`plan_times`.
   - Assert `compute_row_runtime(child, now=run_start + 90s)` returns `(None, "1m30s")`, `active=True`.
   - Assert `runtime_suffix_ticks(child)` is True.

4. **Workflow root aggregates active plan+code children and ticks.**
   - Build the full root + active plan child + active code child + DONE diff child.
   - Assert the root's aggregated interval is `active=True`, elapsed equals the sum of the two ticking child intervals,
     and `runtime_suffix_ticks(root)` is True.

5. **Family-style top-level `.plan` PLAN APPROVED path remains unchanged.**
   - Reuse the existing test setup from `plan_approved_runtime_parent_child.md`'s regression coverage to ensure the
     segmented `RUN→PLAN + CODE→now` behavior still applies for top-level plan-chain rows.

Run the targeted tests first, then `just install` (workspace may be stale), then the full `just check`.

## Non-Goals

- No Rust core change. Runtime computation for the Agents tab is Python/Textual presentation only — this fits the
  `memory/short/rust_core_backend_boundary.md` litmus test.
- No change to how `_active_approved_plan_handoff_status` or `_planner_child_status` decide statuses; we only adjust
  runtime rendering for the statuses already in place.
- No change to how `plan_times`, `code_time`, `run_start_time` are populated. We are fixing the consumer, not the data
  pipeline.
- No general redesign of `_SEGMENTED_FOLLOWUP_RUNTIME_STATUSES`. The workflow-child case is handled as a narrow,
  additive fallback so the existing family-style behavior is preserved.

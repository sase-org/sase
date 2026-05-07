---
create_time: 2026-05-07 11:31:26
status: done
prompt: sdd/prompts/202605/plan_approved_runtime_parent_child.md
---
# Fix PLAN APPROVED Parent and Planner Child Runtime Interaction

## Context

Recent runtime fixes landed in the ACE TUI runtime model:

- Parent/workflow rows can aggregate the runtimes of direct child agent steps.
- `PLAN APPROVED` rows can show a segmented active runtime of `BEGIN -> PLAN` plus `CODE -> now`.
- Planner child rows now end their runtime at the plan submission timestamp instead of at a later workflow stop time.

The current `sase ace` snapshot shows these changes conflicting: the top-level plan-chain row and the child planner row
both show the same static `BEGIN -> PLAN` runtime, while the `.code` follow-up continues separately.

## Root Cause

There are two related bugs.

First, `agent_time._row_runtime_terminal_time()` checks `_is_planner_phase_row()` before the active segmented
`PLAN APPROVED` path. `_is_planner_phase_row()` returns true for any row with `role_suffix == ".plan"`, including the
top-level plan-chain workflow row. That makes the parent row terminal at `PLAN`, so it never reaches the active
`CODE -> now` segment.

Second, `_agent_ordering._attach_runtime_children()` indexes possible parents by `raw_suffix` across both top-level
agents and workflow step rows. Filesystem workflow step rows currently reuse the parent workflow timestamp as their own
`raw_suffix`, so workflow steps overwrite the real parent in `parent_by_suffix`. In live data for `aga.r1.plan`, the
top-level parent has no `runtime_children`, while a hidden workflow step named `resolve` incorrectly owns the planner
and coder runtime children.

## Implementation Plan

1. Fix runtime parent selection in `_agent_ordering`.
   - Build the runtime parent index from real top-level rows only.
   - Do not let workflow child rows with the same `raw_suffix` replace the parent workflow.
   - Preserve existing behavior for non-workflow follow-up chains where a normal agent can own follow-up children.

2. Fix planner-phase terminal detection in `agent_time`.
   - Keep planner child rows static at `PLAN`.
   - Keep terminal top-level `PLAN DONE` rows static at `PLAN`.
   - Allow active top-level `PLAN APPROVED` `.plan` rows with `code_time` to use segmented runtime and tick.

3. Add focused regression tests.
   - Use realistic workflow step data where the planner child shares the parent `raw_suffix`.
   - Assert `sort_and_reorder()` attaches the planner step and `.code` follow-up to the top-level parent, not to a
     workflow child.
   - Assert an active top-level `.plan` `PLAN APPROVED` row ticks while the child planner row stays fixed at `PLAN`.
   - Add rendering/patching coverage if the model-level coverage is not enough to protect the UI path.

4. Validate.
   - Run the focused runtime/order tests first.
   - Run `just install` if this workspace needs dependency refresh.
   - Run the required full `just check` after edits.

## Non-Goals

- No Rust core change: this is ACE TUI presentation and relationship assembly logic.
- No broad redesign of agent identity or loader timestamp semantics.
- No changes to plan-chain artifact writing unless tests prove the displayed data cannot be corrected in the TUI model.

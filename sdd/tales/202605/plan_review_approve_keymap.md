---
create_time: 2026-05-09 22:38:04
status: wip
prompt: sdd/prompts/202605/plan_review_approve_keymap.md
---
# Plan: Plan Review Approve/Tale Keymaps

## Context

The Plan Review modal has four product-level approval choices:

- `approve`: approve the plan without committing it into SDD, then run the coder.
- `tale`: commit the plan into `sdd/tales`, then run the coder.
- `epic`: commit into `sdd/epics`, then launch the epic follow-up workflow.
- `legend`: commit into `sdd/legends`, then launch the legend follow-up workflow.

The custom approval modal already exposes the intuitive direct action mapping:

- `a` = Approve
- `t` = Tale
- `e` = Epic
- `l` = Legend

The main Plan Review modal is currently inconsistent: it binds `a` to an action labeled `Tale`, and `action_approve()`
actually returns the `tale` choice. This makes the quickest path for a normal "approve but do not create an SDD tale"
unavailable from the main panel.

## Implementation Plan

1. Update `src/sase/ace/tui/modals/plan_approval_modal.py`.
   - Change the `BINDINGS` entry for Tale from `("a", "approve", "Tale")` to `("t", "tale", "Tale")`.
   - Add a new `("a", "approve", "Approve")` binding.
   - Update the footer hint text to show `a=Approve` and `t=Tale`.
   - Change `action_approve()` so it returns `plan_approval_result_for_choice("approve")`.
   - Add `action_tale()` so it returns `plan_approval_result_for_choice("tale")`.

2. Preserve the existing protocol boundary.
   - Do not introduce new runner protocol values. Both direct actions should still emit
     `PlanApprovalResult(action="approve")`, with the existing `commit_plan`/`run_coder` flags carrying the behavioral
     difference.
   - This keeps downstream handling in `_notification_modals.py` and `run_agent_exec_plan` unchanged.

3. Update focused tests in `tests/test_plan_approval_modal_title.py`.
   - Replace the old assertion that `a` means Tale with assertions that `a` means Approve and `t` means Tale.
   - Update the direct action test so `action_approve()` returns `choice="approve"`, `commit_plan=False`, and
     `run_coder=True`.
   - Add a direct action test for `action_tale()` returning `choice="tale"`, `commit_plan=True`, and `run_coder=True`.

4. Run targeted validation first.
   - Run the Plan Approval modal tests and the plan rejection/approval protocol tests that exercise these result
     mappings.

5. Run repo validation.
   - Per repo memory, run `just install` if needed and then `just check` after code changes.

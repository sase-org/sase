---
create_time: 2026-05-19 09:06:01
status: done
prompt: sdd/prompts/202605/agent_family_workflow_step_status.md
---
# Plan: Agent Family Workflow Step Status Fix

## Goal

Fix the remaining agent-family display issues shown by the `ap5` ACE snapshot:

- completed non-agent workflow children must display terminal `DONE`, not `PLAN`;
- the planner child row under a family root must have a distinct family-step identity such as `ap5-plan`, not the same
  `ap5` identity as the root;
- a completed planner child must show `DONE` after the workflow has handed off to later child agents;
- child rows must remain nested under the root workflow entry and must not sort above it.

## Diagnosis

The historical `ap5` artifacts show a root `agent_meta.json` with `agent_family=ap5`, `agent_family_role=root`, and
`role_suffix=-plan`. The workflow `prompt_step_*.json` files themselves do not carry those family fields. During
workflow-step loading, `enrich_agent_from_meta()` reads the parent artifact `agent_meta.json` for every prompt-step row.
That copies root-only plan-family metadata onto bash/python steps as well as the main agent step.

The status override pass then sees all workflow children as `-plan` rows. It synchronizes them from the root planner
state, which rewrites completed bash/python rows to `PLAN`. The real main agent step also remains `PLAN` because
`_planner_child_status()` treats a submitted plan with no feedback as awaiting review even when a later family follow-up
child exists.

## Implementation Plan

1. Split root metadata from workflow-step identity.
   - When enriching workflow child rows from the parent artifact metadata, keep useful shared fields such as model,
     provider, paths, workspace, plan/question timestamps, and response metadata.
   - Do not blindly copy root-only `agent_name`, `agent_family_role=root`, `plan_chain_root`, or `role_suffix=-plan` to
     every workflow child.
   - For the concrete main agent step of a root plan workflow, derive a child identity from the family name and planner
     role: `agent_name=ap5-plan`, `agent_family=ap5`, `agent_family_role=plan`, `role_suffix=-plan`.

2. Restrict planner synchronization to actual planner agent rows.
   - Only sync workflow children that are `step_type == "agent"` and are the main workflow agent step.
   - Leave bash/python embedded workflow steps with their own loader status mapping, so completed steps remain `DONE`.

3. Make planner child terminal once the workflow has handed off.
   - Teach the planner-child status helper that a family root with a later follow-up child is no longer waiting for plan
     review.
   - Keep active/question/rejected handling intact: unanswered questions still show `QUESTION`, failed rows still show
     `FAILED`, and genuinely awaiting review rows still show `PLAN`.

4. Protect ordering.
   - Add a regression around `sort_and_reorder()` using an `ap5`-shaped root, planner step, code follow-up, and
     bash/python children.
   - Assert the root remains before all child rows and the planner/code/non-agent steps remain nested in the expected
     order.

5. Verify.
   - Add focused Python tests for status override and ordering behavior.
   - Run the focused tests first.
   - Run `just install` before broad validation, then `just check` as required by the workspace notes.
   - Launch `.venv/bin/sase ace --tmux`, expand the `ap5` family, capture the pane, and verify:
     - root `@ap5` remains the parent row;
     - planner child appears as `@ap5-plan` and displays `DONE`;
     - non-agent workflow children display `DONE`;
     - no child appears above the root.

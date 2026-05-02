---
create_time: 2026-04-25 09:57:41
status: done
prompt: sdd/prompts/202604/agent_status_state_fix.md
---
# Plan: Fix ACE Plan/Question Status Drift

## Context

The snapshot shows a plan-driven agent workflow in an impossible state:

- The parent workflow still shows `QUESTION` even though the user answered the question and approved the plan.
- The follow-up planner child `1/1.plan` shows `PLANNING` even though it completed and launched a coder.

The live artifacts and loader code point to two separate state derivation bugs rather than a display-only issue.

## Root Cause

First, answered user-question notifications are not marked dismissed by `handle_user_question()`. The notification
scanner treats every unread `UserQuestion` notification as authoritative and reapplies a `QUESTION` status override on
each refresh. That can keep the parent workflow stuck at `QUESTION` even after a response was written and later plan
approval occurred.

Second, `_apply_status_overrides()` applies its `DONE -> PLANNING` top-level plan rule to any workflow agent with
`role_suffix == ".plan"`. Follow-up planner agents created after a question or feedback round also have `.plan` and
`parent_timestamp` set, so a completed child planner can be mislabeled `PLANNING`. That rule should only apply to
top-level plan workflows, not follow-up children.

## Implementation Plan

1. Add a focused regression test for answered user questions:
   - Build a minimal fake app and `UserQuestion` notification.
   - Drive `handle_user_question()` through its modal dismissal callback.
   - Assert it writes `question_response.json`, restores the previous status, and marks the notification dismissed.

2. Fix `handle_user_question()`:
   - After successfully writing `question_response.json`, call `mark_dismissed(notification.id)`.
   - Keep status restoration after the response write so the agent can continue immediately.
   - Avoid marking dismissed if the modal is canceled or the response write fails.

3. Add a loader regression test for completed follow-up planner children:
   - Create a top-level parent workflow and a child with `role_suffix=".plan"`, `parent_timestamp` pointing to the
     parent, and `status="DONE"`.
   - Include a `.code` child for the same parent to model approved plan execution.
   - Assert the parent becomes `PLAN APPROVED` while the `.plan` child remains `DONE`.

4. Fix `_apply_status_overrides()`:
   - Restrict top-level plan status transitions (`DONE -> PLAN DONE` / `EPIC CREATED` and `DONE -> PLANNING`) to
     non-child plan workflow agents.
   - Preserve existing behavior for root `.plan` workflows and active `.code`, `.commit`, `.epic`, and feedback
     children.

5. Verify:
   - Run the focused tests for notification handling and loader overrides.
   - Run `just install` if needed, then `just check` per repo instructions.

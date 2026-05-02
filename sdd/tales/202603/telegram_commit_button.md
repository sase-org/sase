---
create_time: 2026-03-25 15:25:39
status: done
prompt: sdd/prompts/202603/telegram_commit_button.md
---

# Plan: Add Commit Button to Telegram Plan Approval Messages

## Summary

Add a "Commit" button to Telegram plan approval messages that saves the plan without starting a coder agent, and send
confirmation messages with a "Plan" copy button for both Approve and Commit actions.

## Changes

### Phase 1: Telegram Plugin Changes (../sase-telegram)

#### 1.1 Add Commit button to keyboard (formatting.py)

- In `_format_plan_approval()`, add a "📦 Commit" button with callback `plan:PREFIX:commit`
- New layout:
  - Row 1: [Approve] [Commit] [Epic]
  - Row 2: [Reject] [Feedback]

#### 1.2 Handle commit callback in pure logic (inbound.py)

- In `process_callback()`, under the `cb.action_type == "plan"` block, add a `commit` choice that returns a
  `ResponseAction` with `response_data={"action": "commit"}` and `answer_text="Plan committed"`

#### 1.3 Store plan file in pending actions (sase_tg_outbound.py)

- When saving a PlanApproval pending action, also store the notification's plan file path as `"plan_file"` in the
  pending action entry

#### 1.4 Send confirmation message after approve/commit (sase_tg_inbound.py)

- Add a helper function `_send_plan_confirmation(action: dict, choice: str)` that:
  - Sends "Plan approved" or "Plan committed" message
  - Includes a "Plan" CopyTextButton that copies the relative path of the plan file
  - Computes relative path using `action["action_data"].get("project_dir")` with fallback to basename
- Call this helper from `_handle_callback()` after writing the response for plan approve/commit choices

### Phase 2: Core Changes (sase_100 repo)

#### 2.1 Accept "commit" in plan polling (\_plan_utils.py)

- Change `if action in ("approve", "epic"):` to `if action in ("approve", "epic", "commit"):`

#### 2.2 Handle commit in runner (run_agent_exec.py)

- Add check for `plan_result.action == "commit"` that saves SDD files but breaks the loop with
  `loop_outcome = "plan_committed"` instead of spawning a follow-up agent

### Phase 3: Tests

#### 3.1 Update formatting tests

- Add test verifying the new "Commit" button exists in the plan approval keyboard

#### 3.2 Update inbound tests

- Add test for `process_callback()` with choice="commit"

#### 3.3 Update \_plan_utils tests

- Add test that "commit" action is accepted and returns PlanApprovalResult

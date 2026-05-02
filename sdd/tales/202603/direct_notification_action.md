---
create_time: 2026-03-27 13:40:28
status: done
prompt: sdd/prompts/202603/direct_notification_action.md
---

# Plan: Direct Notification Action on `,n`

## Problem

Currently, pressing `,n` on the Agents tab:

1. Finds the notification matching the currently selected agent
2. Opens the `NotificationModal` with that notification pre-selected
3. User must press Enter to trigger the actual action (e.g., PlanApproval modal, UserQuestion modal)

This extra Enter step is unnecessary friction since `,n` already identifies exactly which notification to act on.

## Desired Behavior

Pressing `,n` should skip the `NotificationModal` entirely and directly trigger the notification's action handler
(`handle_plan_approval`, `handle_user_question`).

## Analysis

The relevant notification types for `,n` are **PlanApproval** and **UserQuestion** — the only types that set agent
status to `PLANNING` or `QUESTION`, which is the condition for `,n` to activate.

Currently, `_jump_to_agent_notification()` (in `_notifications.py:264-318`) does:

1. Find the current agent (must be in PLANNING/QUESTION status)
2. Search unread notifications for a matching PlanApproval/UserQuestion notification
3. Call `_show_notification_modal(initial_index=...)` → opens the modal

The `_show_notification_modal()` method (lines 320-374) opens the modal and has an `_on_dismiss` callback that
dispatches the action. The key dispatch logic is:

```python
if result.action == "PlanApproval":
    handle_plan_approval(self, result)
elif result.action == "UserQuestion":
    handle_user_question(self, result)
```

## Implementation

### File: `src/sase/ace/tui/actions/agents/_notifications.py`

**Change `_jump_to_agent_notification()`** — instead of calling `_show_notification_modal(initial_index=...)` at the
end, directly dispatch the found notification's action:

1. Keep all the existing logic for finding the agent and matching notification (lines 264-316)
2. After finding the matching notification, instead of opening the modal, directly call the appropriate handler:
   - If `notification.action == "PlanApproval"` → call `handle_plan_approval(self, notification)`
   - If `notification.action == "UserQuestion"` → call `handle_user_question(self, notification)`
3. After dispatching, call `self._refresh_notification_count()` (same as the modal's `_on_dismiss` does)

The change is ~10 lines in a single method. No config changes needed — the `,n` keymap name (`jump_to_notification`)
still makes sense, and the footer label `notification` is still accurate.

### Potential edge case

If the found notification turns out to be neither PlanApproval nor UserQuestion (shouldn't happen given the
PLANNING/QUESTION status check, but defensively), fall back to the current behavior of opening the notification modal.

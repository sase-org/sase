---
create_time: 2026-03-27 15:16:46
status: done
prompt: sdd/prompts/202603/axe_error_notification_action.md
---

# Plan: Axe Error Digest Notification Action

## Problem

When axe error digest notifications appear in the TUI's notification modal, pressing Enter does nothing meaningful — the
notification is marked as read and dismissed with no follow-up action. This is inconsistent with every other
notification type in the system, all of which provide useful actions (ViewErrorReport opens $EDITOR, JumpToAgent
navigates to the agent tab, PlanApproval opens a modal, etc.).

The digest file is already attached to the notification and viewable via C-n/C-p in the file panel, but there's no
dedicated Enter action.

## Design Decision: Reuse `ViewErrorReport`

**Recommendation: Reuse the existing `ViewErrorReport` action** rather than creating a new action type.

Rationale:

- `handle_view_error_report()` already does exactly what we want: opens an error file in `$EDITOR`
- It already has a fallback to `notification.files[0]` when `error_report_path` is absent — meaning it would work even
  without explicit `action_data`, but we'll include `error_report_path` for clarity
- The `[error]` badge in `_ACTION_BADGES` already maps to `ViewErrorReport` — perfect semantic fit
- Adding a new action type would require changes in 4+ files for zero behavioral difference
- The existing pattern in runner code (crs_runner, fix_hook_runner, etc.) already uses this exact action for error files
  — axe error digests are the same kind of artifact

This is the simplest, most consistent approach and follows the existing conventions exactly.

## Changes

### 1. Update `notify_axe_error_digest()` sender (the only meaningful change)

**File**: `src/sase/notifications/senders.py`

Change the notification construction from:

```python
action=None,
action_data={},
```

to:

```python
action="ViewErrorReport",
action_data={"error_report_path": str(digest_file)},
```

This is a 2-line change. The `error_report_path` key matches what `handle_view_error_report()` reads from `action_data`,
providing a direct path to the digest file rather than relying on the `files[0]` fallback.

### 2. No other files need changes

- **`_notification_handlers.py`**: `handle_view_error_report()` already handles `ViewErrorReport` — no change needed
- **`_notifications.py`**: `_show_notification_modal()` already dispatches `ViewErrorReport` — no change needed
- **`_notification_actions.py`**: Already re-exports `handle_view_error_report` — no change needed
- **`notification_modal.py`**: `_ACTION_BADGES` already maps `ViewErrorReport` to `[error]` — no change needed
- **`sase_chop_error_digest.py`**: Just calls `notify_axe_error_digest()`, no change needed

## Result

After this change:

- Axe error digest notifications display with the `[error]` badge in the notification modal
- Pressing Enter opens the digest file in `$EDITOR` for detailed investigation
- The file is still viewable inline via C-n/C-p for quick glances without leaving the TUI
- Behavior is consistent with how all other runner error notifications work

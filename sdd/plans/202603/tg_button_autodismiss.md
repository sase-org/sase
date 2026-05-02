---
create_time: 2026-03-28 13:14:13
status: wip
prompt: sdd/prompts/202603/tg_button_autodismiss.md
---

# Plan: Auto-dismiss Telegram Buttons on TUI Response

## Problem

When a user responds to a notification (approve/reject/commit/epic/feedback) from the TUI, the Telegram inline keyboard
buttons remain visible. The user can still tap stale buttons, leading to confusion or duplicate responses.

The reverse direction already works: when responding via Telegram, the inbound chop removes buttons via
`edit_message_reply_markup(chat_id, message_id, reply_markup=None)` and the TUI auto-dismisses the notification by
detecting the response file.

## Design

### Approach: Inbound chop cleanup pass (no TUI changes)

Add a cleanup pass to the inbound chop that detects when pending actions have been handled externally (by the TUI) and
removes the corresponding Telegram buttons. This preserves the fully decoupled architecture — the TUI never calls
Telegram APIs and doesn't even know Telegram exists.

**How it works**: The inbound chop already runs every ~5 seconds and loads `pending_actions.list_all()`. After
processing Telegram updates, it scans each pending action and checks whether the corresponding response file already
exists. If it does, the notification was handled by the TUI — remove the buttons, clean up the pending action, and clear
any stale awaiting-feedback state.

### Detection signals per action type

| Action       | "Handled" signal                                                                                        |
| ------------ | ------------------------------------------------------------------------------------------------------- |
| PlanApproval | `{response_dir}/plan_response.json` exists OR `plan_approved.marker` exists OR `plan_request.json` gone |
| HITL         | `{artifacts_dir}/hitl_response.json` exists                                                             |
| UserQuestion | `{response_dir}/question_response.json` exists                                                          |

These are the same signals the TUI's `_auto_dismiss_external_plan_response()` already uses, just checked from the
Telegram side.

## Changes

### 1. `sase-telegram/src/sase_telegram/inbound.py` — Add `find_externally_handled()`

Pure logic function (no Telegram API calls, consistent with module's design):

```python
def find_externally_handled(
    pending: dict[str, Any],
) -> list[tuple[str, int, str]]:
    """Find pending actions whose notifications were handled externally (e.g. TUI).

    Returns list of (notif_id_prefix, message_id, chat_id) for actions that
    should have their Telegram buttons removed.
    """
```

For each entry in `pending` where `action` is in `{PlanApproval, HITL, UserQuestion}`:

- Derive the response file path from `action_data` (same logic as `process_callback`)
- Check existence of response file (plus marker/request-gone for PlanApproval)
- If handled, include in return list

### 2. `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py` — Add cleanup in `main()`

After the existing update-processing loop, add:

```python
# Clean up pending actions handled by the TUI (remove stale buttons)
handled = find_externally_handled(pending)
for prefix, message_id, chat_id in handled:
    try:
        telegram_client.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
    except Exception:
        pass  # Message may have been deleted or already edited
    pending_actions.remove(prefix)
    # Clear stale two-step feedback state if it references this action
    awaiting = load_awaiting_feedback()
    if awaiting and awaiting.get("prefix") == prefix:
        clear_awaiting_feedback()
```

**Important**: Re-read `pending_actions.list_all()` AFTER processing updates (since `_handle_callback` may have already
removed some entries) to avoid double-processing.

## Edge Cases

- **Race condition**: Both TUI and Telegram handle the same notification simultaneously. All operations are idempotent:
  `edit_message_reply_markup` on an already-edited message is a no-op, `pending_actions.remove` on a missing key returns
  False, and writing a response file that already exists is harmless.
- **Reject without feedback from TUI**: No response file is written; instead the agent is killed and `plan_request.json`
  is eventually cleaned up. The "request gone" check covers this case.
- **Stale awaiting_feedback**: If the TUI responds while Telegram is mid-way through a two-step feedback flow, the
  cleanup clears the stale state so the next text message isn't misinterpreted as feedback for an already-handled
  notification.
- **Non-actionable pending actions**: `kill-{name}` and `retry-{name}` entries lack an `action` field matching
  `_ACTIONABLE_ACTIONS`. The cleanup function skips these.

## Testing

- Unit test `find_externally_handled()` with mocked file system: create response files for some pending actions, verify
  correct detection.
- Unit test the cleanup integration: verify that when a response file exists, buttons are removed and pending action is
  cleaned up.

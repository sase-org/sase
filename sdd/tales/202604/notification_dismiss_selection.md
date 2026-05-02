---
create_time: 2026-04-30 03:28:51
status: done
prompt: sdd/prompts/202604/notification_dismiss_selection.md
---
# Plan: Deterministic notification selection after dismiss

## Problem

The notification modal renders notifications in section order (`PRIORITY`, `INBOX`, `MUTED`) while each selectable
option stores the notification's raw `_notifications` list index as its option id. Dismiss currently pops the raw index
and then rebuilds with `highlight_index=min(idx, len(_notifications) - 1)`. That chooses the next item by raw storage
order, not by the order the user sees in the sectioned list.

This explains the "random" behavior: when the highlighted notification is followed by a different notification in visual
order than in raw list order, dismissing can highlight a later raw-list neighbor instead of the row directly below the
dismissed row.

## Goal

After dismissing a notification with the `x` flow, and after confirming with `y` for plan/question notifications, the
modal should highlight the next selectable notification in the currently displayed list order. If the dismissed row was
the final visible notification, keep the modal usable by highlighting the previous remaining visible notification. If no
notifications remain, show the empty state as it does today.

## Design

1. Add a small helper on `NotificationModal` that derives the current visual notification index order from
   `_create_sectioned_options()`, skipping disabled section headers.
2. Before mutating `_notifications`, compute the replacement notification id/index from that visual order:
   - find the dismissed raw index in the visual order;
   - prefer the next visual notification after it;
   - otherwise fall back to the previous visual notification;
   - return `None` if the dismissed notification was the only selectable row.
3. In `_dismiss_notification_by_index`, compute that replacement before `pop`, dismiss and remove the selected
   notification, then rebuild using the replacement notification's new raw index. Re-resolving by notification id after
   the pop avoids stale raw-index ids.
4. Keep the existing `_rebuild_list(highlight_index=...)` contract unchanged: it still receives a notification index and
   translates it to an `OptionList` row after the list is rebuilt.
5. Add focused unit coverage for visual-order replacement, especially a mixed section order where raw-list order differs
   from displayed order. Existing single-item dismiss and confirmation tests should continue to assert the empty-state
   behavior.

## Verification

Run the focused notification modal tests first:

```bash
pytest tests/test_notification_modal.py
```

Because this repo's instructions require it after file changes, run the full check after the implementation:

```bash
just install
just check
```

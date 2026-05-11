---
create_time: 2026-05-11 18:29:49
status: wip
prompt: sdd/prompts/202605/agent_unread_completion_notification_dismiss.md
---
# Plan: Dismiss completion notifications when unread agents are acknowledged

## Goal

When a user selects an unread terminal agent in the `sase ace` Agents tab and that selection marks the row read, any
outstanding agent-completion notification should also be dismissed. The change must preserve the current navigation
performance characteristics.

## Current shape

- The Agents tab tracks unread completed rows in `_unread_completed_agent_ids`.
- Selection paths call `_acknowledge_agent_unread(agent)`, which delegates to `_clear_agent_unread(agent)` and then
  patches or refreshes the visible row.
- Completion notifications are already dismissed by `AgentNotificationMixin._request_agent_completion_dismiss(...)`,
  which schedules `_dismiss_agent_completion_notifications_for_agents_tab(...)`.
- That dismissal helper is intentionally cheap on the hot path:
  - it returns immediately if a dismissal is already in flight;
  - when `force=False`, it also returns immediately unless `_agent_completion_ack_latch` is armed;
  - actual notification-store I/O runs off the main thread;
  - the notification indicator refresh runs only if the store reports a real change.
- The helper is currently triggered on Agents-tab entry and Agents-tab user activity, but a direct row-selection
  acknowledgement can clear local unread state without explicitly requesting notification dismissal.

## Design

1. Keep the notification-store semantics in the existing completion-dismiss helper. Do not add a new scan or per-row
   notification lookup to selection handling.
2. After `_acknowledge_agent_unread(agent)` successfully clears local unread state, call
   `_request_agent_completion_dismiss(force=False)` when that method exists.
3. Keep the call after `_clear_agent_unread(...)` succeeds, so manual-unread guarded rows and already-read rows do
   nothing.
4. Keep `force=False` so the call is a constant-time latch check in the common case. If the latch is clear, no worker is
   spawned and no disk I/O happens. If the latch is armed, the existing async bulk primitive dismisses the outstanding
   completion rows without blocking selection or j/k navigation.
5. Update the stale comment in `_clear_agent_unread(...)` so it reflects the new selection-ack trigger while preserving
   the fact that agent kill/dismiss flows handle interactive notifications separately.

## Tests

Add focused tests in `tests/ace/tui/test_agent_unread_selection.py`:

- A successful unread acknowledgement requests completion dismissal with `force=False`.
- A manual unread guarded acknowledgement does not request dismissal.
- An already-read row does not request dismissal.

Keep the existing assertions that `dismiss_notifications_matching_agents` is not called, because the change should not
revive the old per-agent interactive notification dismissal path.

## Verification

Run the focused tests first:

```bash
pytest tests/ace/tui/test_agent_unread_selection.py tests/ace/tui/test_agents_tab_completion_dismiss.py
```

Because this repo requires a full check after code changes, run:

```bash
just install
just check
```

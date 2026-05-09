---
create_time: 2026-05-08 23:57:52
status: done
prompt: sdd/prompts/202605/dismiss_agent_completion_notifications_on_read.md
---
# Plan: Dismiss Agent Completion Notifications When Agents Become Read

## Problem

The TUI tracks completed agents as session-local unread rows in `_unread_completed_agent_ids`. Agent completion
notifications are persisted separately in the notification store. Existing agent dismissal cleanup already dismisses
matching agent notifications through `dismiss_notifications_matching_agents`, but reading an agent only clears the TUI
unread marker and leaves the notification panel entry behind.

The expected behavior is: when a completed agent transitions from unread to read in the TUI, dismiss the corresponding
unread agent completion notification from the notification panel.

## Current Flow

- Completion notifications are created by `send_completion_notification()` in
  `src/sase/axe/run_agent_runner_finalize.py`.
- Successful completions use action `JumpToAgent` with `action_data["cl_name"]` and `action_data["raw_suffix"]`.
- The notification store already has `dismiss_notifications_matching_agents()` in `src/sase/notifications/store.py`,
  backed by Rust `dismiss_matching_agents`, which matches agent-linked notifications.
- TUI unread state is maintained in:
  - `src/sase/ace/tui/actions/agents/_loading_finalize.py`
  - `src/sase/ace/tui/actions/agents/_core.py`
  - `src/sase/ace/tui/actions/event_handlers.py`
- Read transitions happen through several paths:
  - agent row selection/mouse click via `_acknowledge_agent_unread()`
  - keyboard navigation to unread done agents via `_jump_to_next_unread_done_agent()`
  - selecting the current completed agent during the finalize pass via `_sync_unread_completed_agents()`
  - manual unread toggle from unread to read via `_toggle_agent_unread()`

## Design

Add a small TUI-side helper that acknowledges an agent's unread marker and, only when that operation actually changes
the agent from unread to read, dismisses matching agent notifications.

The helper should:

- Accept an `Agent`.
- Check `_manual_unread_agent_ids`; manually guarded unread rows should not be dismissed until the row is genuinely
  acknowledged.
- Remove the identity from `_unread_completed_agent_ids`.
- Call `dismiss_notifications_matching_agents([{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}])` when the
  identity was present and removed.
- Refresh the notification indicator when the dismiss call changes anything.
- Preserve existing row patch/full-refresh behavior for the agent list.

This should live near `_acknowledge_agent_unread()` in `src/sase/ace/tui/actions/agents/_core.py`, because that is
already the central behavior for “read this agent row now.” To cover finalize-driven auto-read of the currently selected
row, either route `_sync_unread_completed_agents()` through an app method when available or have it call a narrower
notification-dismiss helper for identities it removes. Prefer using an app method when available so notification
dismissal stays attached to the TUI mixin rather than leaking persistence behavior into the free-function finalizer.

## Scope

Implement for agent completion notifications that match the existing dismissal contract:

- `JumpToAgent` completion rows with `cl_name` and `raw_suffix`.
- Existing `PlanApproval` / `UserQuestion` matching remains available to the store helper, but read-acknowledge paths
  should only call it for completed agents that are in the TUI unread set.

Do not change notification modal read-all semantics. This request is about the corresponding agent becoming read, not
arbitrary notification read actions.

Do not change agent dismissal cleanup, except possibly to reuse a shared helper if the existing code shape makes that
cleaner.

## Edge Cases

- Manual unread rows: toggling a row to unread should not dismiss anything. Toggling it back to read should dismiss
  matching notifications.
- Currently selected row during refresh: `_sync_unread_completed_agents()` can clear unread without going through
  row-selection handlers; this must dismiss the corresponding notification.
- Stale identities: pruning unread identities for agents no longer visible should not dismiss notifications, because
  there may be no reliable selected/read event.
- Hidden/silent notifications: `dismiss_notifications_matching_agents()` operates on unread matching notifications; the
  notification badge refresh should reflect whatever the store changed.
- Workflow children: use the agent identity and raw suffix already associated with the row being acknowledged; avoid
  broad cl-name-only dismissal unless `raw_suffix` is unavailable, matching existing store behavior.

## Tests

Add focused unit tests around `tests/ace/tui/test_agent_unread_indicator.py`:

- `_acknowledge_agent_unread()` dismisses matching notifications when it removes unread state.
- `_acknowledge_agent_unread()` does not dismiss while the agent is manually guarded.
- `_toggle_agent_unread()` dismisses when toggling a manually unread row back to read, but not when marking it unread.
- `_jump_to_next_unread_done_agent()` dismisses via the centralized acknowledge path.
- `_sync_unread_completed_agents()` dismisses notifications when it auto-clears the selected unread agent on the Agents
  tab.

Use mocks for `dismiss_notifications_matching_agents` and notification count refresh, so the tests stay fast and do not
depend on the real notification store.

## Verification

Run:

```bash
just install
pytest tests/ace/tui/test_agent_unread_indicator.py
just check
```

If `just check` is too slow or fails for unrelated environmental reasons, report that clearly with the narrower passing
test result.

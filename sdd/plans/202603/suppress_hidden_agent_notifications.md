---
create_time: 2026-03-30 12:05:00
status: done
prompt: sdd/prompts/202603/suppress_hidden_agent_notifications.md
---

# Plan: Suppress Notifications from Hidden Agents

## Problem

The `sase ace` notification panel is flooded with notifications from internal/automated agents — `[summarize-hook]`,
`[fix-hook]`, `[mentor-*]` — causing excessive noise in the TUI (bell, toast, unread count) and Telegram. These are
background housekeeping agents that the user didn't launch directly and whose results are already reflected in
ChangeSpec suffixes.

## Design

Add a `silent` flag to the `Notification` model. Silent notifications are stored in the JSONL file (preserving the audit
trail for debugging) but are excluded from the unread count, bell/toast, and Telegram delivery. The notification modal
can still show them if needed in the future, but by default they're invisible.

### Why `silent` field vs. just skipping the notification?

- **Audit trail**: `done.json` records exit codes, but having the notification JSONL as a unified log of all agent
  completions (with timestamps, files, errors) is valuable for debugging.
- **Extensibility**: Any future runner can opt into `silent=True` without rearchitecting.
- **Reversibility**: If we later want to surface some of these (e.g., failures only), we just adjust the filter rather
  than re-adding notification calls.

## Changes

### Phase 1: Core — Add `silent` field

**`src/sase/notifications/models.py`** — Add `silent: bool = False` to `Notification` dataclass.

**`src/sase/notifications/senders.py`** — Add `silent: bool = False` parameter to `notify_workflow_complete()`, thread
it through to `Notification(silent=silent, ...)`.

### Phase 2: Runners — Mark hidden agent notifications as silent

**`src/sase/axe/summarize_hook_runner.py`** — Pass `silent=True` to `notify_workflow_complete()`.

**`src/sase/axe/fix_hook_runner.py`** — Pass `silent=True` to `notify_workflow_complete()`.

**`src/sase/axe/mentor_runner.py`** — Pass `silent=True` to `notify_workflow_complete()`.

No changes to `run_agent_runner.py`, `run_workflow_runner.py`, or `crs_runner.py` — those are user-facing
agents/workflows whose notifications should remain visible.

### Phase 3: TUI — Exclude silent notifications from unread tracking

**`src/sase/ace/tui/actions/agents/_notifications.py`** — In `_poll_agent_completions()` and
`_refresh_notification_count()`, filter out `n.silent` from the unread list so they don't increment the badge or trigger
bell/toast.

**`src/sase/ace/tui/actions/agents/_notifications.py`** — In `_show_notification_modal()`, filter out silent
notifications from the list passed to `NotificationModal`.

### Phase 4: Telegram — Exclude silent notifications from outbound

**`../sase-telegram/src/sase_telegram/outbound.py`** — In `get_unsent_notifications()`, filter out `n.silent` so they
never get forwarded to Telegram.

### Phase 5: Tests

Add tests for:

- `Notification` model serialization with `silent=True`
- `notify_workflow_complete(silent=True)` creates a silent notification
- `load_notifications()` returns silent notifications (they're stored, just filtered at display)
- TUI unread count excludes silent notifications
- Telegram `get_unsent_notifications()` excludes silent notifications

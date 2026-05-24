---
create_time: 2026-05-24 13:41:53
status: done
---
# Plan: Sync Plan Notification Mutes to Agent Tags

## Goal

When a user mutes or snoozes a `PlanApproval` notification in the ACE TUI, automatically give the matching agent the
`mute` agent tag, but only when that agent is currently untagged. When that notification becomes unmuted, either by
manual unmute or by snooze expiry, remove the `mute` tag from the same agent when it is still the active tag.

## Current Shape

- `NotificationModal.action_toggle_mute()` and `action_snooze()` are the direct user-driven mutation points for
  notification mute state.
- Snooze expiry is already handled during `AgentNotificationPollingMixin._poll_agent_completions()` through
  `read_notification_snapshot(..., expire_due_snoozes=True)`, which returns `expired_ids`.
- Agent tags are persisted in `sase.ace.agent_tags` as one tag per agent identity and are loaded into `Agent.tag` during
  agent loading.
- Notification-to-agent matching already exists in `agent_matches_notification_identity()` and handles both phase and
  root timestamps, which matters for plan-chain parent rows.

## Design

1. Add a small `mute` tag constant and conditional tag helpers in `sase.ace.agent_tags`.
   - Add `MUTE_AGENT_TAG = "mute"`.
   - Add a helper that sets a tag only when the identity has no stored tag.
   - Add a helper that clears a tag only when the stored value equals the expected tag.
   - Use the existing atomic save path and avoid rewriting the file for no-op cases.

2. Add an app-level sync method on the notification mixin side.
   - Only handle `notification.action == "PlanApproval"`.
   - Find the matching loaded agent using existing notification identity matching, preferring currently loaded agent
     rows so workflow parent/root timestamp behavior remains consistent with status overrides.
   - On mute/snooze:
     - If the agent already has an in-memory tag, do nothing.
     - Otherwise persist `mute` only if the store is still untagged, then update the in-memory `Agent.tag`.
   - On unmute/expiry:
     - Remove the persisted tag only if it is currently `mute`.
     - Clear the in-memory tag when it is `mute`.
   - If a tag change affects loaded rows, invalidate agent panel caches and refresh the Agents display from memory,
     without triggering a disk reload.

3. Wire manual notification actions to the app-level sync method.
   - `NotificationModal` will call a guarded hook after `mark_muted()` and after `mark_snoozed()`.
   - The guarded hook is a no-op outside the ACE app, so modal unit tests and other uses stay isolated.

4. Wire snooze expiry to the same sync path.
   - During `_poll_agent_completions()`, if `expired_ids` is non-empty, scan only those expired notifications from the
     snapshot.
   - For expired `PlanApproval` notifications, call the sync method with `muted=False`.
   - This adds no work to ordinary polls where no snooze expires.

5. Add focused tests.
   - Modal action tests verify mute, unmute, and snooze call the guarded sync hook for plan notifications.
   - Agent-tag tests cover conditional set and conditional clear helper behavior.
   - Notification mixin tests cover setting `mute` only on untagged agents, preserving existing tags, clearing `mute` on
     unmute, and using root timestamp matching.
   - Polling tests cover expired snoozed plan notifications invoking the unmute sync path.

## Performance Notes

- No new logic is added to list rendering, j/k navigation, or normal refresh paths.
- Persistent tag store reads/writes happen only on explicit mute/snooze/unmute actions or when the existing notification
  poll reports expired snoozes.
- Snooze expiry uses the already-read notification snapshot and `expired_ids`, avoiding an extra notification-store
  read.
- Agent UI updates are in-memory cache invalidations and display refreshes only when an actual tag changes.

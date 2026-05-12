---
create_time: 2026-05-11 22:22:56
status: wip
prompt: sdd/prompts/202605/sase_30_completion_unread_contract.md
---
# Remaining Work Plan: sase-30 Completion Notification Unread Contract

## Findings

- `sase-30` is open and all four child beads are still in progress.
- The epic plan file is still marked `status: wip`.
- No git commits with `sase-30` or child bead IDs were found in the local history.
- The bulk Agents-tab completion dismissal machinery still exists in source and tests.
- Child bead details do not contain notes, so there are no extra note-specific requirements beyond the epic plan.

## Implementation Plan

1. Remove bulk Agents-tab acknowledgement machinery.
   - Delete the TUI completion-dismiss latch and in-flight state.
   - Remove Agents-tab entry/activity triggers that bulk-dismiss completion notifications.
   - Remove the public notification-store wrapper for dismissing every agent completion notification.

2. Restore per-agent row acknowledgement.
   - Make row acknowledgement dismiss only the selected agent's matching completion notification.
   - Refresh notification counts when that targeted dismissal changes the store.
   - Preserve manual unread behavior as a local guard until the row is reselected after departure.

3. Project unread rows from active completion notifications.
   - Add a helper that maps active, not-dismissed agent completion notifications to visible terminal agent identities.
   - Reconcile `_unread_completed_agent_ids` from that helper during notification polling and list finalization.
   - Stop marking terminal rows unread solely from local status transitions.

4. Replace regressions and preserve visuals.
   - Rewrite bulk-dismiss tests into one-to-one completion notification tests.
   - Update unread selection, navigation, finalizer, and notification-store tests.
   - Run focused pytest suites, then `just check`.

5. Close out metadata.
   - Update `sdd/epics/202605/agent_completion_notification_unread_contract.md` frontmatter to `status: done`.
   - Close child beads, then close epic bead `sase-30`.
   - Run `just pyvision` after the epic is closed.

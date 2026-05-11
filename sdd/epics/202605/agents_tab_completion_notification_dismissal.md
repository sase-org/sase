---
create_time: 2026-05-11 14:27:35
status: done
prompt: sdd/prompts/202605/agents_tab_completion_notification_dismissal.md
bead_id: sase-2v
tier: epic
---
# Dismiss Agent Completion Notifications On Agents Tab Activity

## Goal

Change the TUI notification behavior so agent completion notifications are dismissed in bulk when the user is clearly
looking at, or interacting with, the Agents tab:

- When the user navigates to the Agents tab, dismiss all outstanding agent completion notifications immediately.
- When the TUI is already on the Agents tab and an agent completion notification arrives, dismiss all outstanding agent
  completion notifications on the next user activity, including simple row navigation such as `j` / `k`.
- Stop relying on the selected agent being marked unread, manually toggled read, or dismissed from the Agents tab as the
  primary trigger for completion-notification dismissal.

This plan intentionally keeps row unread state as a local UI affordance for highlighting and jump-to-unread behavior,
while treating notification dismissal as an Agents-tab visibility/activity acknowledgement.

## Current State

The current behavior is spread across three paths:

- `src/sase/ace/tui/actions/agents/_core.py`
  - `_clear_agent_unread_and_dismiss_notification()` clears one agent's unread marker and calls
    `sase.notifications.dismiss_notifications_matching_agents(...)`.
  - This means notification dismissal is coupled to a specific unread selected row.
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
  - `_sync_unread_completed_agents()` marks newly terminal rows unread after status transitions, and clears unread for
    the currently selected row when already on the Agents tab.
  - Because it calls `_clear_agent_unread_and_dismiss_notification()`, it can dismiss a single selected agent
    notification.
- `src/sase/ace/tui/actions/agents/_dismissing.py` and `_killing_utils.py`
  - Agent dismiss/kill flows call `dismiss_notifications_for_agents(...)`, which also routes through
    `dismiss_notifications_matching_agents(...)`.

The notification-store predicate lives in `../sase-core/crates/sase_core/src/notifications/store.rs` as
`DismissMatchingAgents`. It currently matches `JumpToAgent`, `PlanApproval`, and `UserQuestion` action shapes. Agent
failure completion notifications can be `ViewErrorReport` with `sender="user-agent"` and `cl_name` / `raw_suffix` in
`action_data`, so the matching surface should be made explicit as part of this work.

Tab and activity hooks are already available:

- `src/sase/ace/tui/app.py`
  - `watch_current_tab()` is the correct place to trigger dismissal on entry to `new_tab == "agents"`.
- `src/sase/ace/tui/actions/event_handlers.py`
  - `_record_user_activity()` is called for ordinary key events and priority-binding tab actions.
  - `on_key()` calls `_record_user_activity()` before dispatching `j` / `k`, so it can handle the "already on Agents
    tab, next activity" case.
- `src/sase/ace/tui/actions/agents/_notifications.py`
  - `_poll_agent_completions()` reads the notification snapshot, computes new unread notification ids, rings the bell,
    emits toasts, updates the indicator, and applies status overrides.

## Phase 1: Notification Store Primitive

Owner: backend/store agent.

Add a store-level primitive for bulk dismissal of agent completion notifications.

Implementation scope:

- Extend `../sase-core/crates/sase_core/src/notifications/wire.rs` with a new update kind, for example
  `DismissAgentCompletions`.
- Implement the predicate in `../sase-core/crates/sase_core/src/notifications/store.rs`.
- Match only agent completion notification shapes:
  - `sender == "user-agent"` and `action == "JumpToAgent"`.
  - `sender == "user-agent"` and `action == "ViewErrorReport"`.
  - Require agent identity data in `action_data`, preferably at least `cl_name`, and preserve `raw_suffix` matching
    behavior where relevant.
- Do not dismiss `PlanApproval`, `UserQuestion`, `JumpToMentorReview`, CRS notifications, axe error reports, or
  unrelated `ViewErrorReport` rows.
- Consider also extending the existing `DismissMatchingAgents` predicate to include
  `sender == "user-agent" && action == "ViewErrorReport"` so current selected-agent and kill/dismiss flows continue to
  behave correctly for failed completion reports.
- Add a Python wrapper in `src/sase/notifications/store.py`, exported via `src/sase/notifications/__init__.py`, such as
  `dismiss_agent_completion_notifications() -> int`.
- Keep the Rust-backed atomic read-modify-write pattern. Avoid implementing this as a Python loop over
  `mark_dismissed()` calls.

Tests:

- Add/extend Rust parity tests in `../sase-core/crates/sase_core/tests/notification_store_parity.rs`.
- Add Python store tests under `tests/notification_store/test_storage.py`.
- Cover success completions, failure report completions, already dismissed rows, and non-agent-completion notifications
  that must remain untouched.

Deliverable:

- A tested notification-store API that can dismiss every outstanding agent completion notification in one call.

## Phase 2: TUI Trigger Wiring

Owner: TUI lifecycle/activity agent.

Wire the new store primitive into the Agents-tab lifecycle without changing unread-row semantics yet.

Implementation scope:

- Add a small TUI helper, likely on `AgentNotificationMixin`, such as
  `_dismiss_agent_completion_notifications_for_agents_tab()`.
- The helper should:
  - Call `dismiss_agent_completion_notifications()` off the UI thread when possible.
  - Coalesce concurrent calls with an in-flight flag.
  - Refresh the notification indicator only when the store reports a nonzero changed count.
  - Avoid toasts for this dismissal; it is an acknowledgement side effect, not a user-facing command result.
- Trigger the helper from `AceApp.watch_current_tab()` when `new_tab == "agents"` after the tab state has switched.
- Trigger the helper from `_record_user_activity()` when `self.current_tab == "agents"`.
  - This covers `j` / `k`, jump hints, folding, marking, copy mode keys, mouse/key activity routed through `on_key()`,
    and other ordinary activity.
  - Keep existing direct calls from tab actions intact because `action_next_tab()` / `action_prev_tab()` call
    `_record_user_activity()` before changing `current_tab`; the actual entry-to-Agents behavior should come from
    `watch_current_tab()`.
- Use lightweight gating so repeated `j` / `k` does not launch a storm of redundant store writes. A simple in-flight
  flag plus a "needs acknowledgement" latch is enough:
  - Set the latch on startup/first Agents-tab entry and whenever `_poll_agent_completions()` observes an unread active
    agent completion notification.
  - Clear it after the bulk-dismiss call completes, regardless of changed count.
  - Set it again when future polling observes completion notifications.
  - On Agents-tab entry, call immediately even if the latch is false, because there may be pre-existing rows from before
    this TUI session.

Tests:

- Add focused unit tests with small fake apps rather than full pilot tests first.
- Cover tab entry from CLs to Agents.
- Cover tab entry from AXE to Agents.
- Cover already-on-Agents activity after a completion notification is observed by polling.
- Cover repeated `j` / `k` coalescing.
- Cover non-Agents activity not dismissing completion notifications.

Deliverable:

- Agents-tab entry and Agents-tab activity dismiss all completion notifications through the new store API.

## Phase 3: Decouple Row Unread From Notification Dismissal

Owner: unread-state cleanup agent.

After Phase 2 is in place, simplify the old per-row acknowledgement behavior so unread rows are no longer the source of
truth for notification dismissal.

Implementation scope:

- Revisit `_clear_agent_unread_and_dismiss_notification()` in `src/sase/ace/tui/actions/agents/_core.py`.
- Either rename it to reflect unread-only behavior or split it into two helpers:
  - one helper for clearing local unread state,
  - one helper for notification acknowledgement if still needed by kill/dismiss flows.
- Preserve manual unread behavior:
  - A manually unread row should stay highlighted until the existing departure/return flow clears it.
  - Manual unread should not keep a completion notification alive once the user has entered or interacted with the
    Agents tab.
- Preserve `_jump_to_next_unread_done_agent()` behavior for local unread rows.
- Keep agent kill/dismiss notification cleanup for agent-scoped interactive notifications, especially `PlanApproval` and
  `UserQuestion`; this is separate from bulk completion dismissal.
- Update tests that currently assert per-selected-row notification dismissal from unread acknowledgement.

Tests:

- Update `tests/ace/tui/test_agent_unread_selection.py`.
- Update `tests/ace/tui/test_agent_unread_navigation.py`.
- Update `tests/ace/tui/test_agent_unread_finalizer.py`.
- Add regression coverage that manual unread does not block global completion notification dismissal.

Deliverable:

- Local unread state remains useful, but completion notifications are no longer dependent on selected-row unread
  acknowledgement.

## Phase 4: End-To-End Behavior And Regression Coverage

Owner: integration/verification agent.

Close gaps across polling, indicators, tab switching, and failure-completion notification shapes.

Implementation scope:

- Add tests around `_poll_agent_completions()` so observing an agent completion while already on the Agents tab arms the
  next-activity dismissal but does not silently dismiss before activity.
- Confirm the notification indicator updates after bulk dismissal.
- Confirm completion toasts still appear when appropriate before dismissal; the new behavior should not suppress the
  initial notification if the user is not on Agents.
- Confirm muted/snoozed behavior:
  - Muted completion rows should be dismissed when the bulk action runs if they are agent completion notifications.
  - Read-but-not-dismissed completion rows should also be dismissed, because the requirement says all completion
    notifications, not only unread ones.
- Confirm unrelated priority notifications remain visible after Agents-tab entry/activity.
- Include failure completion reports (`ViewErrorReport`, `sender="user-agent"`) in integration tests.

Suggested verification commands:

- `just install` first in this workspace if it has not already been run.
- Targeted tests:
  - `pytest tests/notification_store/test_storage.py`
  - `pytest tests/test_notification_toast_polling.py`
  - `pytest tests/ace/tui/test_agent_unread_selection.py tests/ace/tui/test_agent_unread_navigation.py tests/ace/tui/test_agent_unread_finalizer.py`
  - any new TUI activity/tab tests added for this work
- Rust core tests for the notification-store parity changes in `../sase-core`.
- Final repo check from this repo: `just check`.

Deliverable:

- A verified cross-layer behavior change with store, TUI, and unread-state tests covering the intended semantics.

## Risks And Design Notes

- The phrase "agent completion notifications" should be implemented as a concrete predicate, not as every notification
  that has an agent-looking field. Completion notifications are currently created by `send_completion_notification()` as
  `sender="user-agent"` with `JumpToAgent` for normal completions and `ViewErrorReport` for failed completions with an
  error report.
- Do not dismiss `PlanApproval` or `UserQuestion` on Agents-tab entry. Those require user action and currently drive
  agent status overrides.
- Do not make every notification read. Dismiss completion notifications only; leave read/unread state for other
  notification categories untouched.
- Avoid per-key synchronous disk I/O in `j` / `k` navigation. The activity trigger should schedule/coalesce the store
  update.
- Keep the Rust core boundary in mind. The notification-store predicate and atomic update belong in `../sase-core`; the
  TUI-specific timing policy belongs in this repo.
- The existing `DismissMatchingAgents` API is still useful for agent kill/dismiss and interactive notification cleanup.
  The new bulk completion-dismiss API should not replace that broader agent-scoped behavior.

## Suggested Agent Assignment Order

1. Phase 1 agent lands the store primitive and Python wrapper.
2. Phase 2 agent wires Agents-tab entry/activity to the primitive.
3. Phase 3 agent decouples unread-row acknowledgement from notification dismissal and updates affected unread tests.
4. Phase 4 agent adds integration/regression coverage and performs full verification.

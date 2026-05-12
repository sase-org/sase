---
create_time: 2026-05-11 21:19:15
status: done
bead_id: sase-30
tier: epic
prompt: sdd/prompts/202605/agent_completion_notification_unread_contract.md
---
# Plan: Restore One-to-One Agent Completion Notifications and Agents-Tab Unread State

## Goal

Undo most of the recent Agents-tab completion-notification acknowledgement machinery and restore the simpler contract:

- Agent completion notifications are still written to the normal notification store so the TUI sees them through the
  existing notification poller, indicator, modal, bell, and toast paths.
- A completed agent row is unread if and only if its corresponding completion notification is not dismissed.
- Reading/acknowledging the agent row dismisses the corresponding completion notification.
- Dismissing the corresponding notification makes the agent row read.
- Keep the newer visual highlighting for unread agent counts in Agents-tab panel titles and info-panel labels.

This should remove the bulk Agents-tab activity dismissal behavior added in `sase-2v` (`600cbe08`, `b9f525a0`,
`be49b75b`, `b95707f3`) except where a narrow helper remains useful for matching an agent row to its own notification.

## Current Findings

Recent related commits:

- `600cbe08 feat: add dismiss_agent_completion_notifications wrapper (sase-2v.1)` added a store-level bulk dismissal
  helper for all user-agent completion notifications.
- `b9f525a0 feat: wire Agents-tab activity to bulk-dismiss completion notifications (sase-2v.2)` added
  `_agent_completion_ack_latch`, `_agent_completion_dismiss_inflight`, `_request_agent_completion_dismiss`, and
  forced/background dismissal on Agents-tab entry and activity.
- `be49b75b ref: decouple per-row unread acknowledgement from notification dismissal (sase-2v.3)` deliberately removed
  per-row notification dismissal from unread acknowledgement.
- `b95707f3 test: add end-to-end regression coverage for Agents-tab completion dismissal (sase-2v.4)` added tests for
  the bulk-dismiss behavior.

The unread-count highlighting to keep is separate and comes from:

- `ed8027de feat: highlight Agents-tab unread count with yellow background`
- `953f58d8 test: add PNG snapshot covering Agents-tab unread-count highlight`
- `54fc4e69 feat: extend Agents-tab unread highlight across the label word`
- `c3a4f0f0 feat: extend unread chip across the short-hand U token in panel titles`

Key current files:

- `src/sase/axe/run_agent_runner_finalize.py` already calls
  `notify_workflow_complete(..., sender="user-agent", action="JumpToAgent"/"ViewErrorReport", action_data={"cl_name", "raw_suffix", ...}, silent=agent_hidden)`.
  This is the notification path we should preserve.
- `src/sase/ace/tui/actions/agents/_notifications.py` contains the new bulk completion dismissal latch/helper and the
  normal notification polling path.
- `src/sase/ace/tui/actions/agents/_core.py` contains row unread acknowledgement and currently no longer dismisses
  per-agent notifications.
- `src/sase/ace/tui/actions/agents/_loading_finalize.py` currently derives local unread rows from observed status
  transitions, not from notification dismissal state.
- `src/sase/notifications/store.py` has both targeted `dismiss_notifications_matching_agents()` and bulk
  `dismiss_agent_completion_notifications()`.

## Desired Architecture

The TUI should have one source of truth for completion unread state: the notification store's active, not-dismissed
completion notification rows.

Define an agent-completion notification as:

- `sender == "user-agent"`
- `action in {"JumpToAgent", "ViewErrorReport"}`
- `action_data["cl_name"]` present
- `action_data["raw_suffix"]` present when available, matching the visible agent's `raw_suffix`

Maintain local `_unread_completed_agent_ids` only as a projection/cache for rendering and navigation. It should be
recomputed or reconciled from active completion notifications during notification polling / agent-list finalization, not
independently invented from terminal status transitions.

Manual `U` unread toggles are a separate local affordance. They can stay session-local, but they should not violate the
one-to-one completion-notification contract for real completion notifications. If a row has a real completion
notification, clearing the row must dismiss that notification. If a row is manually marked unread without a
notification, that should be visually local only and must not create or block a completion notification.

## Phase 1: Remove Bulk Agents-Tab Acknowledgement Machinery

Owner: one agent instance.

Scope:

- Delete the `dismiss_agent_completion_notifications()` public wrapper unless Phase 2 finds a concrete reason to keep it
  for tests or CLI-only maintenance.
- Remove `_agent_completion_dismiss_inflight` and `_agent_completion_ack_latch` from TUI state initialization and type
  hints.
- Remove `_dismiss_agent_completion_notifications_for_agents_tab()` and `_request_agent_completion_dismiss()` from
  `AgentNotificationMixin`.
- Remove forced completion dismissal on Agents-tab entry in `app.py`.
- Remove user-activity-triggered completion dismissal in `event_handlers.py`.
- Delete or rewrite tests that assert global dismissal on tab entry/activity:
  - `tests/ace/tui/test_agents_tab_completion_dismiss.py`
  - `tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py`
  - the `TestDismissAgentCompletionNotifications` section in `tests/notification_store/test_storage.py`, if the store
    helper is removed.

Expected result:

- Opening or using the Agents tab no longer dismisses all completion notifications.
- Existing completion notifications remain visible in the TUI notification indicator/modal until their corresponding
  agent row is read or the notification is explicitly dismissed.

Suggested focused verification:

- `pytest tests/ace/tui/test_agents_tab_completion_dismiss.py tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py tests/notification_store/test_storage.py`

## Phase 2: Restore Per-Agent Row Acknowledgement Dismissal

Owner: one agent instance after Phase 1 lands.

Scope:

- Reintroduce a narrowly named row-level helper in `src/sase/ace/tui/actions/agents/_core.py`, likely
  `_clear_agent_unread_and_dismiss_notification(agent)`, using
  `dismiss_notifications_matching_agents([{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}])`.
- Ensure `_acknowledge_agent_unread()`, jump-to-next-unread, mouse selection, and finalize-time selected-row
  acknowledgement all route through that helper.
- Refresh the notification count when a matching notification was dismissed.
- Preserve manual-unread guard behavior only for manually marked local rows. Once the user leaves and returns to a
  manually unread completed row, clearing it should dismiss any matching completion notification if one exists.
- Update tests currently changed by `be49b75b` so they assert targeted dismissal again:
  - `tests/ace/tui/test_agent_unread_selection.py`
  - `tests/ace/tui/test_agent_unread_navigation.py`
  - `tests/ace/tui/test_agent_unread_finalizer.py`

Expected result:

- Reading a single completed agent row only dismisses that row's completion notification.
- Reading one row never dismisses unrelated agent completions, plan approvals, user questions, mentor reviews, or AXE
  error notifications.

Suggested focused verification:

- `pytest tests/ace/tui/test_agent_unread_selection.py tests/ace/tui/test_agent_unread_navigation.py tests/ace/tui/test_agent_unread_finalizer.py tests/notification_store/test_storage.py`

## Phase 3: Project Unread Rows From Active Completion Notifications

Owner: one agent instance after Phase 2 lands.

Scope:

- Add a small adapter, preferably in `src/sase/ace/tui/actions/agents/_notifications.py` or a tiny helper module, that
  turns active unread/not-dismissed completion notifications into agent identities.
- During notification polling, reconcile `_unread_completed_agent_ids` with current completion notifications for visible
  agents.
- During agent-list finalization, avoid marking a row unread solely because status transitioned to `DONE`/`FAILED`/plan
  terminal if no corresponding completion notification exists yet. The notification poll should supply the unread marker
  once the notification exists.
- Handle ordering races: if agent scan sees `DONE` before the notification file write is visible, the row may stay read
  for one refresh tick, then become unread once the notification arrives. That is acceptable and keeps the store as the
  source of truth.
- Hidden/silent agents: preserve current notification semantics. If a hidden agent notification is stored as
  `silent=True`, decide explicitly whether it should contribute to row unread. The one-to-one contract says dismissed
  status, not indicator visibility, should drive the row; so silent-but-not-dismissed completion notifications should
  still map to unread rows if the row is visible.
- If the notification is dismissed in the notification modal, the next poll/finalization should remove the row from
  `_unread_completed_agent_ids`.

Expected result:

- Agent-row unread state and notification dismissed state converge in both directions.
- The old status-transition heuristic is no longer the independent authority.

Suggested focused verification:

- New or rewritten tests covering:
  - active completion notification makes matching completed agent row unread
  - dismissed completion notification makes matching row read
  - notification modal dismissal clears row unread after refresh
  - unrelated notifications do not affect agent unread rows
  - `raw_suffix` disambiguates same-`cl_name` completions

## Phase 4: End-to-End Regression and Visual Preservation

Owner: one final agent instance after Phases 1-3 land.

Scope:

- Replace the deleted bulk-dismiss E2E coverage with an E2E contract test for one-to-one behavior:
  - two completed agents with two completion notifications start unread
  - selecting/reading one agent dismisses exactly one notification and clears exactly one row
  - dismissing the other notification through notification APIs clears the other row on refresh
  - entering/navigating the Agents tab alone does not bulk-dismiss anything
- Keep and rerun the unread-count highlight tests/snapshots:
  - `tests/ace/tui/widgets/test_agent_info_panel.py`
  - `tests/ace/tui/test_agent_panel_titles.py`
  - `tests/ace/tui/visual/test_ace_png_snapshots.py` cases for `agents_unread_highlight_120x40.png`
- Run the broader relevant suite, then `just check` after `just install` if dependencies are not already installed in
  this workspace.

Expected result:

- The product behavior is simple and testable: notification dismissal and row unread are one-to-one.
- The newer unread-count highlighting remains unchanged.
- No background activity/tab-entry path silently clears notifications.

## Risks and Watchpoints

- Notification matching must use both `cl_name` and `raw_suffix` where possible. Matching only `cl_name` risks
  dismissing or clearing the wrong row for repeated agent runs.
- The notification store is core-backed. If removing `dismiss_agent_completion_notifications()` leaves unused Rust
  state-update variants, the implementing agent should inspect `../sase-core` and remove dead wire/API surface only if
  it is not used elsewhere.
- Existing PlanApproval/UserQuestion notification flows are intentionally different and should not be folded into
  completion row-read semantics.
- Manual `U` remains a local visual affordance; tests should distinguish local manual unread from real
  completion-notification unread.
- Do not modify memory files. SDD/bead metadata churn from the old commits does not need to be reverted for this product
  fix unless explicitly requested.

## Final Verification Checklist

- `just install`
- Focused pytest suites from each phase
- `just check`
- Confirm no remaining references to `_agent_completion_ack_latch`, `_agent_completion_dismiss_inflight`,
  `_request_agent_completion_dismiss`, or the bulk Agents-tab completion-dismiss worker.
- Confirm unread-count highlight tests and PNG snapshot remain valid.

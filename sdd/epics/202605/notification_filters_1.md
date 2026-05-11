---
create_time: 2026-05-11 10:20:32
status: done
prompt: sdd/prompts/202605/notification_filters_1.md
bead_id: sase-2t
tier: epic
---
# User-Configured Notification Filters

## Goal

Add notification suppression that is scoped by client and notification type, with a default that hides successful
user-agent completion notifications from the ACE TUI only. Telegram and other consumers must continue to receive those
completion rows from the shared notification store.

The important behavioral distinction is that suppression is a client projection concern, not a store mutation. A
suppressed notification should remain in `~/.sase/notifications/notifications.jsonl`, remain visible to non-filtered
clients such as Telegram, and remain inspectable through local commands unless those commands explicitly opt into a
client projection.

## Current Shape

- Agent completion notifications are created by `src/sase/axe/run_agent_runner_finalize.py`.
- Successful visible agents write `sender="user-agent"`, `action="JumpToAgent"`.
- Failed agents with an error report write `sender="user-agent"`, `action="ViewErrorReport"` and are currently treated
  as error notifications.
- Hidden/background agents are written with `silent=True`; that is global suppression and should remain separate from
  client filters.
- TUI notification reads happen in:
  - `src/sase/ace/tui/actions/lifecycle.py`
  - `src/sase/ace/tui/actions/agents/_notifications.py`
- The recently added read-time cleanup is in:
  - `src/sase/ace/tui/actions/agents/_core.py`
  - `src/sase/ace/tui/actions/agents/_loading_finalize.py` It clears an unread agent row and also calls
    `dismiss_notifications_matching_agents`. That dismissal coupling should be removed after TUI filtering is in place.

## Proposed Config Contract

Add a top-level notification config section:

```yaml
notifications:
  suppress:
    - client: tui
      types:
        - agent_completion
```

Rules:

- `client` is case-insensitive and normalized with `casefold()`. Known clients should include `tui`, `telegram`, and
  `mobile`, but unknown client names should not be rejected by the parser.
- `types` is a non-empty list of semantic notification type names. Start with semantic names rather than raw
  sender/action strings so users do not need to know storage internals.
- Default repo config should include only the TUI agent-completion suppression above.
- User `~/.config/sase/sase.yml` replaces the default list, consistent with existing config merge semantics. Overlay and
  local config lists concatenate.

Initial semantic type mapping:

| Type               | Match                                                      |
| ------------------ | ---------------------------------------------------------- |
| `agent_completion` | `sender == "user-agent"` and `action == "JumpToAgent"`     |
| `agent_failure`    | `sender == "user-agent"` and `action == "ViewErrorReport"` |
| `plan_approval`    | `action == "PlanApproval"`                                 |
| `user_question`    | `action == "UserQuestion"`                                 |
| `mentor_review`    | `action == "JumpToMentorReview"`                           |
| `hitl`             | `action == "HITL"`                                         |
| `sync_result`      | `action == "JumpToChangeSpec"` and `sender == "sync"`      |
| `axe_error_digest` | `sender == "axe"` and `action == "ViewErrorReport"`        |

Keep `agent_failure` out of the default suppression so failed agents still surface in the TUI error path.

## Phase 1: Shared Filter Model And Matcher

Owner: one agent instance.

Implement a small notification-filter module in the main repo, likely under `src/sase/notifications/filters.py`.

Responsibilities:

- Parse `load_merged_config()["notifications"]["suppress"]`.
- Normalize client names and type names.
- Expose a pure predicate such as `is_suppressed_for_client(notification, client)`.
- Expose a projection helper that can filter a notification list and recompute `NotificationCountsWire` using the same
  priority/error/rest/muted rules already used by TUI tests.
- Provide a client-aware snapshot helper, for example `read_notification_snapshot_for_client(client, ...)`, that wraps
  the existing store snapshot, preserves snooze expiration behavior, and recomputes counts after filtering.
- Keep invalid config non-fatal: skip malformed entries and log at debug/warning level.

Tests:

- Unit tests for semantic type classification.
- Unit tests for client matching and case normalization.
- Unit tests proving `agent_completion` suppression removes only `sender=user-agent/action=JumpToAgent`, not failed
  agent `ViewErrorReport` rows.
- Unit tests proving counts are recomputed after filtering.

Validation:

- Run focused notification filter tests.
- Run `just check` after `just install` if this phase changes source files.

## Phase 2: Wire The ACE TUI To The Client Projection

Owner: a second agent instance.

Change only ACE/TUI notification read paths to use the client-aware projection for `client="tui"`.

Target reads:

- Startup unread id/count loading in `src/sase/ace/tui/actions/lifecycle.py`.
- Poll/toast/bell/count refresh paths in `src/sase/ace/tui/actions/agents/_notifications.py`.
- Notification modal source rows in `_show_notification_modal`.

Expected behavior:

- Suppressed TUI rows do not contribute to startup counts, top-bar counts, toast batches, bell decisions, or modal rows.
- Suppressed rows remain persisted and are still returned by the raw store API.
- Existing PlanApproval/UserQuestion status override behavior remains unchanged because those types are not suppressed
  by default.
- Snooze expiry should continue to work. The underlying snapshot can expire snoozes before the projection filters rows.

Tests:

- Extend `tests/ace/tui/test_startup_stopwatch_live_update.py` for filtered startup counts.
- Extend `tests/test_notification_toasts.py` so a default-suppressed `agent_completion` does not toast or increment TUI
  counts, while `agent_failure`, `PlanApproval`, and `UserQuestion` still do.
- Add/adjust modal tests so suppressed completion rows are absent from the TUI modal.

Validation:

- Run focused TUI notification tests.
- Run `just check` after `just install`.

## Phase 3: Default Config, Schema, And Docs

Owner: a third agent instance.

Add the default and user-facing contract.

Files:

- `src/sase/default_config.yml`: add the default TUI suppression.
- `config/sase.schema.json`: allow the new top-level `notifications.suppress` structure.
- `docs/configuration.md`: document the config section, merge behavior, client names, and type names.
- `docs/notifications.md`: replace the current statement that TUI selection dismisses matching completion notifications
  with the new client-filter behavior.

Tests:

- Config/schema tests that default config contains the TUI suppression shape.
- If this repo has schema validation coverage, add examples for valid and invalid `notifications.suppress`.
- Confirm docs mention that suppression is client-local and does not mutate the JSONL store.

Validation:

- Run focused config/schema tests.
- Run `just check` after `just install`.

## Phase 4: Remove Agent-Read Notification Dismiss Coupling

Owner: a fourth agent instance.

Remove the recent logic that dismisses agent-completion notifications when an unread completed agent row becomes read.
Keep unread row behavior itself.

Changes:

- Rename or replace `_clear_agent_unread_and_dismiss_notification` with a read-only row state helper such as
  `_clear_agent_unread`.
- Update callers in `_core.py`, `_loading_finalize.py`, and navigation paths.
- Delete the import/call to `dismiss_notifications_matching_agents` from agent-read acknowledgement.
- Keep `dismiss_notifications_for_agents` for explicit agent kill/dismiss operations. Those are different user actions
  and should still clear matching notifications.
- Update tests that currently expect read acknowledgement to call notification dismissal:
  - `tests/ace/tui/test_agent_unread_selection.py`
  - `tests/ace/tui/test_agent_unread_finalizer.py`
  - `tests/ace/tui/test_agent_unread_navigation.py`

Expected behavior:

- Selecting or jumping to an unread completed agent clears the row marker only.
- No notification store mutation happens from the selection/read path.
- Manual unread guard behavior remains unchanged.
- Explicit kill/dismiss flows still dismiss matching notifications.

Validation:

- Run focused unread-agent tests and notification dismissal tests.
- Run `just check` after `just install`.

## Phase 5: End-To-End Regression Pass

Owner: a fifth agent instance.

Perform a final integration review after the previous phases land.

Checklist:

- Raw store still contains successful agent-completion rows.
- TUI default projection hides successful agent-completion rows from unread counts, toasts, bell, and modal.
- Telegram/mobile/raw consumers are not affected unless they explicitly ask for their own client projection.
- Failed-agent error notifications remain visible in TUI.
- Existing silent notification behavior is unchanged.
- Existing explicit kill/dismiss notification cleanup still works.
- Documentation and schema match the implemented YAML exactly.

Validation:

- Run `just install` if needed.
- Run `just check`.
- Run any focused tests that failed during prior phases.

## Risks And Notes

- Avoid implementing suppression by marking rows `read`, `dismissed`, `silent`, or `muted`; all of those mutate shared
  semantics and would affect Telegram or future clients.
- Rust store counts are unfiltered. Any client projection must recompute counts after filtering instead of reusing raw
  counts.
- The default should suppress only successful agent completions. Failed agents should remain visible unless a user
  explicitly configures `agent_failure` for a client.
- If a future phase wants mobile or Telegram to use the same filters, it should call the shared projection helper with
  `client="mobile"` or `client="telegram"` rather than duplicating matcher logic.

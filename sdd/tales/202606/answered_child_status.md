---
create_time: 2026-06-15 18:04:06
status: done
prompt: sdd/prompts/202606/answered_child_status.md
---
# Fix ANSWERED Status For Question-Asking Child Rows

## Problem

Answering a `UserQuestion` notification can flip the visible root/aggregate agent row from `QUESTION` to the new
transient `ANSWERED` status, while the child row that actually asked the question remains `QUESTION`.

The current notification matching deliberately treats both `agent_timestamp` and `agent_root_timestamp` as valid
matches. That is useful for navigation because the notification can select either the concrete child row or the root
row. It is not sufficient for status mutation, because the mutation paths stop at the first matching row and write
`_agent_status_overrides` for only that row's identity. Since `Agent.identity` includes `raw_suffix`, the root and child
rows get separate override keys, so the child can keep its stale `QUESTION` override.

## Proposed Approach

1. Add a small helper in the notification question handling path that resolves all currently loaded rows associated with
   a `UserQuestion` notification, not only the first match.

2. For answered questions, mark every relevant matched row as `ANSWERED`:
   - the concrete asking row whose `raw_suffix` matches `agent_timestamp`
   - the root/aggregate row whose `raw_suffix` matches `agent_root_timestamp`
   - any currently loaded row already matching the notification identity

3. Keep this as an in-memory optimistic TUI status override. The existing loader/meta enrichment still remains the
   durable source once `pending_question.json` and `question_response.json` are seen on disk. The override should
   continue to clear through the existing `should_clear_loaded_agent_status_override()` logic when the runner progresses
   or reaches a terminal state.

4. Refresh the affected rows through the existing notification refresh/cache path. Avoid adding a new disk refresh path
   or synchronous event-loop work.

5. Preserve the existing marker fallback behavior: when a dismissed-notification question is opened from the selected
   child row's `pending_question.json`, continue to mark that supplied row as `ANSWERED`. If the supplied row is part of
   a root/child pair that is already loaded, also update the related root row when it can be found from timestamps.

## Tests

1. Add a regression test in the notification/modal tests that sets up:
   - a root workflow row with `raw_suffix == agent_root_timestamp`
   - a child/follow-up row with `raw_suffix == agent_timestamp`
   - an unread `UserQuestion` notification containing both timestamps
   - existing `QUESTION` overrides for both identities

   After the modal writes `question_response.json`, assert both identities have `ANSWERED` overrides and both
   pre-question entries are cleared.

2. Add or extend a notification status override test for unread `UserQuestion` routing so root and child rows can both
   receive the `QUESTION` override when a single notification references both timestamps. This keeps the ask and answer
   paths symmetric.

3. Run focused tests first:

   ```bash
   pytest tests/test_plan_rejection_response.py tests/ace/tui/test_agent_notification_status_overrides.py tests/test_enrich_agent_pending_question.py tests/test_agent_loader_status_override_questions.py
   ```

4. Because this repo requires it after file changes, run:

   ```bash
   just install
   just check
   ```

## Risks And Constraints

- Do not broaden matching so unrelated rows with the same ChangeSpec name are updated. Timestamp matching should remain
  the primary signal.
- Do not add synchronous disk reads to the TUI event loop. The status update is an in-memory override and row refresh
  only.
- Do not change the durable status semantics for completed agents: completed answered questions should still reconcile
  to the existing terminal plan/done statuses once the loader observes the runner progression.

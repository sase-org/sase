---
create_time: 2026-05-21 20:52:36
status: done
prompt: sdd/prompts/202605/agent_selected_unread.md
---
# Plan: Selected Agent Rows Become Unread Immediately

## Context

The Agents tab projects active agent-completion notifications onto row-level unread checkmarks. Today the finalizer and
notification-polling paths both treat the currently selected Agents-tab row as an exclusion: the selected row is cleared
or prevented from being added to `_unread_completed_agent_ids`. That keeps a just-completed selected row from showing
its checkmark until focus moves away.

The desired product behavior is different:

- If the selected row becomes unread, the checkmark should appear immediately.
- The row should become read only when the user intentionally enters that row again, for example by leaving and
  returning with `j` then `k`, clicking/selecting it again, or reaching it with `,j`.
- Navigation to unread rows should still dismiss the matching completion notification and update counts/panel titles.
- Manual unread marks via `U` should keep their current guard semantics.

## Proposed Design

1. Separate "currently selected" from "read".
   - Stop using the selected row as a blanket `exclude_identity` during notification projection.
   - Stop clearing the selected row from `_unread_completed_agent_ids` during ordinary agent-list finalization.
   - Keep finalization responsible for pruning stale identities and reconciling against active notifications.

2. Preserve explicit read boundaries.
   - Keep `_acknowledge_agent_unread()` as the single-row read path for real selection/navigation events.
   - Existing event paths already call this when an agent row is selected:
     - `on_agent_list_selection_changed`
     - `_navigate_agents_panel`
     - `_jump_to_next_unread_done_agent`
   - This means `j` then `k` and `,j` naturally clear the row when the user re-enters it.

3. Avoid stale notification snapshots re-adding a row after explicit read.
   - When `_clear_agent_unread_and_dismiss_notification()` dismisses a matching notification, ensure the in-memory
     notification snapshot used for row projection is refreshed or filtered so a later reconcile does not resurrect the
     row from stale cache data.
   - Prefer the existing provider refresh path when available; keep tests with minimal fake apps working by maintaining
     local row-state changes even if a fake refresh does not update the cache.

4. Patch visible rows immediately on projection changes.
   - `_reconcile_unread_from_cached_notifications()` already diffs before/after and calls
     `_patch_unread_completed_agent_changes()`.
   - With selected-row exclusion removed, the selected row should be included in that diff and `_try_patch_agent_row()`
     should re-render it with `is_selected=True` and `is_unread=True`.
   - Full finalizer refreshes will continue passing `unread_agents` into `AgentList.update_list()`.

5. Update tests around selected-row semantics.
   - Change finalizer/projection tests that currently assert "selected row stays read" to assert it becomes unread when
     a matching notification exists.
   - Add or adjust a regression test that simulates a selected DONE row receiving a completion notification while on the
     Agents tab and verifies the row identity enters `_unread_completed_agent_ids`.
   - Keep navigation tests verifying `j`/`k` and `,j` acknowledge target rows.
   - Add a focused test for stale-cache behavior if the implementation touches snapshot refresh/filtering.

## Validation

1. Run the targeted unread/selection test set:
   - `pytest tests/ace/tui/test_agent_unread_finalizer.py tests/ace/tui/test_agent_unread_projection.py tests/ace/tui/test_agent_unread_selection.py tests/ace/tui/test_agent_unread_done_navigation.py tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py`

2. Because this repo requires it after source changes, run:
   - `just install`
   - `just check`

## Risks

- Removing selected-row exclusion can expose stale notification snapshots if dismissals do not refresh the cache. The
  implementation must explicitly prevent stale cache resurrection after a row is acknowledged.
- Existing tests encode the old "selection means read" behavior. Those should be updated only where they conflict with
  the new requested UX; unrelated one-to-one notification dismissal guarantees should stay intact.
- Group/banner focus must continue not to acknowledge agent unread state until an actual agent row is selected.

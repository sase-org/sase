---
create_time: 2026-05-12 13:24:58
status: done
prompt: sdd/prompts/202605/mark_all_unread_agents_read.md
---
# Plan: Agents `,J` Mark All Unread As Read

## Goal

Add a new `,J` leader-mode key on the `sase ace` Agents tab that marks every currently unread completed agent row as
read, and dismisses the corresponding agent completion notifications. The implementation must preserve the existing
row/notification contract and avoid adding per-agent disk I/O or expensive refresh work.

## Current System Shape

- Agent unread state is held in memory as `_unread_completed_agent_ids`.
- Manual unread guards are held in `_manual_unread_agent_ids`.
- Active completion notifications are projected onto unread rows from `user-agent` notifications with `JumpToAgent` or
  `ViewErrorReport`.
- Existing single-row acknowledgement goes through `_clear_agent_unread_and_dismiss_notification`, then patches a row or
  refreshes.
- Notification state updates already route through Rust-backed bulk operations under `sase.notifications.store`.
- The Rust core already has a completion-only bulk operation: `DismissAgentCompletionsMatchingAgents`, but the Python
  store layer does not expose a convenience wrapper for it yet.
- Keymaps are configured through `src/sase/default_config.yml`, `AppKeymaps`/mode keymaps, command catalog
  labels/scoping, leader-mode dispatch, footer/help display, and fallback bindings as applicable.

## Implementation Plan

1. Expose a Python notification-store helper for the existing Rust completion-only bulk operation.
   - Add `dismiss_agent_completion_notifications_matching_agents(agent_keys)` to `sase.notifications.store`.
   - Export it from `sase.notifications`.
   - Use the same key normalization path as `dismiss_notifications_matching_agents`.
   - Return the Rust `matched_count` or `changed_count` consistently with current bulk dismiss helpers.
   - This avoids broad dismissal of `PlanApproval` / `UserQuestion` rows when the requested action is specifically
     completion-notification dismissal.

2. Add an in-memory bulk unread acknowledgement helper on `AgentsMixinCore`.
   - Collect target agents from `self._agents` whose identity is in `_unread_completed_agent_ids` and whose status is
     terminal via `is_unread_completed_status`.
   - Treat the command as explicit acknowledgement, so clear both `_unread_completed_agent_ids` and
     `_manual_unread_agent_ids` for the targeted identities.
   - Build one list of `{cl_name, raw_suffix}` keys for the terminal targets.
   - Call the new completion-only store helper once.
   - Refresh the notification count only once when the store changed.
   - Update the display with a single refresh or bounded row patches. Prefer a single list refresh for correctness
     across panels/counts, because all panel unread counters and highlighted row styles can change together.
   - Return the count so leader-mode dispatch can show a useful message for no-op vs success.

3. Wire the `,J` key.
   - Add `mark_all_unread_done_agents_read: "J"` under `ace.keymaps.modes.leader_mode.keys` in
     `src/sase/default_config.yml`.
   - Add the key to `LeaderModeKeymaps` defaults.
   - Add leader-mode dispatch in `_handle_leader_key` gated to `current_tab == "agents"`.
   - Keep existing app-level `J` for panel focus unchanged; `,J` only applies after entering leader mode.
   - Add command catalog label/tab scoping so palette/help metadata stays complete.
   - Add footer/help text so the command is discoverable when unread completed agents exist.

4. Add tests focused on behavior and performance characteristics.
   - Unit test the new notification-store helper routes through one Rust state update with
     `kind == "dismiss_agent_completions_matching_agents"`.
   - Unit test it dismisses completion notifications without dismissing plan/question notifications.
   - Unit test the Agents bulk helper clears all unread/manual unread row state, calls the notification helper once with
     all keys, refreshes notification count once, and performs one display refresh.
   - Unit test no-op behavior when there are no unread terminal agents: no notification-store call and no display
     refresh.
   - Unit test leader-mode `J` dispatches only on Agents tab and does not disturb existing `J` panel focus behavior.

5. Validate.
   - Run the targeted test files first:
     - `pytest tests/notification_store/test_storage.py tests/notification_store/test_state_updates.py tests/ace/tui/test_agent_unread_navigation.py tests/ace/tui/test_show_agent_run_log_keymap.py`
   - Because this repo requires it after code changes, run `just install` if needed, then `just check`.

## Performance Notes

- The command will not loop over notifications or call notification-store mutations per agent.
- It will use the already-loaded agent list and unread identity set, making target collection O(number of currently
  loaded agent rows).
- Store mutation is one Rust-backed locked read/rewrite, using the existing notification-store bulk update path.
- UI work is one display refresh and one notification-count refresh at most.
- No new filesystem scans or agent reloads are needed.

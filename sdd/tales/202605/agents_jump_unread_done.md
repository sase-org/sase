---
create_time: 2026-05-08 14:10:09
status: done
prompt: sdd/prompts/202605/agents_jump_unread_done.md
---
# Plan: Add `,j` jump to next unread done agent

## Goal

Add a leader-mode keymap on the Agents tab so `,j` jumps to the next unread completed agent row. The jump must leave the
target row marked unread immediately after selection, instead of using the normal selection behavior that clears unread
state.

## Current Behavior

- Completed-agent unread state is session-local in `AceApp._unread_completed_agent_ids`.
- `_sync_unread_completed_agents()` adds an identity when a visible agent transitions from a non-terminal status to
  `DONE` or `FAILED`, except for the currently selected row.
- Normal Agents-tab selection clears unread state:
  - `BasicNavigationMixin._navigate_agents_panel()` clears unread on `j` / `k` row navigation.
  - `EventHandlersMixin.on_agent_list_selection_changed()` clears unread on list selection.
- The unread indicator is passed to `AgentList.update_list()` and row patching through `unread_agents=...`.
- Leader-mode dispatch already owns `,` subkeys in `LeaderModeMixin._handle_leader_key()`, with defaults in both
  `LeaderModeKeymaps` and `src/sase/default_config.yml`.

## Implementation

1. Add a new leader-mode command id, probably `jump_to_next_unread_done_agent`, with default subkey `j`.
   - Update `LeaderModeKeymaps` in `src/sase/ace/tui/keymaps/types.py`.
   - Update `ace.keymaps.modes.leader_mode.keys` in `src/sase/default_config.yml`.
   - Update command palette metadata in `src/sase/ace/tui/commands/catalog.py` and scope it to the Agents tab.
   - Update command availability so it is only available on Agents when an unread terminal agent exists.
   - Update help/footer surfaces where leader-mode Agents-tab bindings are listed.

2. Implement the jump behavior as an Agents-tab helper/action.
   - Search the rendered visible agent order, not raw list order, so the command follows what the user sees.
   - Exclude collapsed banner rows because the target is an agent entry.
   - Start after the current selected visible agent when focused on an agent; if focused on a banner or the current row
     is not visible, anchor sensibly to the visible order.
   - Wrap around to the first matching unread terminal row.
   - Restrict targets to identities in `_unread_completed_agent_ids` whose `status` is terminal (`DONE` / `FAILED`, via
     the existing dismissable-status convention).

3. Preserve unread state during the jump.
   - Set `current_idx` and clear `_current_group_key`.
   - Re-add or leave the selected target identity in `_unread_completed_agent_ids` after changing selection so the
     target remains unread.
   - Patch the target row with `_try_patch_agent_row()` when possible; otherwise refresh the agents display with
     `list_changed=True, defer_detail=True`.
   - Refresh panel highlights when needed so the cursor moves immediately.

4. Wire leader-mode dispatch.
   - In `LeaderModeMixin._handle_leader_key()`, handle the new leader subkey on the Agents tab by calling the helper.
   - Keep the command a no-op outside the Agents tab, matching existing leader command style.
   - Notify with a low-severity message when no unread completed agent exists.

## Tests

Add focused unit coverage rather than a full TUI integration test:

- Keymap/config tests:
  - Default leader mode includes `jump_to_next_unread_done_agent == "j"`.
  - Help modal / command catalog show `,j` for the Agents-tab command.
  - Command availability is false without unread done agents and true when context reports unread completed agents.

- Behavior tests:
  - Jump chooses the next unread `DONE` agent after the current visible row and wraps.
  - Jump ignores running agents and read completed agents.
  - Jump preserves `_unread_completed_agent_ids` for the target after selection.
  - Jump follows rendered visible order, using `_agents_visible_order()`.
  - Jump clears banner focus and updates display/patch paths.

## Verification

After implementation:

- Run the focused tests for keymaps, command availability, unread behavior, and agent navigation.
- Because this repo requires it after code changes, run `just install` if needed, then `just check`.

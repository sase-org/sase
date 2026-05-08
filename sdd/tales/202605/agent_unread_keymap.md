---
create_time: 2026-05-08 15:41:52
status: done
prompt: sdd/prompts/202605/agent_unread_keymap.md
---
# Plan: Agents Tab Manual Unread Toggle

## Goal

Add a configurable `U` keymap on the `sase ace` Agents tab that toggles the selected agent row's unread marker. Pressing
`U` once manually marks the focused agent row unread; pressing `U` again marks it read. A manually marked row must not
be acknowledged merely because it is already selected or because an agents refresh runs while it remains selected. It
should only be auto-acknowledged after the user leaves that row and later navigates back to it.

## Current Shape

- Agent unread state is session-local and lives in `AceApp._unread_completed_agent_ids`.
- Row rendering already accepts `unread_agents` in `AgentList.update_list()` and `patch_agent_row()`.
- New completed agents are marked unread by `_sync_unread_completed_agents()`, which also clears unread for the
  currently selected row on the Agents tab.
- Normal Agents-tab navigation/selection clears unread in:
  - `src/sase/ace/tui/actions/navigation/_basic.py`
  - `src/sase/ace/tui/actions/event_handlers.py`
- `,j` jumps to unread completed agents and intentionally preserves unread state.
- Configurable app keymaps are defined in `src/sase/default_config.yml`, `src/sase/ace/tui/keymaps/types.py`, and the
  fallback `src/sase/ace/tui/bindings.py`.
- Help content for the Agents tab lives in `src/sase/ace/tui/modals/help_modal/bindings.py`.

## Design

Introduce a second session-local set, `_manual_unread_agent_ids`, that records identities explicitly toggled unread by
the user. This set acts as a guard against the normal "selected row is read" behavior.

Behavior:

1. `U` on Agents tab with an agent selected:
   - If the selected identity is unread because it was manually marked, remove it from both `_manual_unread_agent_ids`
     and `_unread_completed_agent_ids` (undo / mark read).
   - Otherwise add it to both sets (manual mark unread).
   - Patch only that row when possible; fall back to `_refresh_agents_display(list_changed=True, defer_detail=True)`.
   - Do not auto-advance the cursor.

2. Automatic read acknowledgment:
   - Existing navigation and mouse selection clearing should skip the clear when the selected agent identity is
     currently in `_manual_unread_agent_ids`.
   - When the user navigates away from a manually unread row, remove that identity from `_manual_unread_agent_ids` but
     leave it in `_unread_completed_agent_ids`. This arms the row for the normal read-clear path the next time it is
     selected.
   - The next navigation or selection back to that row then clears `_unread_completed_agent_ids` normally.

3. Refresh/finalize behavior:
   - `_sync_unread_completed_agents()` should preserve selected unread state when the selected identity is manually
     guarded.
   - Prune `_manual_unread_agent_ids` alongside `_unread_completed_agent_ids` for identities that are no longer visible,
     so stale manual guards do not survive filtering/dismissal.

4. Scope:
   - The manual unread toggle should target agent rows only, not collapsed group banner rows.
   - It can apply to any selected agent row, not just DONE/FAILED rows, because the user asked for the currently
     selected agent row and the renderer already supports unread styling independently of status. Existing `,j` still
     only jumps among unread DONE/FAILED rows.

## Files To Change

- `src/sase/default_config.yml`
  - Add `toggle_agent_unread: "U"` under Agent / axe keymaps.
- `src/sase/ace/tui/keymaps/types.py`
  - Add binding metadata and `AppKeymaps.toggle_agent_unread`.
- `src/sase/ace/tui/bindings.py`
  - Add fallback `Binding("U", "toggle_agent_unread", ...)`.
- `src/sase/ace/tui/actions/_state_init.py`
  - Initialize `_manual_unread_agent_ids`.
- `src/sase/ace/tui/actions/agents/_core.py`
  - Add type annotation for `_manual_unread_agent_ids`.
  - Add helper methods for clearing/arming manual unread state and the `_toggle_agent_unread()` implementation.
- `src/sase/ace/tui/actions/marking.py`
  - Add `action_toggle_agent_unread()` and route it only on the Agents tab.
- `src/sase/ace/tui/actions/navigation/_basic.py`
  - Before changing away from an agent stop, arm manual unread for the old row.
  - Use a helper to acknowledge unread on the destination row, respecting the manual guard.
- `src/sase/ace/tui/actions/event_handlers.py`
  - Apply the same selected-row acknowledgment helper for mouse/highlight selection changes.
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
  - Preserve selected manual-unread row through refresh and prune stale manual guards.
- `src/sase/ace/tui/modals/help_modal/bindings.py`
  - Document `U` in the Agents tab help.

## Tests

Add/adjust focused tests in `tests/ace/tui/test_agent_unread_indicator.py`:

- `U` marks the selected agent unread without moving selection and patches the row.
- Pressing `U` again removes unread/manual state and patches the row.
- Refresh/finalize does not clear a selected manually unread row.
- Navigating away from a manually unread row leaves it visibly unread but removes the manual guard.
- Navigating back to that row clears the unread marker.
- Mouse/selection handling respects the same guard.

Update keymap/help tests:

- Default registry binds `toggle_agent_unread` to `U`.
- App binding count expectations are updated.
- Agents help includes the manual unread toggle.

## Verification

Run:

```bash
just install
just test tests/ace/tui/test_agent_unread_indicator.py tests/test_keymaps.py tests/ace/tui/test_show_agent_run_log_keymap.py tests/ace/tui/test_agent_jk_navigation.py
just check
```

If the targeted tests expose unrelated fixture drift, fix local expectations that are directly tied to the new keymap,
then still run `just check` before finishing because this repo requires it after source changes.

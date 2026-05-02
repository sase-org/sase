---
create_time: 2026-04-30 17:33:56
status: done
prompt: sdd/prompts/202604/notification_jump_keymap.md
---
# Add apostrophe jump hints to the notification panel

## Goal

Support the existing apostrophe jump-to-entry keymap inside the notification panel. When the notification panel is open,
pressing `'` should enter a one-key jump mode whose hints are rendered next to notification rows, not section headers or
other UI. Pressing a hint should select that notification as if the user highlighted it and pressed Enter.

## Current behavior

- App-level `'` is configured as `jump_to_entry` in `src/sase/default_config.yml` and `src/sase/ace/tui/bindings.py`.
- App-level jump mode lives in `src/sase/ace/tui/actions/navigation/_advanced.py` and uses:
  - `JUMP_HINT_CHARS`
  - `normalize_jump_key()`
  - `build_jump_hint_maps()`
- The notification panel is `NotificationModal` in `src/sase/ace/tui/modals/notification_modal.py`.
- Notification rows are rendered through `_create_sectioned_options()`, with disabled section headers using `hdr:*` IDs
  and selectable notification rows using the raw notification index as the option ID.
- The modal currently has no jump mode. Its `'` key is unbound, and app-level bindings do not handle the modal's focused
  `OptionList`.

## Design

Add a modal-local jump mode to `NotificationModal`.

- Reuse the shared jump-hint helpers from `sase.ace.tui.actions.navigation.jump_hints` so notification hints follow the
  same alphabet and uppercase handling as the rest of the TUI.
- Keep the mode scoped to the notification modal. Do not add global app state or new config keys.
- Allocate hints in visual notification order via `_visual_notification_index_order()`, which already skips section
  headers and follows the sectioned render order.
- Render hints by extending `_create_styled_label()` with an optional `hint_char` parameter and threading a `jump_hints`
  map through `_create_sectioned_options()`.
- Store modal-local state:
  - `_entry_jump_mode_active: bool`
  - `_entry_jump_hint_to_index: dict[str, int]`
  - `_entry_jump_index_to_hint: dict[int, str]`
  - `_entry_jump_last_index: int | None`
- Pressing `'` outside modal jump mode should:
  - If notifications exist, build hint maps, enable jump mode, rebuild options with hints, and update the footer/help
    line.
  - If there are no selectable notifications, do nothing.
- Pressing a hint while jump mode is active should:
  - Save the previously selected notification index for apostrophe back-jump.
  - Highlight and dismiss the selected notification, matching Enter behavior.
- Pressing `'` while jump mode is active should:
  - Jump back to the last selected notification when one exists.
  - Otherwise behave like the first hint (`1`), matching existing app-level behavior.
- Pressing Esc while jump mode is active should cancel jump mode and leave the modal open.
- Pressing an invalid jump key while jump mode is active should exit jump mode without selecting, matching app-level
  jump mode.

## Implementation steps

1. Update `NotificationModal` imports to include `build_jump_hint_maps` and `normalize_jump_key`.
2. Add apostrophe binding to `NotificationModal.BINDINGS`, wired to `action_jump_to_entry`.
3. Add modal-local jump state in `NotificationModal.__init__`.
4. Add helper methods to start, exit, render, and handle notification jump mode:
   - `_jump_candidate_indices()`
   - `action_jump_to_entry()`
   - `_exit_entry_jump_mode()`
   - `_handle_entry_jump_key()`
   - `_select_notification_index()`
   - `_update_hint_footer()`
5. Override `NotificationModal.on_key()` to intercept jump-mode keystrokes with `normalize_jump_key()` before regular
   modal actions.
6. Extend `_create_styled_label()` and `_create_sectioned_options()` so only notification entries receive `[hint]`
   markers.
7. Ensure list rebuilds triggered by dismiss/mute/snooze/read-all clear stale hint state unless they are specifically
   rebuilding to show jump hints.
8. Add focused tests in `tests/test_notification_modal.py` for:
   - hint markers render only on notification rows in visual order,
   - apostrophe without history selects the first visual notification,
   - uppercase hint characters are dispatched correctly,
   - apostrophe back-jump toggles to the previous notification,
   - Escape cancels jump mode without dismissing the modal.

## Verification

- Run targeted tests:
  - `pytest tests/test_notification_modal.py tests/ace/tui/test_jump_to_entry_hints.py`
- Because this repo's memory requires it after changes, run:
  - `just install`
  - `just check`

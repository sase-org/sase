---
create_time: 2026-04-30 18:34:28
status: done
---
# Fix notification panel jump hints so they navigate instead of closing

## Goal

Make apostrophe jump mode inside the notification panel behave like navigation, not activation. When the panel is open
and the user presses `'`, numbered/lettered hints should move the highlighted notification row and update the right-side
preview while keeping the notification panel open. The user can then press Enter to activate the selected notification,
or use normal panel actions like `x`, `m`, `s`, and file scrolling.

## Current Behavior

The hints render correctly in visual order, but pressing a hint closes the modal immediately. This is not caused by a
missed `event.stop()` or a stray `OptionList` binding: the modal's jump handler explicitly selects-and-dismisses.

The relevant path is:

- `NotificationOptionMixin.on_key()` intercepts keys while `_entry_jump_mode_active` is true.
- `_handle_entry_jump_key()` resolves the pressed hint to a notification index.
- `_select_notification_index()` sets the highlighted row, clears jump mode, updates the footer, and then calls
  `self.dismiss(notification)`.
- The parent `_show_notification_modal()` callback treats a non-`None` dismissed notification like Enter/click and
  dispatches the notification action.

That makes jump hints equivalent to activation rather than navigation. The focused tests currently encode that behavior
by asserting `modal.dismiss(...)` is called for numbered hints and apostrophe back-jump.

## Intended Behavior

Use jump hints to reposition inside the panel:

- Pressing `'` outside jump mode enters notification-local jump mode and renders row hints.
- Pressing a valid hint moves the highlight to that notification, updates the file/details preview, exits jump mode,
  removes hint markers, and leaves the modal open.
- Pressing `'` inside jump mode keeps the existing first/back semantics, but the result is also navigation-only.
- Pressing Escape while jump mode is active cancels jump mode and leaves the current highlight unchanged.
- Pressing an invalid jump key exits jump mode without changing the selected notification.
- Pressing Enter after a jump still activates the currently highlighted notification through the existing
  `on_option_list_option_selected()` path.

## Technical Design

Keep the existing modal-local jump state and hint rendering. Change only what the hint dispatch does after resolving a
target.

1. Replace selection-by-dismissal with selection-by-highlight.
   - Rename or repurpose `_select_notification_index()` to make its contract navigation-only, e.g.
     `_jump_to_notification_index()`.
   - It should validate the target index, set the `OptionList.highlighted` row for that notification, clear jump mode,
     update the footer, rebuild/remove hints if needed, and return `True`.
   - It must not call `self.dismiss(notification)`.

2. Preserve preview updates.
   - Setting `OptionList.highlighted` may emit `OptionHighlighted` in the live TUI, but the direct unit tests should not
     rely on Textual message delivery.
   - After changing the highlight, explicitly reset `_current_file_index` and call `_display_file()` for the target
     notification, or route through the same helper used by `on_option_list_option_highlighted()`.

3. Keep Enter/click activation unchanged.
   - `on_option_list_option_selected()` should remain the single path that dismisses with a notification result.
   - Add a focused test proving: jump hint changes highlight/preview and does not dismiss; then invoking
     `on_option_list_option_selected()` for the highlighted row still dismisses with the selected notification.

4. Adjust apostrophe first/back history.
   - Preserve `_entry_jump_last_index` updates before moving, so repeated jump-mode apostrophe can toggle between the
     previous and current notification.
   - Update tests so apostrophe-first and apostrophe-back assert highlight movement, last-index bookkeeping, and no
     modal dismissal.

5. Improve test coverage at the event level.
   - Keep existing pure method tests for hint map ordering and uppercase handling.
   - Add or update tests for `on_key()` using a small fake key event to prove valid hints call `prevent_default()` and
     `stop()` while leaving the modal open.
   - Prefer a lightweight `run_test()`/Pilot test if practical: mount `NotificationModal`, press `'`, press `1`, assert
     the screen stack still contains the modal and the highlighted row changed. This would catch the exact regression
     the current direct-method tests missed.

6. Leave config and shared jump helpers alone.
   - No keymap/default-config changes are needed; the apostrophe binding already reaches the modal action.
   - `build_jump_hint_maps()` and `normalize_jump_key()` remain shared with app-level jump mode.

## Files To Change

- `src/sase/ace/tui/modals/notification_modal_options.py`
  - Change hint dispatch from activate/dismiss to navigate/highlight.
  - Ensure preview/footer state remains correct after a jump.

- `tests/test_notification_modal.py`
  - Update existing notification jump tests that currently expect `dismiss()`.
  - Add coverage for navigation-only behavior, Enter-after-jump activation, event stopping, invalid-key cancellation,
    and preview refresh.

## Verification

Run from this workspace, installing the editable dev environment first if needed:

```bash
just install
.venv/bin/pytest tests/test_notification_modal.py tests/ace/tui/test_jump_to_entry_hints.py
just check
```

Manual check in `sase ace`:

1. Open the notification panel.
2. Press `'` and confirm hints appear on notification rows only.
3. Press `1` or another visible hint.
4. Confirm the panel stays open, the highlighted row moves to that notification, and the right preview updates.
5. Press Enter and confirm the selected notification action still runs.

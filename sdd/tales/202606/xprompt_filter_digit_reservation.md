---
create_time: 2026-06-27 09:48:15
status: done
prompt: sdd/prompts/202606/xprompt_filter_digit_reservation.md
---
# Plan: Reserve Numeric Tab Keys in the XPrompts Filter

## Context

The Admin Center modal already binds `0`-`9` at the modal level:

- `1`-`5` jump to the current five Admin Center tabs.
- `6`-`9` and `0` call the same action but are intentionally out of range today, so they are reserved no-ops.

The bug happens because the XPrompts tab focuses `BrowserFilterInput` by default. A focused Textual `Input` consumes
printable digits as text before the modal bindings can see them, so pressing `1` after entering the XPrompts tab inserts
`1` into the empty filter instead of jumping to the Config tab.

The fix belongs in the XPrompts filter input, not in the modal tab action. Neighboring panes already use the same local
input-forwarding pattern for printable keys like `[` and `]`. This is also a purely local key-event change with no disk
I/O or background work in the event path.

## Proposed Changes

1. Update `src/sase/ace/tui/modals/xprompt_browser_filter_input.py`.

2. In `BrowserFilterInput.on_key`, detect digit keys while the filter value is empty:
   - Stop and prevent the input default so the digit is not inserted as the first filter character.
   - Forward the digit to the host Admin Center's `action_focus_center_tab(int_digit)`.
   - This makes `1`-`5` switch tabs and makes `6`-`9`/`0` reserved no-ops through the existing modal action.

3. Preserve digit typing after the user has started a filter:
   - If `self.value` is non-empty, let digit keys fall through to normal `Input` handling.
   - This allows filters like `bug2`, `2026`, and `x1` while still preventing a digit as the first filter keystroke.

4. Adjust Tab handling in `BrowserFilterInput.on_key`:
   - Keep the existing empty-filter behavior where `tab` routes to `action_load_xprompt()` for a loadable row.
   - When the filter contains text, do not intercept `tab`; let Textual's normal focus traversal move focus out of the
     filter so modal-level numeric tab keymaps work again.
   - If tests show default focus traversal does not move focus as expected, explicitly focus the XPrompts option list in
     that non-empty-filter branch.

5. Leave `ConfigCenterModal` bindings unchanged.
   - The modal already owns all numeric tab reservations.
   - No default keymap config update is needed because this does not add or rename a configured keymap.

## Tests

Add focused regression coverage to the existing Admin Center/XPrompts test area:

1. Empty XPrompts filter reserves numeric keys:
   - Open Admin Center on Config.
   - Press `5` to activate XPrompts and focus its empty filter.
   - Press `1`.
   - Assert the active tab becomes Config, rather than the XPrompts filter receiving `"1"`.

2. Future numeric tabs remain reserved:
   - With the XPrompts filter empty and focused, press one or more out-of-range digits such as `6`, `9`, and `0`.
   - Assert the active tab remains XPrompts and the filter value remains empty.

3. Digits are allowed after filter text exists:
   - With the XPrompts filter focused, type a non-digit prefix such as `n`.
   - Press a digit such as `1`.
   - Assert the filter value contains `n1` and the active tab is still XPrompts.

4. Tab can escape after typed filter text:
   - Seed a loadable markdown-backed xprompt.
   - Type filter text into the XPrompts filter.
   - Press `tab`.
   - Assert the Admin Center stays open, no prompt bar is loaded, focus leaves the filter, and pressing `1` then
     switches to Config.

5. Keep existing load behavior covered:
   - The current empty-filter `tab` load test should continue to pass for loadable rows.
   - Existing `ctrl+i` load tests should remain unchanged.

## Verification

After implementing the code and tests:

1. Run the targeted tests first:
   - `python -m pytest tests/ace/tui/test_config_center_tabs.py tests/ace/tui/test_xprompt_browser_load_keymap.py`

2. Run the required repository check:
   - `just check`

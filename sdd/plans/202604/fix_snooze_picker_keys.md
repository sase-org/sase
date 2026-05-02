---
create_time: 2026-04-27 11:15:24
status: done
prompt: sdd/prompts/202604/fix_snooze_picker_keys.md
---
# Fix Snooze Picker Key Handling

## Problem

The notification modal opens `SnoozeDurationModal` when the user presses `s`. The picker renders preset rows for `1`,
`2`, `3`, `4`, `c`, and `esc`, and it declares matching modal bindings. In practice, the visible picker ignores the
printable shortcuts.

I reproduced the issue with a Textual pilot that opens `NotificationModal`, presses `s`, then presses `1`. After the
snooze screen is pushed, app focus is on `#snooze-custom-input` even though that input has the `hidden` class. Because
Textual's `Input` consumes printable key events, `1`, `2`, and `c` are treated as text input instead of bubbling to
`SnoozeDurationModal.BINDINGS`.

## Root Cause

`SnoozeDurationModal.compose()` mounts the custom-duration `Input` immediately and only hides it with CSS. The widget
remains focusable, so Textual chooses it as the focused widget when the modal opens. A focused `Input` intercepts
printable keys before the modal's digit/custom bindings can run.

## Plan

1. Make the custom snooze input non-focusable while hidden.
   - Initialize `#snooze-custom-input` as disabled as well as hidden.
   - When the user presses `c`, enable it, reveal it, clear it, and focus it.
   - When `esc` backs out of custom entry, hide it again and disable it.

2. Preserve existing behavior.
   - Preset actions continue to return relative `timedelta` values.
   - Tomorrow morning continues to return an absolute `datetime`.
   - Custom entry continues to parse directive-style durations and show the validation error on bad input.
   - `esc` still cancels the picker from preset mode and backs out from custom mode.

3. Add regression coverage at the event-dispatch level.
   - Add async Textual pilot tests for `SnoozeDurationModal` that press `1`, `2`, and `c` after mount.
   - Assert `1`/`2` dismiss with the expected durations.
   - Assert `c` reveals and focuses the custom input, proving the shortcut is handled by the modal before the input
     becomes active.
   - Add a back-out assertion that `esc` from custom mode hides and disables the input so future preset shortcuts are
     not swallowed.

4. Verify narrowly first, then broadly enough for this repo.
   - Run the snooze modal tests and notification modal tests.
   - Because this repo requires it after changes, run `just check` before the final response.

---
create_time: 2026-05-29 08:52:15
status: done
prompt: sdd/prompts/202605/notification_bracket_footer.md
---
# Plan: Show Notification Tag Bracket Keymaps In Footer

## Context

The notification panel already supports square-bracket tag navigation:

- `NotificationModal.BINDINGS` maps `left_square_bracket` to `prev_notification_tag_tab`.
- `NotificationModal.BINDINGS` maps `right_square_bracket` to `next_notification_tag_tab`.
- `action_prev_notification_tag_tab()` and `action_next_notification_tag_tab()` cycle the current notification tag tab
  when there is more than one tab.

The missing piece is discoverability. The footer users see inside the notification modal is the `#notification-hints`
label populated from `DEFAULT_HINT_TEXT` in `src/sase/ace/tui/modals/notification_modal_constants.py`, and that string
does not mention `[` or `]`.

This is presentation-only TUI behavior. It does not cross the Rust core/backend boundary, and it does not require
changes to the configurable app keymap defaults because these bracket bindings are modal-local `BINDINGS`, not entries
in `ace.keymaps.app`.

## Implementation

Update the notification modal footer text so it advertises the existing bracket bindings. The smallest safe change is to
add a compact hint to `DEFAULT_HINT_TEXT`, for example:

```text
[/]: tags
```

or, if a more explicit label still fits cleanly:

```text
[: prev tag  ]: next tag
```

The footer is constrained to one row (`#notification-hints { height: 1; text-align: center; }`), so the final wording
should stay short and readable. The rest of the hint line is already compact and always shows some keys whose action may
be a no-op for the current notification, such as file navigation without attachments, so showing tag navigation
unconditionally is consistent with the current pattern.

If the explicit wording makes the one-line footer too crowded in practice, prefer the compact `[/]: tags` form over
introducing dynamic footer state. Dynamic display based on `len(self._tag_tabs()) > 1` would be possible, but it adds
extra update points after dismiss/mute/snooze/tab changes for very little benefit.

## Tests

Add a focused test near the existing notification modal binding tests that asserts the normal footer hint text includes
the square-bracket affordance. This guards against the exact regression without needing to mount the full modal.

Existing tests already cover:

- the bracket bindings themselves in `tests/test_notification_modal_action_bindings.py`;
- the tab-cycling behavior in `tests/test_notification_modal_mark_and_tabs.py`;
- jump mode restoring `DEFAULT_HINT_TEXT` through `_update_hint_footer()`.

## Verification

Run the focused notification modal tests first:

```bash
pytest tests/test_notification_modal_action_bindings.py tests/test_notification_modal_mark_and_tabs.py tests/test_notification_modal_sections.py
```

Because this repo requires it after source/test changes, run:

```bash
just install
just check
```

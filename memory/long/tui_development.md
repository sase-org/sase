---
keywords: [TUI, textual, widget, modal, keymap, panel, ace tui, keybinding, prefix mode]
---

# TUI Development

## Reactive Properties

All reactives use `recompose=False`. Watch callbacks do manual `.update()` / `_refresh_display()` instead of DOM
rebuild. Example: setting `current_idx` triggers `watch_current_idx()` which calls `_refresh_display()` or the
tab-specific display method.

## Prefix-Key Dispatch

Each mode has a `_*_mode_active` boolean flag. Flow:

1. Activate flag (e.g., `self._copy_mode_active = True`)
2. Update footer to show mode-specific bindings
3. Wait for second key press
4. Dispatch to handler based on key
5. Clear flag
6. Restore footer via `_refresh_current_tab()`

Dispatch happens in `on_key()` in the EventHandlers mixin — checks each mode flag and calls the appropriate handler.
These are NOT Textual bindings; they're manual key dispatch.

## Modal Copy Mode

Modals must inherit `CopyModeForwardingMixin` so that % (copy mode) keys are forwarded to the app instead of consumed by
the modal.

## Widget Messaging Pattern

1. List widget detects selection → posts `SelectionChanged(index)` message
2. App catches message in handler → updates `current_idx` reactive
3. Watch callback fires → calls `_refresh_display()`
4. Display method queries detail panel widget → calls `panel.update_display(data)`

## Pitfalls

- **Don't call `_refresh_display()` from widget methods** — emit a message instead and let the app handle it
- **Don't query widgets in `compose()`** — use `on_mount()` (widgets aren't mounted yet during compose)
- **Don't use `recompose=True` on frequently-changing reactives** — manual updates are much cheaper
- **Clear mode flags on tab change** — footer restoration happens via `_refresh_display()` on tab switch, but mode flags
  should be reset to avoid stale state

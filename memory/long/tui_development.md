---
keywords: [TUI, textual, widget, modal, keymap, panel, ace tui, keybinding, prefix mode]
---

# TUI Development

## Architecture

Framework: Textual. Main app: `AceApp` with 18 action mixins (AgentWorkflow, Agents, Axe, ChangeSpec, Clipboard,
CustomMode, EventHandlers, HintActions, Lifecycle, Marking, Navigation, ProposalRebase, Rename, StatusActions, Sync,
TaskActions, WorkspaceActions, BaseActions).

**3 tabs:** changespecs, agents, axe. Toggled via `.hidden` CSS class — no DOM recompose. Tab type:
`Literal["changespecs", "agents", "axe"]`.

## Reactive Properties

All reactives use `recompose=False`. Watch callbacks do manual `.update()` / `_refresh_display()` instead of DOM
rebuild. Example: setting `current_idx` triggers `watch_current_idx()` which calls `_refresh_display()` or the
tab-specific display method.

## Prefix-Key Modes

Modes: fold (z), copy (%), leader (comma), bang (!), plus custom modes via config. Additional internal modes: hint,
accept, rewind, checkout.

**Pattern:** Each mode has a `_*_mode_active` boolean flag. Flow:

1. Activate flag (e.g., `self._copy_mode_active = True`)
2. Update footer to show mode-specific bindings
3. Wait for second key press
4. Dispatch to handler based on key
5. Clear flag
6. Restore footer via `_refresh_current_tab()`

Dispatch happens in `on_key()` in the EventHandlers mixin — checks each mode flag and calls the appropriate handler.
These are NOT Textual bindings; they're manual key dispatch.

## Keymap Resolution

1. **Defaults** loaded from `default_config.yml` (single source of truth)
2. **User/plugin overrides** merged
3. **Validation** — invalid keys revert to defaults; duplicate keys revert the conflicting user override
4. **Prefix sync** for modes, plus conflict detection for custom mode prefixes
5. **`KeymapRegistry`** object created and passed to widgets (footer, tab bar)

## Modal Lifecycle

`push_screen(Modal, callback)` → user interacts → `modal.dismiss(result)` → callback fires with result.

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

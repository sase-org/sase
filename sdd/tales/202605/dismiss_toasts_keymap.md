---
create_time: 2026-05-10 13:58:28
status: done
prompt: sdd/prompts/202605/dismiss_toasts_keymap.md
---
# Plan: Add `<ctrl+l>` Keymap to Dismiss Visible Toasts

## Goal

Add a TUI keybinding `<ctrl+l>` that immediately dismisses any currently-visible toast notifications. The motivating use
case: after triggering `%s` to copy a `sase ace` snapshot, the user wants the snapshot pane to be free of stale toasts
(e.g. "Copied: Snapshot" or older notifications) when capturing/sharing it.

The action should be a no-op when no toasts are visible, work on every tab, and not consume any other state.

## Background

### Toast plumbing (Textual)

`App.notify(message, severity=...)` is the only way toasts get created in this codebase (e.g.
`src/sase/ace/tui/actions/clipboard/_core.py:181` for the `%s` snapshot copy case). Textual stores active notifications
in `App._notifications` (a `Notifications` collection) and renders them via a `ToastRack` containing `Toast` widgets.
There is no public `clear_notifications()` API in the version of Textual we use, but two stable private hooks exist:

- `app._notifications.clear()` — wipes the underlying state
- `app._refresh_notifications()` — rebuilds the `ToastRack` from current state

Calling them in sequence is exactly what `App._unnotify()` does internally per-toast on expiry, so this is the intended
composition. (Alternative: `app.query(Toast).remove()` — public query API, but leaves `_notifications` state diverged
from the DOM, so we'd lose the "right" semantics if Textual ever re-renders toasts after a layout event.)

### Keymap registration pipeline

There are five places a new app-level binding must flow through. The `default_config.yml` file is the single source of
truth, but the dataclass and metadata table must list the field too, and the `DEFAULT_BINDINGS` fallback in
`bindings.py` must mirror the default. The loader (`keymaps/loader.py`) glues them together and validates that every
dataclass field has a config entry on startup, so a missed step fails fast at app boot.

### `%s` precedent

`%s` (copy snapshot) is implemented through copy-mode in `src/sase/ace/tui/actions/clipboard/_core.py`. Its handler
calls `self.notify("Copied: Snapshot")`, which is itself one of the toasts the user wants to dismiss with `<ctrl+l>`.
The new binding does not need to integrate with copy mode — it is a top-level app action that runs independently.

## Design

### Action

A single new app action `action_dismiss_toasts` on the `AceApp`. It calls `self._notifications.clear()` followed by
`self._refresh_notifications()`. No notify-on-success (that would defeat the purpose). No-op semantics fall out for
free: clearing an already-empty collection is harmless.

Place the implementation in `src/sase/ace/tui/actions/lifecycle.py` next to other always-available app actions like
`action_quit` / `action_refresh`. (lifecycle.py is the natural home for actions that aren't tied to a tab or modal.)

### Key choice: `ctrl+l`

`ctrl+l` is currently unbound in the app keymap (verified against `default_config.yml` lines 30–131 and the
`DEFAULT_BINDINGS` list in `bindings.py`). It conventionally means "redraw / clear screen" in shells and editors, which
fits the intent.

### Visibility in footer / help

This is a global action that's always available, so per the "Footer Keybinding Convention" in `src/sase/ace/AGENTS.md`
it does **not** belong in the keybinding footer (footer is for conditional bindings only). It does belong in the help
modal. Help-modal bindings are listed per-tab in `src/sase/ace/tui/modals/help_modal/bindings.py` — add
`(d(a.dismiss_toasts), "Dismiss toasts")` to the "global" section that already lists `show_notifications`, `refresh`,
`quit`, etc., for each of the changespecs / agents / axe tabs (three call sites near lines 279, 520, 641).

## Files to change

1. **`src/sase/default_config.yml`** — add `dismiss_toasts: "ctrl+l"` under `ace.keymaps.app` (group it under a "Display
   / misc" comment near `show_help` / `browse_xprompts`, since it's a UI-affordance action).
2. **`src/sase/ace/tui/keymaps/types.py`** —
   - Append `("dismiss_toasts", "Dismiss Toasts", False)` to `_BINDING_META`.
   - Add `dismiss_toasts: str` field to the `AppKeymaps` dataclass in the "Display / misc" cluster.
3. **`src/sase/ace/tui/bindings.py`** — add `Binding("ctrl+l", "dismiss_toasts", "Dismiss Toasts", show=False)` to
   `DEFAULT_BINDINGS`.
4. **`src/sase/ace/tui/actions/lifecycle.py`** — add `action_dismiss_toasts(self)` method that calls
   `self._notifications.clear()` then `self._refresh_notifications()`.
5. **`src/sase/ace/tui/modals/help_modal/bindings.py`** — add a `(d(a.dismiss_toasts), "Dismiss toasts")` entry to each
   of the three per-tab "global" sections (changespecs / agents / axe), placed near `show_notifications`.

No new files are needed.

## Testing

- Unit-test path: existing keymap tests (search the test suite for tests that import `_BINDING_META` or `AppKeymaps`)
  will already exercise that the new field validates and round-trips through the loader. Add or extend a test that
  asserts `action_dismiss_toasts` empties `_notifications` and triggers a refresh — the action is small enough to test
  directly with a mocked or real `AceApp` instance, mirroring existing lifecycle action tests if any.
- Manual verification: launch `sase ace`, trigger several toasts (e.g. press `%s` repeatedly, or any action that
  notifies on success), confirm `<ctrl+l>` clears all visible toasts, confirm pressing it again with no toasts is a
  no-op, confirm it works from each tab.
- Run `just check` before declaring done (per `memory/short/build_and_run.md`).

## Risks / Open Questions

- **Textual private API**: `_notifications` and `_refresh_notifications` are underscore-prefixed. Risk is low — they're
  load-bearing for the public `notify()` API itself, which is unlikely to break across minor versions, but worth a
  one-line comment at the call site explaining _why_ private API is necessary (no public clear API exists in our Textual
  version).
- **Naming**: I'm using `dismiss_toasts` for both the config key and the action. Alternative names considered:
  `clear_toasts`, `clear_notifications`. Rejected `clear_notifications` because we already have a different
  `show_notifications` action that operates on the persistent inbox modal — using "notifications" for both would be
  confusing. "Toasts" is the precise Textual term and matches what the user sees.
- **Out of scope**: Not touching the persistent notification inbox (`show_notifications` / `i` key). Not adding a toast
  log or "undismiss" capability.

---
create_time: 2026-04-05 11:28:34
status: done
prompt: sdd/prompts/202604/jump_back_backtick.md
---

# Plan: Backtick "Jump Back" Hint in Jump to All Entries Modal

## Goal

Add a hidden backtick (`` ` ``) hint to the "Jump to All Entries" modal that maps to the user's previous position before
their last cross-tab jump. This enables a quick "jump back" workflow:

1. Press `` ` `` to open the modal, press `f` to jump to entry "f"
2. Later, press `` ` `` again to reopen the modal, press `` ` `` to jump back to where you were

## Design

### State: Track the Pre-Jump Position

Add a `_jump_all_last_position: JumpAllResult | None` attribute (initialized to `None`) on the app. This stores where
the user was _before_ their most recent successful cross-tab jump.

**When it's set**: Only when a jump actually completes (not when the modal is dismissed without selection). Captured in
the `_on_dismiss` callback of `action_jump_to_all_entries()` — the current tab/index/panel at the moment the modal was
opened becomes the "last position" for next time.

**When it's NOT set**: If the user opens the modal and presses Escape or any non-hint key, the last position is
unchanged.

### Modal: Accept and Handle the Last Position

Pass `last_position: JumpAllResult | None` to `JumpAllModal.__init__()`. In `on_key()`, intercept `grave_accent` — if a
last position exists, dismiss with that `JumpAllResult`. If no last position exists, treat it like any other
unrecognized key (dismiss with `None`).

The backtick hint is **hidden** — it does not appear in the entry list display. However, show a subtle indicator in the
modal footer when a last position is available: change the footer from `"press key to jump · esc cancel"` to
`"press key to jump · ` back · esc cancel"` so the user knows the feature is available.

### No Changes to Single-Tab Jump Mode

The single-tab jump mode (`'`) is unaffected. The backtick "jump back" feature is scoped entirely to the cross-tab
modal.

## File Changes

### 1. `src/sase/ace/tui/actions/navigation/_types.py`

Add type hint for the new attribute:

```python
_jump_all_last_position: JumpAllResult | None
```

(With the appropriate TYPE_CHECKING import for `JumpAllResult`.)

### 2. `src/sase/ace/tui/actions/navigation/_advanced.py`

In `action_jump_to_all_entries()`:

- Capture the current position (tab, index, panel focus) into a local `pre_jump_position` variable before opening the
  modal.
- In the `_on_dismiss` callback, if a jump was made (result is not None), set
  `self._jump_all_last_position = pre_jump_position`.
- Pass `self._jump_all_last_position` to the `JumpAllModal` constructor.

### 3. `src/sase/ace/tui/modals/jump_all_modal.py`

- Add `last_position: JumpAllResult | None = None` parameter to `__init__()`.
- Store it as `self._last_position`.
- In `on_key()`: before the final "any other key" fallback, check if `key == "grave_accent"` and
  `self._last_position is not None` — if so, dismiss with `self._last_position`.
- In `compose()`: adjust the footer text when `self._last_position` is not None to include `` ` back ``.

### 4. `src/sase/ace/tui/app.py` (or wherever attributes are initialized)

Initialize `_jump_all_last_position = None` alongside the other `_*_last_idx` attributes.

### 5. `tests/ace/tui/test_jump_to_entry_hints.py`

Add a test for the `JumpAllModal` backtick handling:

- Construct a modal with a `last_position`, verify that sending `grave_accent` produces that result.
- Construct a modal without a `last_position`, verify that `grave_accent` dismisses with `None`.

### 6. Help modal (`src/sase/ace/tui/modals/help_modal/bindings.py`)

Update the "Jump to entry (all tabs)" help text to mention the backtick-back feature, e.g.: `"Jump to entry (all tabs, `
back)"` — or add a separate line for it.

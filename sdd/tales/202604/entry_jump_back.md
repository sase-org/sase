---
create_time: 2026-04-06 15:20:01
status: done
prompt: sdd/prompts/202604/entry_jump_back.md
---

# Plan: Hidden Apostrophe "Jump Back" Hint for Entry Jump Mode

## Goal

When the user presses `'` to enter single-tab jump mode, then presses `'` again, they should jump back to the entry they
previously jumped from on the current tab. Pressing `''` repeatedly should toggle back and forth between the same two
entries.

## Design

### Behavior

1. User is on entry A, presses `'` → jump mode activates with hints `[1]`, `[a]`, etc.
2. User presses `3` → jumps to entry B. The position of A is saved as the "jump back" target.
3. User presses `'` again → jump mode activates. A hidden `'` hint is available.
4. User presses `'` → jumps back to entry A. Position of B is now saved as the jump back target.
5. This toggles indefinitely.

### State Tracking

Add a per-tab dictionary to `app.py` that stores the last jumped-from index:

```python
# Entry jump-back state (per-tab, for '' toggle)
self._entry_jump_last_index: dict[str, int] = {}
# For agents tab, also track which panel was focused
self._entry_jump_last_panel: dict[str, str | None] = {}
```

### Key Handling

In `_handle_entry_jump_key()`, when the key is `"apostrophe"`:

- Check if there's a saved position for the current tab in `_entry_jump_last_index`
- If yes: save current position as the new jump-back target, then jump to the saved position
- If no: exit jump mode (same as any unrecognized key)

### Position Saving

When any successful jump happens via `_handle_entry_jump_key()` (including the `'` jump-back), save `current_idx`
(pre-jump) into `_entry_jump_last_index[current_tab]`. For agents tab, also save `_pinned_panel_focused`.

### Hidden Hint in Footer

Follow the pattern used by fold/bang/leader modes: add an `update_jump_bindings()` method to `KeybindingFooter` that
shows:

- `JUMP ` mode indicator (gold, like other modes)
- `' back` when a jump-back position exists for the current tab
- `<esc> cancel`

Call this from `action_jump_to_entry()` after activating jump mode.

## Changes

### 1. `src/sase/ace/tui/app.py` (~215)

Add two new state variables after the existing jump mode state:

```python
# Entry jump-back state (' toggle)
self._entry_jump_last_index: dict[str, int] = {}
self._entry_jump_last_panel: dict[str, str | None] = {}
```

### 2. `src/sase/ace/tui/actions/navigation/_advanced.py`

**`action_jump_to_entry()`**: After activating jump mode, update the footer to show jump mode bindings.

**`_handle_entry_jump_key()`**: Add apostrophe handling before the `target is None` check:

```python
if key == "apostrophe":
    last_idx = self._entry_jump_last_index.get(self.current_tab)
    if last_idx is not None:
        # Save current position before jumping back
        self._entry_jump_last_index[self.current_tab] = self.current_idx
        if self.current_tab == "agents":
            self._entry_jump_last_panel[self.current_tab] = self._pinned_panel_focused
        # Jump to saved position
        if self.current_tab == "agents":
            saved_panel = self._entry_jump_last_panel.get(self.current_tab)
            if saved_panel is not None:
                self._pinned_panel_focused = saved_panel
        self.current_idx = last_idx
    self._exit_entry_jump_mode()
    return True
```

**Save position on regular jumps**: In the existing jump handling (both agents and non-agents branches), save
`self.current_idx` before setting the new target:

```python
# Before: self.current_idx = target
self._entry_jump_last_index[self.current_tab] = self.current_idx
if self.current_tab == "agents":
    self._entry_jump_last_panel[self.current_tab] = self._pinned_panel_focused
self.current_idx = target
```

### 3. `src/sase/ace/tui/widgets/keybinding_footer.py`

Add `update_jump_bindings()` method:

```python
def update_jump_bindings(self, *, has_back: bool = False) -> None:
    """Update bindings to show entry jump mode options."""
    bindings: list[tuple[str, str]] = []
    if has_back:
        bindings.append(("'", "back"))
    bindings.append(("<esc>", "cancel"))
    text = self._format_bindings(bindings)
    prefix = Text()
    prefix.append("JUMP ", style="bold #FFD700")
    prefix.append_text(text)
    self._update_display(prefix)
```

### 4. `src/sase/ace/tui/actions/navigation/_advanced.py` (footer integration)

In `action_jump_to_entry()`, after setting `_entry_jump_mode_active = True`, call footer update:

```python
self._update_jump_footer()
```

Add helper:

```python
def _update_jump_footer(self) -> None:
    from ...widgets import KeybindingFooter
    try:
        footer = self.query_one("#keybinding-footer", KeybindingFooter)
        has_back = self.current_tab in self._entry_jump_last_index
        footer.update_jump_bindings(has_back=has_back)
    except Exception:
        pass
```

## Testing

Verify with `sase ace --agent`:

1. `--keys apostrophe 1` → jumps to first entry
2. `--keys apostrophe apostrophe` → should jump back (if prior jump exists)
3. Repeat to confirm toggle behavior

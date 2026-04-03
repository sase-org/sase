---
create_time: 2026-04-03 11:32:35
status: done
---

# Jump to Entry (`V` keymap) — Implementation Plan

## Overview

Add a new `V` (jump to entry) keymap that works on all TUI tabs. When pressed, it renders hints (`1-9`, `0`, `a-z`) next
to each entry in the left side-panel, then a single keypress jumps to that entry.

## Context

The TUI has three tabs with left side-panels:

- **CLs tab**: `ChangeSpecList` widget showing ChangeSpecs
- **Agents tab**: `AgentList` widget showing agents/workflows (main + optional pinned panel)
- **AXE tab**: `BgCmdList` widget showing axe parent, lumberjacks, bg commands

The existing hint system (for `v` = view files) works on the **right** detail panel with numeric hints and a text input
bar. This new feature is fundamentally different: hints appear in the **left** list panel, and selection is instant
(single keypress, no input bar).

## Plan

### Phase 1: Keymap Registration (4 files)

1. **`src/sase/default_config.yml`** — Add `jump_to_entry: "V"` under `ace.keymaps.app` in the Navigation section.

2. **`src/sase/ace/tui/keymaps/types.py`** — Add `jump_to_entry: str` field to `AppKeymaps` dataclass and add
   `("jump_to_entry", "Jump to Entry", False)` to `_BINDING_META`.

3. **`src/sase/ace/tui/bindings.py`** — Add `Binding("V", "jump_to_entry", "Jump", show=False)` to `DEFAULT_BINDINGS`.

4. **`src/sase/ace/tui/modals/help_modal/bindings.py`** — Add `V` to the Navigation section in all three tab help
   sections (`cls_bindings`, `agents_bindings`, `axe_bindings`).

### Phase 2: Hint Sequence Utility

5. **`src/sase/ace/tui/actions/hints/_jump.py`** (new file) — Create:
   - `JUMP_HINT_CHARS`: The ordered hint character sequence: `"1234567890abcdefghijklmnopqrstuvwxyz"` (36 chars)
   - `build_jump_hint_map(count: int) -> dict[str, int]`: Maps hint char -> entry index for up to `min(count, 36)`
     entries
   - `JumpToEntryMixin(HintMixinBase)`: Mixin class with `action_jump_to_entry()`, `_exit_jump_mode()`, and
     `_handle_jump_key(key: str) -> bool`

### Phase 3: List Widget Hint Rendering (3 files)

6. **`src/sase/ace/tui/widgets/changespec_list.py`** — Add `show_jump_hints(hint_labels: dict[int, str])` method that
   re-renders the list using stored `_changespecs` with hint labels prepended as `[label] ` in bold yellow (#FFFF00),
   matching the existing hint style.

7. **`src/sase/ace/tui/widgets/agent_list.py`** — Add `show_jump_hints(hint_labels: dict[int, str])` method that
   re-renders the list using stored `_agents` with hint labels prepended.

8. **`src/sase/ace/tui/widgets/bgcmd_list.py`** — Add `show_jump_hints(hint_labels: dict[int, str])` method that
   re-renders items with hint labels prepended.

### Phase 4: Action Implementation & Wiring

9. **`src/sase/ace/tui/actions/hints/_jump.py`** — Implement the `JumpToEntryMixin`:
   - `action_jump_to_entry()`: Computes hint labels for the current tab's entries, calls `show_jump_hints()` on the
     appropriate list widget, stores the hint->index map, sets `_jump_mode_active = True`
   - For agents tab: only hint entries in the focused panel (using `_active_panel_indices()`)
   - `_handle_jump_key(key: str) -> bool`: Looks up key in `_jump_hint_map`, sets `current_idx` if found, exits jump
     mode, returns True if handled
   - `_exit_jump_mode()`: Clears `_jump_mode_active`, refreshes the appropriate tab display to remove hints

10. **`src/sase/ace/tui/actions/hints/__init__.py`** — Add `JumpToEntryMixin` to the `HintActionsMixin` class hierarchy.

11. **`src/sase/ace/tui/actions/hints/_types.py`** — Add `_jump_mode_active: bool` and `_jump_hint_map: dict[str, int]`
    type declarations to `HintMixinBase`.

12. **`src/sase/ace/tui/actions/event_handlers.py`** — Add a `_jump_mode_active` check in `on_key()` at appropriate
    priority (before fold_mode, since it's a transient mode): if active, call `_handle_jump_key(event.key)`, and if
    handled, prevent default + stop.

### Phase 5: App State Init

13. **`src/sase/ace/tui/app.py`** — Initialize `_jump_mode_active = False` and `_jump_hint_map: dict[str, int] = {}` in
    `__init__`.

## Key Design Decisions

- **No input bar**: Unlike the `v` (view files) hint system, `V` uses instant single-keypress selection. No
  `HintInputBar` is mounted.
- **Hint sequence**: `1-9, 0, a-z` (36 total) — digits first for the most common entries, then letters.
- **Focused panel only**: On the agents tab, hints only appear on the focused panel (main or pinned).
- **on_key priority**: Jump mode intercept happens early in the `on_key` chain (before fold mode etc.) since it's a
  transient state that should capture all keys.
- **Escape cancels**: Pressing escape or any unrecognized key exits jump mode and restores normal list display.
- **Reuse existing refresh**: Exiting jump mode just calls the tab's standard refresh method, which fully rebuilds the
  list without hints.

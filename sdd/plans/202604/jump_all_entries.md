---
create_time: 2026-04-04 15:16:45
status: done
prompt: sdd/prompts/202604/jump_all_entries.md
---

# Plan: Cross-Tab Jump-to-Entry Modal (backtick)

## Summary

Add a new keymap bound to backtick (`` ` ``) that opens a modal showing **all entries across all three tabs** (CLs,
Agents, AXE). Each entry has a single-keypress hint character. Pressing a hint immediately switches to the target tab,
focuses the entry, and dismisses the modal.

This is the cross-tab counterpart to the existing apostrophe (`'`) `jump_to_entry` action, which only shows hints for
the _current_ tab's entries inline.

## Design

### UX Flow

1. User presses `` ` ``
2. A centered modal appears with entries grouped under tab section headers
3. Each entry has a bold yellow hint character (e.g., `[1]`, `[a]`)
4. User presses a single hint key → modal dismisses, app switches to the entry's tab, focuses that entry
5. User presses `Escape` → modal dismisses with no navigation

### Visual Design

```
╭────────────── Jump to Entry ──────────────╮
│                                            │
│  ▸ CLs                                     │
│    [1] my_feature              Draft       │
│    [2] bugfix_auth             Ready       │
│    [3] refactor_db             WIP         │
│                                            │
│  ▸ Agents                                  │
│    [4] my_feature              RUNNING     │
│    [5] review                  WORKFLOW     │
│                                            │
│  ▸ AXE                                     │
│    [6] sase axe                ● running   │
│    [7]   └─ hooks              ● running   │
│                                            │
│        press key to jump · esc cancel      │
╰────────────────────────────────────────────╯
```

- **Section headers**: Bold, colored per tab (teal for CLs, blue for Agents, gold for AXE), with `▸` prefix
- **Hint characters**: Bold yellow `[X]` — consistent with existing jump hint styling (`"bold #FFFF00"`)
- **Entry names**: Teal, matching existing list styling
- **Status**: Right-aligned, colored per status type (same palette as the tab list widgets)
- **Footer hint**: Dim gray instruction text at the bottom

### Hint Assignment

Hints are assigned sequentially: CLs first (most commonly accessed → lowest-effort keys), then Agents, then AXE. Uses
`JUMP_HINT_CHARS = "1234567890abcdefghijklmnopqrstuvwxyz"` (same pool as existing `jump_to_entry`).

If a tab has 0 entries, its section is omitted entirely. If total entries exceed 36, excess entries are shown without
hints (display-only, not selectable).

### Key Decisions

1. **Modal, not inline overlay** — The existing `jump_to_entry` uses inline overlays because entries are already
   visible. Cross-tab entries are not visible, so a modal is the natural choice.

2. **Static display, not OptionList** — Since selection is by hint keypress (not cursor navigation + Enter), the modal
   uses a `Static` widget with Rich `Text` content. No cursor/highlight state needed.

3. **Single keypress** — No Enter required. The `on_key()` handler intercepts hint characters and immediately dismisses.
   This matches the speed/feel of the existing inline jump mode.

4. **Tab switching** — On selection, the modal returns a `JumpAllResult(tab, index)`. The action handler then saves the
   current tab position, switches `current_tab`, sets `current_idx`, and handles agents panel focus correctly.

5. **Only visible entries** — Hidden agents (those filtered by `.` toggle) are excluded. Only entries the user would see
   if they navigated to that tab are shown.

## Implementation

### Phase 1: Keymap Registration

**Files:**

- `src/sase/default_config.yml` — Add `jump_to_all_entries: "grave_accent"` under `ace.keymaps.app`
- `src/sase/ace/tui/keymaps/types.py`:
  - Add `"grave_accent": "\`"`to`\_KEY_DISPLAY`
  - Add `("jump_to_all_entries", "Jump All", False)` to `_BINDING_META`
  - Add `jump_to_all_entries: str` field to `AppKeymaps` (under CL actions, next to `jump_to_entry`)
- `src/sase/ace/tui/bindings.py` — Add `Binding("grave_accent", "jump_to_all_entries", "Jump All", show=False)`

### Phase 2: Modal Implementation

**New file: `src/sase/ace/tui/modals/jump_all_modal.py`**

- `JumpAllResult` dataclass: `tab: TabName`, `index: int`, `pinned_panel_focused: str | None`
- `JumpAllModal(ModalScreen[JumpAllResult | None])`:
  - Constructor receives: `changespecs`, `agents` (with panel index maps), `axe_items`, plus agent visibility state
  - `compose()` yields a `Container` > `Label` (title) + `Static` (rich-formatted entry list) + `Label` (footer hint)
  - `_build_display()` constructs a `Rich.Text` with section headers + entries + hints using `build_jump_hint_maps`
  - `on_key()` intercepts hint chars → `self.dismiss(JumpAllResult(...))`, escape → `self.dismiss(None)`
  - `on_mount()` calls `self.focus()` so key events reach the modal

**Update: `src/sase/ace/tui/modals/__init__.py`** — Add `JumpAllModal` and `JumpAllResult` to imports + `__all__`

**Update: `src/sase/ace/tui/styles.tcss`** — Add CSS for `JumpAllModal`:

- Center-aligned modal with border, constrained width/height
- Consistent with existing modal styling (thick border, padding, background)

### Phase 3: Action Handler

**File: `src/sase/ace/tui/actions/navigation/_advanced.py`**

Add `action_jump_to_all_entries()` method:

1. Gather all entries: `self.changespecs`, visible `self._agents` (via `_main_panel_indices` + `_pinned_panel_indices`),
   `self._axe_items`
2. Push `JumpAllModal` with all entry data
3. On dismiss callback:
   - If result is None → no-op
   - Save current tab position (`_save_current_tab_position`)
   - Switch `self.current_tab` to result.tab
   - If agents tab, set `self._pinned_panel_focused` from result
   - Set `self.current_idx` to result.index

### Phase 4: Help Modal Update

**File: `src/sase/ace/tui/modals/help_modal/bindings.py`**

Add `jump_to_all_entries` entry to the Navigation section of all three tab binding lists (CLs, Agents, AXE), right after
the existing `jump_to_entry` line.

### Phase 5: Testing

- Verify `sase ace --agent --keys grave_accent` opens the modal (or shows the overlay appropriately)
- Test with entries across all tabs
- Test with empty tabs (e.g., no agents running)
- Test hint assignment ordering
- Run `just check` to ensure lint/type/test pass

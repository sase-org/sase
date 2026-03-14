---
status: done
---

# Plan: Unify AXE Tab Side-Panel and `.` Keymap Across All Tabs

## Context

The AXE tab's side-panel and `.` keymap work differently from the Agents and CLs tabs. The goal is to unify behavior:

- AXE tab should show one entry per lumberjack nested under "sase axe" (like workflow steps on Agents tab)
- j/k navigates items; h/l expands/collapses lumberjacks (replacing Ctrl+N/P)
- `.` hides/shows bgcmd entries from the side-panel (panel always visible)
- `◌` indicator prepended to any hideable entry on any tab

## Implementation Steps

### Step 1: Add AXE item data model

**File:** `src/sase/ace/tui/widgets/bgcmd_list.py`

Add `AxeItem` union type for side-panel entries:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class AxeParentItem:
    """The main 'sase axe' parent entry."""

@dataclass(frozen=True)
class LumberjackItem:
    """A lumberjack child entry."""
    name: str

@dataclass(frozen=True)
class BgCmdItem:
    """A background command entry."""
    slot: int

AxeItem = AxeParentItem | LumberjackItem | BgCmdItem
```

### Step 2: Add AXE tab state to app

**File:** `src/sase/ace/tui/app.py`

Add new state in `__init__`:

- `_axe_items: list[AxeItem] = []` — flat list of visible items
- `_axe_last_idx: int = 0` — saved position for tab switching
- `_axe_fold_manager = FoldStateManager()` — fold state for lumberjacks (key: `"axe"`)

### Step 3: Build AXE items list

**File:** `src/sase/ace/tui/actions/axe_display.py`

Add `_build_axe_items()` method:

- Always starts with `AxeParentItem()`
- If fold state for key `"axe"` is not COLLAPSED, add `LumberjackItem(name)` for each lumberjack
- If `_axe_cmds_hidden` is False, add `BgCmdItem(slot)` for each bgcmd slot
- Store result in `self._axe_items`

Derive `_axe_current_view` and `_axe_lumberjack_idx` from selected item:

- `AxeParentItem` → `view="axe"`, `lj_idx=None`
- `LumberjackItem(name)` → `view="axe"`, `lj_idx=index of name in _axe_lumberjack_names`
- `BgCmdItem(slot)` → `view=slot`, `lj_idx=None`

### Step 4: Refactor BgCmdList widget to show all item types

**File:** `src/sase/ace/tui/widgets/bgcmd_list.py`

Update `update_list()` to accept `list[AxeItem]` and format each type:

- `AxeParentItem`: `[*] sase axe (+N steps)` with fold annotation (reuse `FoldStateManager`)
- `LumberjackItem`: `  └─ hooks` with status indicator, indented like workflow children
- `BgCmdItem`: `◌ [*] command...` with `◌` prefix (always, since bgcmds are hideable by `.`)

Lumberjack status indicator: `[*]` running (green), `[·]` idle (dim), `[!]` error (red). Read status via
`read_lumberjack_status(name)`.

### Step 5: Update j/k navigation for AXE tab

**File:** `src/sase/ace/tui/actions/navigation/_basic.py`

Change `action_next/prev_changespec()` for the axe branch to use `current_idx` into `_axe_items` instead of cycling
`_axe_current_view`:

```python
else:  # axe tab
    if len(self._axe_items) == 0:
        return
    if self.current_idx < len(self._axe_items) - 1:
        self.current_idx += 1
    else:
        self.current_idx = 0
```

Add `_axe_last_idx` save/restore in `_save_current_tab_position()` and tab switch methods.

### Step 6: Update `watch_current_idx` for AXE tab

**File:** `src/sase/ace/tui/app.py`

Add axe case to `watch_current_idx`:

```python
elif self.current_tab == "axe":
    self._refresh_axe_display()
```

In `_refresh_axe_display()`, derive `_axe_current_view` and `_axe_lumberjack_idx` from the currently selected
`_axe_items[current_idx]` before updating the display.

### Step 7: Add h/l fold support for AXE tab

**File:** `src/sase/ace/tui/actions/agents/_folding.py`

Update `action_expand_or_layout()` and `action_hooks_or_collapse()` to handle AXE tab:

- `l` on AXE tab: expand `_axe_fold_manager.expand("axe")`, rebuild items
- `h` on AXE tab: if on a lumberjack child, navigate to parent first; collapse `_axe_fold_manager.collapse("axe")`,
  rebuild items

Also update `action_expand_all_folds()` and `action_hooks_or_collapse_all()` for AXE tab.

### Step 8: Update `.` toggle for AXE tab

**File:** `src/sase/ace/tui/actions/changespec.py`

In `action_toggle_hide_reverted()`, update the axe branch:

- Toggle `_axe_cmds_hidden`
- If hiding and current selection is a bgcmd, navigate to axe parent
- Rebuild `_axe_items` and refresh display
- Side panel stays visible (no layout toggle)

### Step 9: Remove Ctrl+N/P lumberjack cycling on AXE tab

**File:** `src/sase/ace/tui/actions/agents/_interaction.py`

Remove the `elif self.current_tab == "axe"` branches from `action_next_agent_file()` and `action_prev_agent_file()`.

**File:** `src/sase/ace/tui/actions/axe.py`

Remove `_next_lumberjack()` and `_prev_lumberjack()` methods.

### Step 10: Make side panel always visible on AXE tab

**File:** `src/sase/ace/tui/app.py`

In `compose()`, remove `classes="hidden"` from `#bgcmd-list-container`.

**File:** `src/sase/ace/tui/actions/axe_display.py`

Remove `_update_axe_layout()` method (no longer needed). Remove calls to it.

### Step 11: Update footer bindings for AXE tab

**File:** `src/sase/ace/tui/widgets/keybinding_footer.py`

In `_compute_axe_bindings()`:

- Remove `^N/P` lumberjack hint
- Add h/l fold hint when lumberjacks exist
- Update `.` label: `"show (N)"` / `"hide (N)"` with bgcmd count

### Step 12: Add `◌` to reverted CLs on CLs tab

**File:** `src/sase/ace/tui/widgets/changespec_list.py`

In `_format_changespec_option()`, add `◌` prefix for reverted/archived CLs when `hide_reverted = False`:

- Pass `hide_reverted` as parameter to `update_list()` and `_format_changespec_option()`
- Check `get_base_status(cs.status) in ("Reverted", "Archived")` and `not hide_reverted`
- Prepend `◌ ` in dim gray

Also update `_calculate_entry_display_width()` to account for the `◌` prefix.

### Step 13: Update BgCmdList.SelectionChanged handler

**File:** `src/sase/ace/tui/actions/event_handlers.py`

Update `on_bg_cmd_list_selection_changed()` to set `current_idx` based on the selected item's position in `_axe_items`,
rather than calling `_switch_to_axe_view()` directly.

### Step 14: Update clear output (`X` key) for lumberjack context

**File:** `src/sase/ace/tui/actions/axe.py`

In `action_clear_axe_output()`, derive the lumberjack name from the selected `_axe_items[current_idx]` instead of using
`_axe_lumberjack_idx`.

## Key Design Decisions

1. **Lumberjack fold default**: COLLAPSED — user presses `l` to expand, matching workflow behavior
2. **bgcmds always show `◌`**: Since all bgcmds are hideable by `.`, they always get the indicator when visible
3. **Selection preservation**: When hiding bgcmds (`.`) and a bgcmd is selected, auto-navigate to axe parent
4. **No FULLY_EXPANDED for axe fold**: Lumberjacks don't have hidden steps, so EXPANDED is the max level. The fold
   manager still works (expand at EXPANDED returns False).

## Files Modified (summary)

| File                             | Changes                                                   |
| -------------------------------- | --------------------------------------------------------- |
| `widgets/bgcmd_list.py`          | Add item types, refactor rendering for parent/child/bgcmd |
| `widgets/changespec_list.py`     | Add `◌` for reverted CLs                                  |
| `widgets/keybinding_footer.py`   | Update AXE footer bindings                                |
| `app.py`                         | Add AXE state, update compose/watchers                    |
| `actions/axe.py`                 | Remove lumberjack cycling, update clear output            |
| `actions/axe_display.py`         | Add `_build_axe_items()`, remove `_update_axe_layout()`   |
| `actions/navigation/_basic.py`   | Use `current_idx` for AXE, save/restore position          |
| `actions/agents/_folding.py`     | Add h/l fold for AXE tab                                  |
| `actions/agents/_interaction.py` | Remove Ctrl+N/P for AXE                                   |
| `actions/changespec.py`          | Update `.` toggle for AXE                                 |
| `actions/event_handlers.py`      | Update selection handler                                  |

## Verification

1. `just install && just lint` — ensure no type errors
2. `just test` — run existing tests
3. Manual testing with `sase ace --agent`:
   - Switch to AXE tab, verify side panel always visible with "sase axe" entry
   - Press `l` to expand lumberjacks, verify nested entries appear
   - Press `h` to collapse, verify they hide
   - j/k navigates through all entries
   - `.` hides/shows bgcmd entries with `◌` indicator
   - Switch to CLs tab, press `.` to show reverted CLs, verify `◌` appears

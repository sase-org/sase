---
create_time: 2026-03-30 18:00:03
status: done
prompt: sdd/prompts/202603/move_pinned_panel.md
---

# Plan: Move Pinned Panel to Left Side & Focus-Only Highlighting

## Goal

Two changes to the Agents tab in `sase ace` TUI:

1. **Move the Pinned panel** from the right side (below `agent-detail-container`) to the left side (below
   `agent-list-container`, i.e. below the main agent list).
2. **Only the focused panel shows a highlighted entry** — the unfocused panel should have no visible highlight/cursor.

## Current Layout

```
agents-view (Vertical)
├── AgentInfoPanel
└── agents-content (Horizontal)
    ├── agent-list-container (Vertical)     ← LEFT SIDE
    │   └── AgentList (main)
    └── agent-detail-container (Vertical)   ← RIGHT SIDE
        ├── AgentDetail
        └── pinned-panel-container (Vertical)
            └── AgentList (pinned)
```

## Target Layout

```
agents-view (Vertical)
├── AgentInfoPanel
└── agents-content (Horizontal)
    ├── agent-list-container (Vertical)     ← LEFT SIDE
    │   ├── AgentList (main)
    │   └── pinned-panel-container (Vertical)
    │       └── AgentList (pinned)
    └── agent-detail-container (Vertical)   ← RIGHT SIDE
        └── AgentDetail
```

## Changes

### 1. Layout: Move pinned panel (`app.py`)

In `compose()`, move the `pinned-panel-container` block from inside `agent-detail-container` to inside
`agent-list-container`, after the main `AgentList`.

**File**: `src/sase/ace/tui/app.py` (~lines 410-415)

Before:

```python
with Vertical(id="agent-list-container"):
    yield AgentList(id="agent-list-panel")
with Vertical(id="agent-detail-container"):
    yield AgentDetail(id="agent-detail-panel")
    with Vertical(id="pinned-panel-container"):
        yield AgentList(panel="pinned", id="pinned-list-panel")
```

After:

```python
with Vertical(id="agent-list-container"):
    yield AgentList(id="agent-list-panel")
    with Vertical(id="pinned-panel-container"):
        yield AgentList(panel="pinned", id="pinned-list-panel")
with Vertical(id="agent-detail-container"):
    yield AgentDetail(id="agent-detail-panel")
```

### 2. CSS: Adjust sizing (`styles.tcss`)

- The main `#agent-list-panel` needs `height: 1fr` so it shares vertical space with the pinned panel (already the case).
- The `#pinned-panel-container` CSS comment should be updated from "bottom-right" to "bottom-left" (minor).
- No other CSS changes needed — the pinned panel already has `height: auto; max-height: 12` which will work correctly in
  the left column.

### 3. Focus-only highlighting (`_core.py` and `agent_list.py`)

**Problem**: Currently, when `list_changed=True`, both panels call `update_list()` which sets
`self.highlighted = current_idx` on both panels. The unfocused panel retains its highlight visually.

**Solution**: Two complementary changes:

#### 3a. `AgentList.update_list()` — accept a `has_focus` parameter

Add an `has_focus: bool = True` parameter. When `has_focus=False`:

- Skip setting `self.highlighted = current_idx` at the end (or set it to `None`)
- Pass `is_selected=False` for all entries (so no bold name styling)

#### 3b. `_refresh_agents_display()` — pass focus state to each panel

When calling `agent_list.update_list()` and `pinned_list.update_list()`, pass
`has_focus=(self._pinned_panel_focused == "main")` and `has_focus=(self._pinned_panel_focused == "pinned")`
respectively.

#### 3c. `_refresh_agents_display()` — clear highlight on unfocused panel during navigation

In the `else` branch (navigation-only, `list_changed=False`), after updating the focused panel's highlight, explicitly
clear the unfocused panel's highlight by setting `highlighted = None`.

#### 3d. `_refresh_agents_display_debounced()` — same treatment

The debounced path also needs to clear the unfocused panel's highlight when updating the focused one.

### 4. Width calculation for pinned panel

The `AgentList.WidthChanged` message is posted by both panels. The handler that resizes `agent-list-container` should
account for the pinned panel's width too (take the max of main and pinned widths). Check `_on_agent_list_width_changed`
or equivalent handler to ensure this works correctly now that both panels are in the same container.

## Files to Modify

| File                                       | Change                                       |
| ------------------------------------------ | -------------------------------------------- |
| `src/sase/ace/tui/app.py`                  | Move pinned panel in `compose()`             |
| `src/sase/ace/tui/styles.tcss`             | Update comment                               |
| `src/sase/ace/tui/widgets/agent_list.py`   | Add `has_focus` param to `update_list()`     |
| `src/sase/ace/tui/actions/agents/_core.py` | Pass focus state, clear unfocused highlights |

## Verification

Run `just install && .venv/bin/sase ace --agent --keys tab` and visually inspect JSON output to confirm:

- Pinned panel is inside `agent-list-container`
- Only the focused panel has a highlighted entry

---
create_time: 2026-03-30 16:23:04
status: done
---

# Pinned Agents Panel — Implementation Plan

## Problem

Pinned agents (toggled via `P`) currently live inline in the main agent list. As the list grows with active and
completed agents, pinned entries — which represent deliberately saved reference points — get lost in the noise. They
deserve their own dedicated space.

## Design

### Layout

The agents tab right column (`agent-detail-container`) gains a new bottom panel:

```
┌──────────────────┬──────────────────────────────┐
│                  │  AgentDetail (prompt + file)  │
│   AgentList      │  ┌────────────────────────┐   │
│   (main list)    │  │ prompt  (30%)          │   │
│                  │  ├────────────────────────┤   │
│   • running      │  │ file/thinking (70%)    │   │
│   • done ✗       │  │                        │   │
│                  │  └────────────────────────┘   │
│                  ├──────────────────────────────┤
│                  │  📌 Pinned (3)                │
│                  │  ► agent-a (DONE) ✓           │
│                  │    agent-b (FAILED) ✗         │
│                  │    agent-c (DONE) ✓           │
│                  └──────────────────────────────┘
└──────────────────┴──────────────────────────────┘
```

### Behavior

**Filtering**: Pinned agents are _moved_ out of the main agent list and into the pinned panel. The main list no longer
shows pinned agents — this keeps the list focused on active work.

**Focus model**: Two navigable zones on the agents tab: the main agent list (default) and the pinned agents panel. `J`
toggles focus between them:

- **Main list focused** (default): `j`/`k` navigate the main list, detail panel shows selected agent. `J` moves focus to
  pinned panel (if it has entries).
- **Pinned panel focused**: `j`/`k` navigate within pinned entries, detail panel shows selected pinned agent. `J`
  returns focus to main list. A visual indicator (border color change) shows which zone has focus.

**Panel visibility**: Hidden when no pinned agents exist. Appears automatically when the first agent is pinned. The
detail panel (above) shrinks slightly to accommodate it.

**Actions while pinned panel has focus**: Most agent actions work on the selected pinned agent: `P` unpins (moves agent
back to main list), `x` dismisses, `]`/`[` cycle panel mode, `E` opens editor, `Enter` jumps to CL, etc.

### Visual Design

- **Border**: Gold (`#FFD700`) solid border — matches the 📌 pin icon color, distinct from the green/purple/secondary
  borders of other panels
- **Border title**: `"📌 Pinned (N)"` where N is the count
- **Focus indicator**: When focused, border becomes `double` style (thick); when unfocused, `solid` (thin). This matches
  how Textual focus conventions work.
- **Entry format**: Compact single-line entries matching the main agent list style (reuse `_format_agent_option` from
  `agent_list.py`)
- **Max height**: `max-height: 10` — caps the panel at ~10 entries visible, scrollable beyond that. This prevents pinned
  entries from overwhelming the detail panel.

## Implementation

### Phase 1: New widget + layout

**New file `src/sase/ace/tui/widgets/pinned_agents_panel.py`**:

- `PinnedAgentsPanel(OptionList)` widget — similar structure to `AgentList` but simpler
- `update_list(agents, current_idx, focused)` — rebuilds the option list
- `update_highlight(idx)` — moves highlight without rebuild
- Reuses `_format_agent_option`-style rendering from `agent_list.py` (import shared helpers)
- Emits `SelectionChanged` message when user clicks an entry

**Modify `app.py` compose()**:

- Add `PinnedAgentsPanel` inside `agent-detail-container`, after `AgentDetail`
- New widget ID: `pinned-agents-panel`

**Add CSS in `styles.tcss`**:

- `#pinned-agents-panel`: `height: auto; max-height: 10; border: solid #FFD700; padding: 0 1;`
- `#pinned-agents-panel.hidden`: `display: none;`
- `#pinned-agents-panel.focused-panel`: `border: double #FFD700;` (when this panel has focus)
- `#agent-list-panel.unfocused-panel`: `border: solid $secondary;` (dim when pinned has focus)

### Phase 2: Data flow — filter pinned out of main list

**Modify `_core.py` `_load_agents()`**:

- After building `self._agents`, partition into unpinned (stays in `self._agents`) and pinned (stored in new
  `self._pinned_agent_objects: list[Agent]`)
- Pinned agents are those whose identity is in `self._pinned_agents` AND status is in `DISMISSABLE_STATUSES` (only
  completed agents can be pinned, matching existing invariant)
- Update tab bar count logic to include pinned agents in the done count

**Modify `_refresh_agents_display()`**:

- Also update the pinned panel:
  `pinned_panel.update_list(self._pinned_agent_objects, self._pinned_panel_idx, focused=self._pinned_panel_focused)`
- Show/hide pinned panel based on whether `self._pinned_agent_objects` is non-empty

### Phase 3: Navigation — J toggle + j/k routing

**New app state**:

- `_pinned_panel_focused: bool = False` — whether pinned panel has focus
- `_pinned_panel_idx: int = 0` — current selection in pinned panel

**New keymap entry**:

- Add `focus_pinned_panel: "J"` to `AppKeymaps` and `_BINDING_META`
- Add to `default_config.yml`

**New action `action_focus_pinned_panel()`** (in `_interaction.py` or new mixin):

- If not on agents tab: return
- Toggle `_pinned_panel_focused`
- If toggling ON: validate pinned panel has entries; update visual focus indicators
- If toggling OFF: restore main list focus indicators
- Refresh display to reflect focus change

**Modify `action_next_changespec` / `action_prev_changespec`** (in `_basic.py`):

- When on agents tab AND `_pinned_panel_focused`: navigate `_pinned_panel_idx` within `self._pinned_agent_objects`
  instead of `current_idx` within `self._agents`
- Trigger detail panel update for the selected pinned agent

**Modify `_refresh_agents_display_debounced()`**:

- When pinned panel focused: update pinned panel highlight instead of main list highlight

### Phase 4: Detail panel integration

**Modify `_apply_agent_detail_update()`**:

- When `_pinned_panel_focused`: use `self._pinned_agent_objects[self._pinned_panel_idx]` as the current agent for the
  detail panel instead of `self._agents[self.current_idx]`

**Modify `_update_agents_info_panel()`**:

- When pinned panel focused: show "Pinned: X/Y" instead of "Agent: X/Y"

### Phase 5: Agent actions on pinned entries

**Modify action guards in `_interaction.py`**:

- Actions that operate on "the selected agent" need to resolve through a helper: `_get_selected_agent() -> Agent | None`
  that checks `_pinned_panel_focused` and returns from either `_agents[current_idx]` or
  `_pinned_agent_objects[_pinned_panel_idx]`
- Affected actions: `action_pin_agent`, `action_kill_agent`, `action_toggle_thinking`, `action_edit_panel`,
  `action_next_agent_file`, `action_prev_agent_file`, `action_toggle_layout`, `action_jump_to_agent_changespec`,
  `action_show_diff`, `action_edit_spec`, `action_open_tmux`
- `action_pin_agent` when in pinned panel: unpin moves the agent back to main list and refreshes both panels

### Phase 6: Footer + help updates

**Modify footer**:

- `_compute_agent_bindings()`: add `J` → "pinned" / "agents" toggle binding (conditional: only show when pinned agents
  exist or panel is focused)
- When pinned panel focused: adjust footer to show pinned-relevant actions

**Modify help modal**:

- Add `J` to the agents tab keybindings section

### Phase 7: Pinned panel unfocus on tab switch

**Modify `watch_current_tab()`**:

- When leaving agents tab: reset `_pinned_panel_focused = False` and clear visual indicators
- This prevents returning to agents tab in a confusing state

## Files to Modify

| File                                              | Change                                                     |
| ------------------------------------------------- | ---------------------------------------------------------- |
| `src/sase/ace/tui/widgets/pinned_agents_panel.py` | **NEW** — PinnedAgentsPanel widget                         |
| `src/sase/ace/tui/widgets/__init__.py`            | Export PinnedAgentsPanel                                   |
| `src/sase/ace/tui/app.py`                         | Add PinnedAgentsPanel to compose(), add state vars         |
| `src/sase/ace/tui/styles.tcss`                    | CSS for pinned panel                                       |
| `src/sase/ace/tui/actions/agents/_core.py`        | Filter pinned from main list, update refresh               |
| `src/sase/ace/tui/actions/agents/_interaction.py` | Add \_get_selected_agent helper, action_focus_pinned_panel |
| `src/sase/ace/tui/actions/navigation/_basic.py`   | Route j/k through pinned panel when focused                |
| `src/sase/ace/tui/widgets/keybinding_footer.py`   | Add J binding, adjust agent bindings                       |
| `src/sase/ace/tui/keymaps/types.py`               | Add focus_pinned_panel to AppKeymaps + \_BINDING_META      |
| `src/sase/default_config.yml`                     | Add focus_pinned_panel: "J"                                |
| `src/sase/ace/tui/modals/help_modal.py`           | Document J keymap                                          |

## Edge Cases

- **No pinned agents**: `J` does nothing (or shows brief notification). Panel stays hidden.
- **Unpin last entry**: Panel auto-hides, focus returns to main list.
- **Pin from main list**: Agent moves to pinned panel. If pinned panel was hidden, it appears. Main list selection
  adjusts (stays on same-position or moves up if at end).
- **Auto-refresh**: When agents are reloaded on timer, pinned panel entries update their status (though pinned agents
  are always completed, so this is mostly a no-op).
- **Agent dismissed from pinned panel**: Removed from both pinned set and panel. Panel auto-hides if last entry.
- **Tab switch**: Leaving agents tab resets pinned panel focus to unfocused.

---
create_time: 2026-03-30 14:43:39
status: done
---

# Pinned Agents Panel

## Problem

Pinned agents currently live inline in the main agent list, distinguished only by a 📌 icon. This creates two issues:

1. **Discoverability** — Pinned agents get lost among active/completed agents, especially when the list is long.
2. **Ergonomics** — There's no quick way to browse your pinned collection without scrolling through the full list.

## Design

Add a **dedicated "Pinned" panel** below the agent detail panel (bottom-right quadrant of the Agents tab). The user
navigates between the detail area and the pinned panel using `J` (shift-j).

### Layout (Agents Tab — After)

```
┌─────────────────────────────────────────────────────────────────┐
│ AgentInfoPanel                                                  │
├──────────────────┬──────────────────────────────────────────────┤
│                  │  ┌────────────────────────────────────────┐  │
│                  │  │ Agent Detail (prompt/file/thinking)    │  │
│   Agent List     │  │                                        │  │
│   (unpinned +    │  │                                        │  │
│    active only)  │  ├────────────────────────────────────────┤  │
│                  │  │ 📌 Pinned Agents (2)                   │  │
│                  │  │  ✘ [agent] my_cl (DONE)                │  │
│                  │  │  ✘ [workflow] deploy (DONE)            │  │
│                  │  └────────────────────────────────────────┘  │
└──────────────────┴──────────────────────────────────────────────┘
```

### Key Behaviors

- **`J` toggles focus** between the detail area and the pinned panel. When the pinned panel is focused, `j`/`k` navigate
  within it, the detail panels update to show the selected pinned agent, and footer bindings reflect the pinned agent's
  available actions.
- **`K` also toggles focus** (same as `J` — symmetric pair for moving up/down between the two right-side regions).
- **Pinned agents are removed from the main list** — they only appear in the pinned panel. This prevents duplication and
  keeps the main list focused on active work.
- **Pinning an active agent** doesn't move it immediately — it stays in the main list until it reaches a dismissable
  status (DONE, FAILED, PLAN DONE), at which point it appears in the pinned panel instead of the main list.
- **The pinned panel auto-hides** when there are no pinned agents to display, giving the full vertical space back to the
  detail panels (same pattern as `AncestorsChildrenPanel` which hides via `self.display = False`).
- **Unpinning from the pinned panel** (`P`) moves the agent back to the main list (it becomes a regular completed agent
  visible in the main list again).
- **Selecting a pinned agent** shows its full detail (prompt, file, thinking) in the detail panels above — exactly the
  same experience as selecting from the main list.

### Visual Design

- **Border**: `solid #FFD700` (gold) — matches the existing pin icon color, immediately conveys "pinned".
- **Title**: `📌 Pinned (N)` as the border title, where N is the count.
- **Entries**: Same rendering as the main agent list (status colors, icons, type indicators) but without the pin icon
  itself (redundant in a dedicated pinned panel).
- **Height**: `auto` with `max-height: 12` — grows with content, caps to avoid overwhelming the detail panels.
- **Focus indicator**: When focused, the border brightens or changes to a highlighted style. When unfocused, it uses a
  dimmer gold border.

## Implementation Plan

### Phase 1: PinnedAgentList Widget

**New file: `src/sase/ace/tui/widgets/pinned_agent_list.py`**

Create a `PinnedAgentList` widget (extending `Static`, similar to `AncestorsChildrenPanel`):

- Accepts a list of pinned `Agent` objects and renders them using Rich `Text` with the same color scheme as
  `AgentList._format_agent_option()`.
- Tracks `_selected_idx` internally for j/k navigation within the panel.
- Highlights the selected entry with the `$accent` background color.
- Emits a `SelectionChanged(agent)` message when selection changes.
- Auto-hides (`self.display = False`) when the pinned list is empty.
- Renders a counter in the border title: `📌 Pinned (N)`.

### Phase 2: Layout Integration

**Modify: `src/sase/ace/tui/app.py`** — Update `compose()`:

```python
# Agents Tab
with Vertical(id="agents-view", classes="hidden"):
    yield AgentInfoPanel(id="agent-info-panel")
    with Horizontal(id="agents-content"):
        with Vertical(id="agent-list-container"):
            yield AgentList(id="agent-list-panel")
        with Vertical(id="agent-detail-container"):
            yield AgentDetail(id="agent-detail-panel")
            yield PinnedAgentList(id="pinned-agent-list")  # NEW
```

**Modify: `src/sase/ace/tui/styles.tcss`** — Add CSS:

```css
#pinned-agent-list {
  height: auto;
  max-height: 12;
  border: solid #ffd700;
  padding: 0 1;
  scrollbar-gutter: stable;
}

#pinned-agent-list.focused {
  border: solid #ffdf4d; /* Brighter gold when focused */
}
```

### Phase 3: Agent List Filtering

**Modify: `src/sase/ace/tui/actions/agents/_core.py`** — In `_load_agents()`:

- After building the filtered `self._agents` list, separate out pinned agents that are in a dismissable status. These go
  into a new `self._pinned_agent_objects` list.
- Remove those pinned-and-dismissed agents from `self._agents` so they don't appear in the main list.
- Pinned agents that are still active (RUNNING, WAITING, etc.) remain in `self._agents` — they only move to the pinned
  panel upon completion.

### Phase 4: Focus State & Navigation

**Modify: `src/sase/ace/tui/actions/agents/_core.py`** — Add focus tracking:

- New attribute: `_pinned_panel_focused: bool = False` — tracks whether the pinned panel has logical focus.
- When `_pinned_panel_focused` is True, `j`/`k` navigate within the pinned panel instead of the main agent list, and the
  detail panels show the selected pinned agent.

**Modify: `src/sase/ace/tui/actions/navigation/_basic.py`**:

- Update `action_next_changespec()` / `action_prev_changespec()` to check `_pinned_panel_focused` when on agents tab and
  delegate to the pinned panel's internal navigation.

**New keymap: `toggle_pinned_focus`** — Mapped to `J` (and `K` as alias):

- **Modify: `src/sase/ace/tui/keymaps/types.py`** — Add `toggle_pinned_focus` to `AppKeymaps` and `_BINDING_META`.
- **Modify: `src/sase/default_config.yml`** — Add `toggle_pinned_focus: "J"` to the keymaps section.
- **Modify: `src/sase/ace/tui/bindings.py`** — Add Textual binding for `J`.

**New action: `action_toggle_pinned_focus()`**:

- **Modify: `src/sase/ace/tui/actions/agents/_interaction.py`** — Add the action:
  - Toggle `_pinned_panel_focused`.
  - If switching TO pinned panel: update the pinned list's visual highlight, update detail panel with the selected
    pinned agent, update border style to focused, update footer bindings.
  - If switching FROM pinned panel: restore the main agent list's detail view, remove focused border style, update
    footer bindings.
  - No-op (with notification) if there are no pinned agents.

### Phase 5: Detail Panel Integration

**Modify: `src/sase/ace/tui/actions/agents/_core.py`**:

- `_refresh_agents_display()`: When `_pinned_panel_focused`, pass the pinned panel's selected agent to
  `_apply_agent_detail_update()` instead of `self._agents[self.current_idx]`.
- `_refresh_agents_display_debounced()`: Same conditional — debounce detail updates for the pinned panel's selection
  when focused.
- `_update_agents_info_panel()`: Show position within the pinned list when focused (e.g., "Pinned: 1/3").
- Update `PinnedAgentList` whenever `_load_agents()` runs (alongside the main list update).

### Phase 6: Footer & Help Updates

**Modify: `src/sase/ace/tui/widgets/keybinding_footer.py`**:

- `_compute_agent_bindings()`: When `_pinned_panel_focused`, show the `J` key as "main list" (to go back). When not
  focused and pinned agents exist, show `J` as "pinned (N)".
- Pin/unpin action label: When in the pinned panel, `P` shows "unpin" (always, since everything in the panel is pinned).

**Modify: `src/sase/ace/tui/modals/help_modal.py`**:

- Add `J` / `K` to the Agents tab keybinding section: "toggle pinned panel".

### Phase 7: Edge Cases

- **Dismiss-all**: Already excludes pinned agents (line 467 in `_killing.py`). No change needed.
- **Auto-refresh**: When `_load_agents()` fires on the timer, update both the main list and the pinned panel. If the
  focused pinned agent disappears (manually unpinned from disk), fall back to the main list focus.
- **Tab switching**: Save/restore `_pinned_panel_focused` state alongside `_agents_last_idx` when switching tabs.
- **Pinning from main list**: After `action_pin_agent()` succeeds and the agent is dismissable, the refresh cycle moves
  it to the pinned panel. If the user pins the currently selected agent, bump `current_idx` to the next agent (or
  previous if at end).
- **Unpinning from pinned panel**: After `action_pin_agent()` (which toggles), the agent moves back to the main list. If
  the pinned list becomes empty, auto-switch focus back to the main list.
- **Search filter**: Agent search (`/` query) filters the main list only. Pinned agents are always visible in their
  panel regardless of the search query.

## Files Changed

| File                                              | Change                                          |
| ------------------------------------------------- | ----------------------------------------------- |
| `src/sase/ace/tui/widgets/pinned_agent_list.py`   | **NEW** — PinnedAgentList widget                |
| `src/sase/ace/tui/widgets/__init__.py`            | Export PinnedAgentList                          |
| `src/sase/ace/tui/app.py`                         | Add PinnedAgentList to compose()                |
| `src/sase/ace/tui/styles.tcss`                    | CSS for pinned panel                            |
| `src/sase/ace/tui/actions/agents/_core.py`        | Filter pinned agents, update refresh logic      |
| `src/sase/ace/tui/actions/agents/_interaction.py` | action_toggle_pinned_focus(), update pin action |
| `src/sase/ace/tui/actions/navigation/_basic.py`   | Delegate j/k to pinned panel when focused       |
| `src/sase/ace/tui/keymaps/types.py`               | Add toggle_pinned_focus binding metadata        |
| `src/sase/ace/tui/bindings.py`                    | Add J binding                                   |
| `src/sase/default_config.yml`                     | Add toggle_pinned_focus keymap                  |
| `src/sase/ace/tui/widgets/keybinding_footer.py`   | Show J binding conditionally                    |
| `src/sase/ace/tui/modals/help_modal.py`           | Document J keymap                               |

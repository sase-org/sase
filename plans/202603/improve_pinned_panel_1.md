---
create_time: 2026-03-31 12:00:00
status: in_progress
---

# Improve Pinned Panel Visual Design & UX

## Goals

Transform the pinned panel from a functional-but-plain secondary list into a visually polished, intuitively navigable
component that feels like a deliberate "save shelf" for important completed agents.

## Current State

The pinned panel works correctly but has minimal visual identity:

- Solid border that changes from dim purple (#5F5F87) to bright purple (#AF87D7) on focus
- Border title `"📌 Pinned (N)"` in purple
- Pin icon suppressed inside the pinned panel (relies solely on border title for context)
- No visual breathing room between the main list and pinned panel
- Unfocused panel content looks identical to focused panel content
- Color scheme (purple) disconnects from the gold pin icon used in the main list

## Product/UX Design

### 1. Unified Gold/Amber Color Identity

Establish "pinned = gold" as a consistent visual language across the entire feature:

| Element                                 | Focused               | Unfocused            |
| --------------------------------------- | --------------------- | -------------------- |
| Pinned panel border                     | Bright gold (#D4A017) | Muted gold (#8B7536) |
| Pinned panel border title               | Bright gold           | Dim gold             |
| Main panel border (when pinned focused) | Dim (#5F5F87)         | N/A                  |
| Pin icon in main list                   | Gold (#FFD700)        | unchanged            |

This replaces the current purple scheme with a warm amber palette that matches the existing 📌 icon color.

### 2. Focus State Clarity

Make it immediately obvious which panel has keyboard focus:

- **Focused panel**: Bright border, full-opacity content, focus arrow `▸` in border title
- **Unfocused panel**: Dim border, slightly muted content (via CSS `dim` class on the list widget), no focus arrow
- **Main panel gets a border title too**: Show `"▸ Agents"` when focused, `"  Agents"` when unfocused — symmetry makes
  the focus model learnable

### 3. Border Style Differentiation

Use `double` border for the pinned panel vs `solid` for the main list. This gives the pinned panel a heavier, more
"permanent" feel — matching the semantic intent of pinning (these are agents you chose to keep).

### 4. Contextual Border Titles

- **Pinned panel focused**: `"▸ 📌 Pinned (3)"`
- **Pinned panel unfocused**: `"  📌 Pinned (3)"`
- **Main panel focused**: `"▸ Agents"`
- **Main panel unfocused**: `"  Agents"`

The border subtitle on the pinned panel shows `"J switch"` when focused (hinting at the escape hatch), hidden when
unfocused to reduce clutter.

### 5. Visual Separation

Add `margin-top: 1` to the pinned panel container. This one-row gap between the main list and pinned panel provides
breathing room and makes the two panels read as distinct zones rather than a single stacked list.

### 6. Gold Marker in Pinned Panel Entries

Replace the suppressed pin icon logic: in the pinned panel, show a small gold bullet `●` prefix on each entry instead of
the full `📌` icon. This provides a subtle but consistent visual reinforcement that these entries are pinned, even when
the border title isn't visible (e.g., scrolled in a long pinned list).

### 7. Content Dimming on Unfocused Panel

Apply a CSS class (`panel-content-dim`) to the unfocused panel's `AgentList` widget that reduces text brightness. This
is the strongest focus signal — the focused panel's text pops while the unfocused panel recedes.

## Technical Design

### Styling (styles.tcss)

```
#pinned-panel-container:
  - Change border from solid to double
  - Change border colors: dim gold (#8B7536) default, bright gold (#D4A017) when .panel-active
  - Change border-title-color to gold (#D4A017)
  - Add margin-top: 1

#agent-list-panel:
  - Add border-title-align: left and border-title-color
  - Add .panel-inactive styling for both border and content dim

#pinned-list-panel:
  - Add .panel-content-dim class for opacity/color reduction when unfocused

New class: .panel-content-dim on AgentList widgets to dim text in unfocused panel
```

### Display Logic (\_display.py)

`_update_panel_focus_styling()` changes:

- Set border titles on BOTH panels with focus arrow `▸` prefix
- Set border subtitle on pinned panel when focused: `"J switch"`
- Add/remove `panel-content-dim` class on the unfocused panel's list widget
- Clear border subtitle on pinned panel when unfocused

### Agent List (agent_list.py)

`_format_agent_option()` changes:

- In the pinned panel, show a gold `●` prefix instead of suppressing the pin icon entirely
- This replaces the `self._panel != "pinned"` guard with a panel-specific icon

### Minimal Layout Change (app.py)

No structural changes needed — the existing widget composition is sound.

## Reliability / Edge Cases

- **No pinned agents**: Pinned panel hidden via `display = False` (existing behavior). Main panel border title reverts
  to no title (no "▸ Agents" needed when there's only one panel).
- **Single pinned agent**: Panel height auto-sizes to 1 row (existing min-height: 1).
- **All agents pinned**: Main panel may be empty. `J` to switch should still work. Main panel stays visible (it can
  receive new agents at any time).
- **Narrow terminals**: Gold/amber colors maintain readability at any width. Margin-top of 1 row is acceptable even at
  small heights.
- **Border subtitle length**: `"J switch"` is 8 chars — fits comfortably even in narrow panels.

## Test Plan

- Existing `test_pinned_panel.py` tests continue to pass (panel identity, selection events, footer bindings).
- Add tests for:
  - Border title content when focused vs unfocused (both panels)
  - Border subtitle presence on pinned panel when focused
  - CSS class application for content dimming

## Execution Order

1. Update `styles.tcss`: gold colors, double border, margin, dim classes
2. Update `_display.py`: border titles with focus arrows, subtitle, content dim classes
3. Update `agent_list.py`: gold bullet marker in pinned panel entries
4. Update/add tests in `test_pinned_panel.py`
5. Run `just install && just check`

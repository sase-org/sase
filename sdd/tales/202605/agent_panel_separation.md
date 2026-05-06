---
create_time: 2026-05-06 17:22:18
status: done
prompt: sdd/prompts/202605/agent_panel_separation.md
---
# Agent Panel Separation Plan

## Goal

Make stacked panels in the `sase ace` Agents tab read as distinct sections, especially when multiple tagged panels
appear near the bottom of the left column. The fix should improve scanability without making the agent list feel noisy
or reducing the density that makes this view useful.

## Current Shape

- The Agents tab left column is `#agent-list-container`, a vertical stack of `AgentList` widgets.
- Panel membership and ordering are model-owned by `src/sase/ace/tui/models/agent_panels.py`.
- Rendering and dynamic mounting live in `src/sase/ace/tui/actions/agents/_display_panels.py`.
- Each `AgentList` already has a `solid` border and a styled border title, but panels are stacked edge-to-edge. Adjacent
  terminal borders visually compress into a dense horizontal junction.
- Panel heights are manually assigned in `_apply_panel_heights()` using either exact cell heights or fractional weights,
  so any structural spacing must be accounted for in that sizing logic.

## Design Direction

Add a calm, structural break between panels:

- Keep the existing bordered panels and styled titles.
- Add a one-cell top margin to every non-first `AgentList` panel so the boundary becomes visible at terminal scale.
- Style non-first panel titles with the existing tag/count palette; avoid adding another strong color or another
  row-level glyph system.
- Keep the focused panel border accent behavior unchanged, because focus is a separate concept from panel separation.

This is preferable to adding a banner row inside each panel because the problem is between panels, not inside the agent
tree. It also avoids spending an agent row on decoration and preserves row semantics for navigation, jump hints, and
grouping.

## Implementation Steps

1. Update `PanelsMixin._refresh_panel_widgets_impl()` so it marks panel widgets by position:
   - first panel: no separator class
   - subsequent panels: separator class, e.g. `agent-panel-separated`
   - remove stale position classes during refresh so reused panel slots stay correct after tag changes.

2. Update `src/sase/ace/tui/styles.tcss`:
   - add `margin-top: 1` for `#agent-list-container AgentList.agent-panel-separated`
   - keep the base `AgentList` border/padding/focus styles intact.

3. Adjust `_apply_panel_heights()` so its natural-height calculation includes the separator margin for non-first panels:
   - each non-first panel costs one extra row in both Fits and Overflow decisions.
   - cell-height assignments should continue to use the widget's content/border height; the margin is owned by
     CSS/layout.
   - the total fit calculation should subtract or include separator rows so panels do not overflow unexpectedly when the
     natural content just fits.

4. Add focused tests:
   - verify `_refresh_panel_widgets()` adds the separator class to panel indices `>= 1` and removes it from index `0`.
   - verify the Fits/Overflow height regime accounts for separator rows when deciding whether a panel stack fits the
     container.

5. Verify:
   - run the targeted panel tests first.
   - run `just install` if needed, then `just check` before reporting back, per repo memory.

## Risks And Mitigations

- Risk: adding a row of spacing slightly reduces visible list density. Mitigation: apply only between panels, never
  inside a panel; single-panel views are unchanged.

- Risk: dynamic height tests assume only content rows plus borders. Mitigation: make separator cost explicit in
  `_apply_panel_heights()` and add tests around the fit boundary.

- Risk: slot reuse can leave a separator class on the first panel when panel ordering changes. Mitigation: set/remove
  classes for every ordered widget on every refresh.

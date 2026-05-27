---
create_time: 2026-05-27 12:56:17
status: done
prompt: sdd/prompts/202605/agent_panel_gold_highlight.md
---
# Agents Panel Gold Border Highlight Plan

## Context

The Agents tab renders one dynamic `AgentList` panel per effective tag bucket through
`PanelRefreshMixin._refresh_panel_widgets`. Panel membership and selection are already tracked by
`AgentPanelGroup.focused_idx` and `current_idx`; full rebuilds and j/k highlight-only refreshes both apply the
`-focused-panel` class to the panel that owns the current selection and remove it from stale panels.

Today that class uses `$accent`, so the selected-agent panel is not visually gold. The requested behavior can stay
presentation-only in the Python/TUI repo; it does not cross the Rust core boundary.

## Goals

- Make the dynamic Agents-tab panel containing the currently selected agent show a gold border.
- Keep highlight updates cheap on j/k navigation by reusing the existing class toggling and `AgentPanelIndex` lookup
  path.
- Preserve the existing row-level selection highlight and panel title content.
- Cover both full panel rebuilds and focused-panel/highlight-only refreshes in tests.

## Proposed Changes

1. Update the Agents-tab CSS rule for `#agent-list-container AgentList.-focused-panel` to use the established gold color
   used elsewhere in the TUI (`#FFD700`) instead of `$accent`.

2. Add or adjust focused-panel unit coverage in the existing Agents panel tests:
   - assert that `_refresh_panel_widgets` applies `-focused-panel` only to the panel whose key matches
     `AgentPanelGroup.focused_key`;
   - retain existing coverage that `_refresh_panel_highlights_impl` and optimized panel switching clear stale panel
     classes.

3. Run focused tests first:
   - `pytest tests/ace/tui/test_agent_panels_display.py tests/ace/tui/test_agent_panel_first_selection.py`

4. Run visual snapshot coverage for the Agents tab. Because the border color change is intentional and visible, update
   the affected PNG goldens after inspecting the diff:
   - `pytest -m visual tests/ace/tui/visual/test_ace_png_snapshots.py`
   - if only the selected panel border color changed, rerun with `--sase-update-visual-snapshots` for the affected
     snapshots.

5. Run the repository check required after changes:
   - `just install`
   - `just check`

## Risks And Mitigations

- Visual snapshot failures are expected because border pixels change from accent to gold. Mitigation: inspect
  `.pytest_cache/sase-visual/` before accepting snapshot updates.
- If Textual theme variables differ across terminals, hard-coding `#FFD700` is still consistent with existing gold UI
  accents and avoids ambiguity around `$warning`.
- The change should not affect navigation latency because it does not add list scans or change the j/k refresh path.

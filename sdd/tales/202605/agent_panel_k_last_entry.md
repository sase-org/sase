---
create_time: 2026-05-06 17:34:33
status: done
prompt: sdd/prompts/202605/agent_panel_k_last_entry.md
---
# Plan: Make K Land On The Last Agent-Panel Entry

## Context

The Agents tab has tag-driven side panels. The default keymaps are:

- `J` -> `focus_next_agent_panel`
- `K` -> `focus_prev_agent_panel`

Both actions currently route through `AgentPanelsMixin._change_focused_agent_panel(forward=...)`. After moving panel
focus, that helper reads `_panel_navigation_stops()` for the newly focused panel and lands on `stops[0]`. Those stops
mirror rendered selectable order and include:

- `("agent", global_idx)` for visible agent rows
- `("banner", group_key)` for collapsed group banners

The recently-added behavior should remain for `J`: when cycling forward to the next panel, land on the first rendered
selectable entry in that panel. The requested change is only for `K`: when cycling backward to the previous panel, land
on the last entry in that newly focused panel.

I will interpret "last entry on that agent panel" as the last rendered selectable stop, not the last raw `_agents`
member. That keeps `K` symmetric with the render-order behavior that was approved for `J`, and it preserves collapsed
banner semantics.

## Proposed Implementation

1. Keep the existing keymap configuration unchanged.
   - `src/sase/default_config.yml`, `src/sase/ace/tui/bindings.py`, and the help modal already map/document `J / K` as
     panel focus cycling.
   - The action names do not change, so this is a behavioral refinement rather than a keymap change.

2. Refactor the panel-landing code in `src/sase/ace/tui/actions/agents/_panels.py`.
   - Extract the duplicated stop-application logic into a small helper, for example `_focus_panel_navigation_stop(...)`.
   - The helper should preserve current behavior for both stop kinds:
     - Agent stop: clear `_current_group_key` and assign `current_idx` to the stop's global index.
     - Banner stop: assign `_current_group_key` and use `_first_agent_idx_for_focused_group(...)` to anchor
       `current_idx` to a real backing agent for detail/actions.

3. Change `_change_focused_agent_panel(forward=...)` to choose the landing stop by direction.
   - `forward=True` (`J`): select `stops[0]`, preserving current behavior.
   - `forward=False` (`K`): select `stops[-1]`, implementing the requested last-entry behavior.
   - Leave the existing no-stops fallback in place. It should still clear banner focus and snap to the focused panel by
     the existing `_snap_current_idx_to_focused_panel(...)` helper.

4. Update docstrings/comments.
   - `_change_focused_agent_panel` should describe direction-specific landing:
     - next panel -> first rendered selectable row
     - previous panel -> last rendered selectable row
   - Avoid changing user-visible help unless a more specific description is needed; current help says `J / K` cycles
     focus across tag panels, which remains true.

## Test Plan

1. Update `tests/ace/tui/test_agent_panel_first_selection.py`.
   - Keep the `J` regression proving forward panel switching selects the first rendered entry.
   - Change the `K` regression to prove backward panel switching selects the last rendered entry in the destination
     panel.
   - Use agent ordering where raw order and rendered order differ, so the test fails if the code falls back to raw
     `_agents` order.

2. Add or update collapsed-banner coverage for `K`.
   - Construct a destination panel whose last rendered selectable stop is a collapsed group banner.
   - Assert that `K` focuses that banner (`_current_group_key` is set) and anchors `current_idx` to a real agent covered
     by the banner.
   - Keep the existing `J` collapsed-banner test for first-entry behavior.

3. Run focused verification:
   - `.venv/bin/python -m pytest tests/ace/tui/test_agent_panel_first_selection.py`

4. Run nearby TUI navigation/grouping coverage.
   - At minimum include the existing agents grouping/navigation tests that cover rendered stops and collapsed banners.

5. Run repo-required verification after code changes:
   - `just install` if the workspace virtualenv is stale.
   - `just check` before final response.

## Risks And Edge Cases

- If a destination panel has no selectable stops, the existing fallback should remain unchanged. This is unlikely for a
  real tag panel with agents, but keeping the fallback avoids introducing lifecycle issues.
- A collapsed banner selected as the last stop must still leave `current_idx` valid because detail rendering and actions
  expect a backing agent. Reusing `_first_agent_idx_for_focused_group(...)` keeps this aligned with the existing `J`
  banner behavior.
- The `_panel_navigation_stops()` cache is keyed by focused panel index and fold state, so reading `stops[-1]` after
  `focus_prev()` should use the newly focused panel's cached-or-rebuilt stop list correctly.

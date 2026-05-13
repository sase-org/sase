---
create_time: 2026-05-13 16:03:05
status: done
prompt: sdd/prompts/202605/agent_panel_highlight_reset.md
---
# Stop stale row highlight after dynamic agent panel switches

## Problem

On the Agents tab, switching between dynamic/tag-driven agent panels via `J`/`K` uses the optimized
`_refresh_focused_agent_panel()` path instead of rebuilding every `AgentList`. That path updates the newly focused
panel's row highlight and focused-panel class, but the previously focused panel only loses the `-focused-panel` class.
Its underlying Textual `OptionList.highlighted` value can remain set to the last selected row, so the old panel still
looks row-selected. When the old panel is the last dynamic panel, this makes it ambiguous which panel is currently
active.

## Relevant code

- `src/sase/ace/tui/actions/agents/_panel_navigation.py`
  - `_change_focused_agent_panel()` computes `old_focused_idx`, updates `current_idx`, then calls
    `_refresh_focused_agent_panel(old_focused_idx=...)`.
- `src/sase/ace/tui/actions/agents/_display_panel_refresh.py`
  - `_refresh_focused_agent_panel_impl()` refreshes only the old and new panel widgets.
  - `_refresh_panel_highlights_impl()` refreshes only the current focused widget and toggles focused classes across
    widgets.
- `src/sase/ace/tui/widgets/agent_list.py`
  - `AgentList.update_highlight()` assigns `highlighted` programmatically and suppresses selection-change messages
    through `_programmatic_update`.

## Approach

1. Add an explicit `AgentList.clear_highlight()` helper.
   - It should set `highlighted = None` under the same programmatic-update guard used by `update_highlight()`.
   - It should not scroll, because clearing an inactive panel should not move any viewport.
   - It should leave `_programmatic_update` false in a `finally` block.

2. Use that helper whenever a panel becomes inactive in the optimized refresh path.
   - In `_refresh_focused_agent_panel_impl()`, after removing `-focused-panel` from `old_focused_idx`, clear that
     widget's highlight.
   - In `_refresh_panel_highlights_impl()`, clear highlights on every non-focused `AgentList` while removing
     `-focused-panel`, so any other highlight-only refresh path cannot leave stale row state.

3. Keep current full rebuild behavior unchanged.
   - `_refresh_panel_widgets_impl()` already passes `local_idx = -1` for inactive panels, so inactive panel rows are
     rendered without selected row styling on rebuild.
   - The change should only address retained `OptionList.highlighted` state in reused widgets.

4. Add focused regression coverage.
   - Extend an existing agent panel refresh/navigation test harness with `highlighted`, `clear_highlight()`, and
     `update_highlight()` tracking.
   - Verify switching from one dynamic panel to another clears the old panel's highlighted row and sets the new panel as
     focused.
   - Verify the broader `_refresh_panel_highlights_impl()` path clears non-focused panel highlights.

5. Run targeted tests first, then the repository check.
   - Targeted tests around agent panel refresh/navigation.
   - Because code files will change in this repo, run `just check` before reporting completion, per repo instructions.
     If dependencies are missing, run `just install` first as instructed by memory.

## Risks

- Clearing `highlighted` could post selection-change events if done without the programmatic guard; the helper avoids
  that by matching existing `update_highlight()` behavior.
- Some Textual versions may treat `None` as no highlighted row; this matches the widget's existing type usage in tests
  and Textual's `highlighted` annotation.
- Clearing only visual highlight, not `current_idx`, preserves the app-level selection semantics for detail panels and
  actions.

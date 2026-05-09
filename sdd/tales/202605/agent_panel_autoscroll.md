---
create_time: 2026-05-09 15:55:04
status: done
prompt: sdd/prompts/202605/agent_panel_autoscroll.md
---
# Plan: Agent Panel Auto-Scroll

## Goal

Make the dynamic agent list panels on the left side of the `sase ace` Agents tab keep the selected row visible during
j/k navigation. In particular, when pressing `j` moves selection to an agent row that is currently below the visible
portion of the focused `AgentList` panel, the panel should scroll down immediately so the highlighted row is visible.
The same behavior should apply symmetrically for `k`, collapsed banner stops, and full list rebuilds that restore a
selection into a scrolled panel.

## Current Behavior

The Agents tab does not use Textual's built-in `OptionList.action_cursor_down` / `action_cursor_up` for j/k. Instead,
`BasicNavigationMixin._navigate_agents_panel()` updates app selection state (`current_idx` or `_current_group_key`) and
the Agents display path calls `AgentList.update_highlight()` to assign `self.highlighted` programmatically.

`AgentList.watch_highlighted()` intentionally suppresses Textual's base `OptionList.watch_highlighted()` while
`_programmatic_update` is true. That suppression is correct because it avoids queued `OptionHighlighted` messages that
can race and overwrite app selection state. However, Textual's base watcher is also where
`OptionList.scroll_to_highlight()` is normally called. Because the watcher is skipped, the visual highlight can move to
an offscreen row while the list panel's scroll offset remains unchanged.

## Design

1. Keep the existing `_programmatic_update` suppression behavior. It protects against a known selection-drift bug and
   should not be relaxed.

2. Add a small `AgentList` helper that sets `highlighted` under `_programmatic_update` and then explicitly calls
   `scroll_to_highlight()` for the selected row. This mirrors the useful part of Textual's base watcher without posting
   an `OptionHighlighted` message.

3. Use that helper in every programmatic AgentList highlight path:
   - `AgentList.update_highlight()` when selecting a collapsed banner row.
   - `AgentList.update_highlight()` when selecting an agent row.
   - the full `build_list()` path after it computes `highlighted_row`.

4. Do not change j/k stop computation, focused-panel selection, grouping/folding semantics, or detail-panel refresh
   behavior. The navigation model is already correct; only the widget scroll reconciliation is missing.

5. Keep scrolling immediate and non-animated, matching Textual's `OptionList.scroll_to_highlight()` default and
   preserving the fast j/k feel.

## Tests

Add focused regression tests around `AgentList` rather than broad TUI snapshot tests:

- Verify `update_highlight()` calls `scroll_to_highlight()` when moving to an agent row.
- Verify `update_highlight(group_key=...)` calls `scroll_to_highlight()` when moving to a collapsed banner row.
- Verify `update_list()` / full rebuild calls `scroll_to_highlight()` after assigning the selected row.
- Verify the programmatic message suppression contract still holds: no `OptionHighlighted` message is posted by these
  programmatic highlight updates, and `_programmatic_update` is false on return.

Run the relevant focused tests first, then run `just check` after implementation as required by the repo instructions.

## Risks

- Calling `scroll_to_highlight()` on an unmounted widget is safe in Textual; it returns without scrolling. This keeps
  unit tests and pre-mount refreshes stable.
- A helper that scrolls while `_programmatic_update` is true must not delegate to the base watcher. It should call
  `scroll_to_highlight()` directly.
- The same suppression pattern exists in `ChangeSpecList`, but this request is specifically about dynamic agent panels.
  Avoid broadening scope unless tests reveal shared breakage that blocks the Agents fix.

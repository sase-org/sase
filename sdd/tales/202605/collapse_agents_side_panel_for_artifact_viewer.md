---
create_time: 2026-05-09 03:19:28
status: done
prompt: sdd/prompts/202605/collapse_agents_side_panel_for_artifact_viewer.md
---
# Collapse Agents Side Panel While Artifact Viewer Is Visible

## Goal

When the user opens an agent artifact from the `sase ace` Agents tab inside a tmux pane, the TUI should shift focus to
the selected agent's artifact by collapsing the Agents side panel. While that artifact viewer pane is still visible,
actions that would navigate to a different agent row should be disabled and explain the constraint with a toast. Closing
the artifact viewer should restore the normal Agents panel.

## Product Behavior

- Opening agent artifacts with `A` in a tmux session should keep the current agent selected, launch the artifact viewer
  pane as it does today, and collapse the Agents side panel so the detail area fills the Agents tab.
- Pressing `A` again while the tracked artifact viewer pane is live should keep the existing toggle behavior: close that
  pane and restore the side panel.
- If the tracked pane was closed externally, the next relevant interaction should detect that the pane is gone, clear
  the tracked pane id, restore the side panel, and proceed normally.
- Navigation that would change the current agent selection should be blocked while the tracked artifact viewer pane is
  visible. This includes `j`/`k`, mouse/list selection messages, panel-focus cycling (`J`/`K`), and Agents-tab jump-mode
  entry/jump selection.
- Current-agent actions that do not change selected agent should remain available, including artifact close/open toggle,
  scrolling/detail actions, file cycling, copying, editing, approval/kill flows, and tab switching.
- The toast should be short and actionable, e.g. `Close the artifact viewer before switching agents`.

## Technical Design

- Use the existing `_artifact_tmux_pane_id` state as the source of truth for whether this behavior can apply. Add a
  small helper on `AgentPanelsMixin` that:
  - returns false when there is no tracked pane id or the app is not in tmux;
  - calls `artifact_tmux_pane_exists(pane_id)` when a pane is tracked;
  - clears `_artifact_tmux_pane_id` and restores layout when the pane no longer exists;
  - returns true only when the tracked pane is still visible.
- Add an idempotent layout sync helper on `AgentPanelsMixin` that adds/removes a CSS class on `#agents-content` based on
  the helper above. CSS should hide `#agent-list-container` when that class is present, allowing
  `#agent-detail-container` to consume the width through its existing `1fr` sizing.
- Call the layout sync helper:
  - after a tmux artifact pane successfully opens;
  - after the tracked pane is closed by `A`;
  - when the tracked pane is discovered stale;
  - when switching back to the Agents tab;
  - at the start of Agents display refreshes, so normal refresh paths keep the layout consistent.
- Add a navigation guard helper that checks for a visible tracked artifact pane and emits the toast. Use it before code
  paths that change agent row focus:
  - `BasicNavigationMixin._navigate_agents_panel`;
  - `EventHandlersMixin.on_agent_list_selection_changed`;
  - `AgentPanelsMixin._change_focused_agent_panel`;
  - `AdvancedNavigationMixin._begin_agents_jump_mode` and `_handle_entry_jump_key` for Agents-tab jump targets.
- Keep the guard narrow: it should not block non-navigation interactions on the current agent or non-Agents tabs.

## Tests

- Add focused unit tests around the helper/guard behavior using small fake app harnesses rather than a full Textual
  pilot where possible.
- Extend existing navigation tests to assert `j`/`k` do not mutate `current_idx` or `_current_group_key` when the
  artifact viewer guard reports active, and that a warning toast is emitted.
- Add event-handler tests for list selection being ignored under the guard.
- Add panel/action tests for:
  - successful tmux artifact launch stores the pane id and applies the collapsed class;
  - tracked pane close restores the class;
  - stale tracked pane clears state and restores the class.
- Run targeted pytest for the new/changed tests, then run `just install` if needed followed by `just check` per repo
  instructions.

## Risks And Mitigations

- Calling `tmux` on every refresh would be wasteful. The pane-existence check should happen only when a pane id is
  tracked, and primarily on layout sync or guarded interactions.
- Hidden AgentList widgets may still receive programmatic selection events. Guarding `on_agent_list_selection_changed`
  prevents accidental selection changes even if a stale event arrives.
- External pane closure has no existing watcher. Detecting stale state on the next sync/interaction keeps implementation
  scoped without adding a polling timer.

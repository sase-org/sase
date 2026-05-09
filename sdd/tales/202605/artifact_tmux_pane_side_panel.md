---
create_time: 2026-05-09 03:49:53
status: wip
prompt: sdd/prompts/202605/artifact_tmux_pane_side_panel.md
---
# Plan: Restore Agents Side Panel When Artifact Tmux Pane Closes

## Context

The Agents tab hides the side panel by adding `-artifact-viewer-active` to `#agents-content` while an artifact viewer
tmux pane is tracked. The class makes `#agent-list-container` `display: none`, giving the artifact viewer more usable
width.

Opening an artifact in tmux records `_artifact_tmux_pane_id` and calls `_sync_artifact_viewer_layout()`. Stale pane
cleanup already exists, but it only runs when some UI path calls `_artifact_tmux_pane_visible()` or
`_sync_artifact_viewer_layout()`: explicit `A` toggles, Agents display refresh, or tab switches. Closing the tmux pane
manually does not create an agent artifact filesystem event, so no immediate refresh path runs and the side panel
remains hidden until another unrelated refresh happens.

## Goal

When the user closes the artifact viewer tmux pane manually, the Agents tab side panel should reappear promptly without
requiring an explicit keypress, tab switch, or agent refresh.

## Approach

Add a narrow lifecycle around tracked artifact tmux panes:

1. Track a Textual timer dedicated to the artifact pane, for example `_artifact_tmux_pane_watch_timer`.
2. When a tmux artifact viewer opens successfully and `_artifact_tmux_pane_id` is set, start a short interval timer.
3. On each tick, check only the tracked pane via the existing `artifact_tmux_pane_exists()` path by calling the existing
   layout sync helper.
4. If the pane no longer exists, clear `_artifact_tmux_pane_id`, remove `-artifact-viewer-active`, and stop the watch
   timer immediately.
5. When the app closes the pane itself or the pane becomes stale through an existing explicit path, also stop the watch
   timer.

This keeps the existing source of truth (`_artifact_tmux_pane_id`) and existing CSS behavior intact. The new polling is
active only while a pane is tracked, so it avoids adding constant background tmux subprocesses to the normal Agents tab.

## Implementation Notes

- Initialize the new timer field in `_init_app_state`.
- Keep the helper methods inside `AgentPanelsMixin`, next to the existing artifact viewer layout helpers.
- Use `set_interval()` only when available, so isolated mixin unit-test fakes remain simple.
- Store the timer handle returned by Textual and call `stop()` when the tracked pane is gone.
- Avoid a full `_refresh_agents_display()` from the timer. The visual fix only requires toggling the CSS class.

## Tests

Add focused unit coverage in `tests/ace/tui/actions/test_agent_artifact_image_actions.py`:

- Opening an artifact in a tmux pane starts a watch timer and keeps the side panel collapsed while the pane exists.
- When the timer callback observes that the tracked pane has disappeared, it clears `_artifact_tmux_pane_id`, removes
  `-artifact-viewer-active`, and stops the timer.
- Existing explicit close and stale-pane tests should continue to pass, confirming the explicit `A` behavior remains
  unchanged.

Then run the targeted test module. After code changes, run the repository check command required by the repo
instructions.

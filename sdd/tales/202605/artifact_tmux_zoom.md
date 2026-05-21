---
create_time: 2026-05-21 17:04:48
status: done
prompt: sdd/prompts/202605/artifact_tmux_zoom.md
---
# Plan: Artifact tmux pane zoom key

## Goal

Add a `z` key inside the terminal artifact viewer pane launched from the Agents tab `A` action. Pressing `z` should
toggle tmux zoom for the artifact pane, then redraw the current artifact image exactly like the existing `r` refresh
key. If the pane is already zoomed, the same key should unzoom it and refresh.

## Current behavior

- The Agents tab `A` action opens one or more selected artifacts through `AgentPanelArtifactMixin`.
- In a tmux session, that action launches the artifact viewer in a horizontal split via
  `view_agent_artifacts_in_tmux_pane()`, tracks the returned pane id, and decorates the tmux window.
- The artifact viewer process runs `run_artifact_sequence_loop()` / `run_artifact_page_loop()` in
  `src/sase/ace/tui/graphics/_viewer_loop.py`.
- The viewer already handles `r` by keeping the current page/artifact index and forcing a redraw.
- The Ace app-level `z` key is already the fold-mode prefix in `default_config.yml`, so this change should not add an
  Ace app keymap or change global keymap config.

## Design

1. Add a tmux helper in the artifact viewer launch module that toggles zoom with `tmux resize-pane -Z`.
   - Use tmux's native toggle behavior so already-zoomed panes unzoom without a separate zoom-state query.
   - Return the existing `ArtifactViewerResult` shape and surface structured warnings consistently with the other tmux
     helpers.
   - Target the current viewer pane when `TMUX_PANE` is available, while still supporting the default current-pane tmux
     behavior.

2. Wire `z` into the viewer loops.
   - Add `z` to the available key set only when the viewer is running in tmux.
   - On `z`, call the zoom helper, keep the current artifact and page index, and force the same redraw path used by `r`.
   - Preserve existing `tab` focus behavior, page navigation, artifact navigation, and `q` close behavior.

3. Update prompt text.
   - Show a concise `z: zoom` affordance in the artifact pane footer when tmux zoom is available.
   - Keep non-tmux artifact viewing prompts unchanged.

4. Add focused tests.
   - Unit test the tmux helper command and failure handling alongside the existing tmux pane helper tests.
   - Update loop tests so `z` appears only when tmux zoom is available.
   - Add loop tests proving `z` invokes zoom and redraws the current page/artifact without changing indices.
   - Cover both the single-page loop and multi-artifact sequence loop because both expose artifact viewer controls.

5. Verify.
   - Run the focused artifact viewer/tmux tests first.
   - Then run `just install` if needed followed by `just check`, per repo memory, before reporting completion.

## Non-goals

- Do not change the Ace app-level `z` fold-mode binding.
- Do not change `A` close/toggle behavior for tracked panes.
- Do not add tmux zoom state tracking in Ace; tmux's `resize-pane -Z` already provides the required toggle semantics.

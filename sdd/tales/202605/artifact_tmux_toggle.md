---
create_time: 2026-05-08 17:50:18
status: done
prompt: sdd/prompts/202605/artifact_tmux_toggle.md
---
# Artifact Tmux Pane Toggle Plan

## Goal

Make the Agents-tab `A` action act as a toggle for the artifact viewer tmux pane:

- If an artifact viewer pane previously opened by ACE is still present, pressing `A` closes that pane and stops.
- If no tracked artifact viewer pane exists, pressing `A` keeps the current behavior and opens the artifact selection
  panel.
- If the tracked pane was already closed with `q` or otherwise disappeared, pressing `A` should clear stale state and
  open the artifact panel normally.

## Current Behavior

The `A` action is implemented in `src/sase/ace/tui/actions/agents/_panels.py` as `action_open_agent_artifacts()`. It
lists artifacts for the selected agent, opens `AgentArtifactSelectionModal`, and the modal callback eventually calls
`_open_agent_artifact()` / `_open_agent_artifacts()`.

When running inside tmux, those methods call `view_agent_artifact_in_tmux_pane()` /
`view_agent_artifacts_in_tmux_pane()`, which delegate to `view_artifact_files_in_tmux_pane()` in
`src/sase/ace/tui/graphics/_viewer_launch.py`. That helper always runs:

```text
tmux split-window -h <viewer command>
```

The viewer pane then exits only when the viewer itself receives `q`.

## Implementation Design

1. Extend the artifact viewer launch result with optional tmux pane metadata.
   - Add `pane_id: str | None = None` to `ArtifactViewerResult`.
   - Keep the field defaulted so existing tests and callers constructing `ArtifactViewerResult(True)` continue to work.

2. Teach the tmux launcher to return the created pane id.
   - Change `view_artifact_files_in_tmux_pane()` to run `tmux split-window -h -P -F "#{pane_id}" <viewer command>`.
   - Parse `stdout` for the new pane id and return it in `ArtifactViewerResult(ok=True, pane_id=pane_id)`.
   - Preserve existing warning behavior for missing tmux, not-in-tmux, empty artifacts, and split failures.

3. Add small tmux pane lifecycle helpers in the graphics launch module.
   - A helper to check whether a pane id still resolves via `tmux display-message -p -t <pane_id> "#{pane_id}"`.
   - A helper to close a tracked pane with `tmux kill-pane -t <pane_id>`.
   - The close helper must refuse to kill the current pane (`TMUX_PANE`) so a stale or incorrect id cannot close ACE
     itself.

4. Track the artifact pane in `AgentPanelsMixin`.
   - When a tmux artifact launch succeeds and returns a `pane_id`, store it on the app/mixin instance, e.g.
     `_artifact_tmux_pane_id`.
   - At the top of `action_open_agent_artifacts()`, before selecting/listing artifacts, check for a stored pane id when
     inside tmux:
     - If it exists and is alive, kill it, clear the stored id, and return.
     - If it no longer exists, clear the stored id and continue with normal artifact-panel behavior.
     - If killing fails for a real tmux error, notify with a warning, clear the id if appropriate, and avoid opening a
       second pane in the same keypress.

5. Keep documentation and tests in sync.
   - Update the help popup label from “Open artifacts” to a short toggle-aware wording that stays within the help modal
     width constraints.
   - Update `docs/ace.md` artifact action text to mention that pressing `A` again closes the tmux viewer pane.
   - Add/adjust unit tests around:
     - tmux split invocation includes `-P -F "#{pane_id}"` and stores/returns the pane id.
     - pressing `A` with a live tracked pane calls `tmux kill-pane` and does not push the artifact modal.
     - pressing `A` with a stale tracked pane clears state and opens the artifact modal normally.

## Verification

Run focused tests first:

```bash
pytest tests/ace/tui/test_artifact_viewer.py tests/test_agent_artifact_e2e.py tests/ace/tui/test_image_file_panels.py tests/test_keybinding_footer_agent.py
```

Then, because this repo requires it after file changes, run:

```bash
just install
just check
```

---
create_time: 2026-06-09 09:43:15
status: done
prompt: sdd/prompts/202606/artifact_panel_zoom_open.md
---
# Plan: Artifact Panel Zoomed Tmux Open

## Goal

Add a `z` option to the agent artifact selection modal so a user can open the selected artifact, or the currently marked
artifact set, in a newly created tmux artifact viewer pane that is zoomed immediately.

## Current Flow

- `AgentArtifactSelectionModal` currently returns either one artifact, a list of marked artifacts, all artifacts, or
  `None`.
- `AgentPanelArtifactMixin.action_open_agent_artifacts()` normalizes that return value and calls
  `_open_agent_artifacts()`.
- `_open_agent_artifacts()` chooses the normal terminal viewer outside tmux, or `view_agent_artifacts_in_tmux_pane()`
  inside tmux.
- `view_artifact_files_in_tmux_pane()` already creates a split with `tmux split-window -h -P -F "#{pane_id}"`.
- The viewer process already supports `z` through `toggle_artifact_tmux_pane_zoom()`, which runs `tmux resize-pane -Z`.

## Design

1. Represent zoom intent explicitly at the modal boundary.
   - Add a small modal result type for zoomed opens, for example an immutable dataclass containing
     `artifacts: list[Any]` and `zoom: bool`.
   - Keep existing modal return values for existing actions (`enter`, selector keys, `A`, marked enter, cancel) so the
     current callback contract remains backward compatible.
   - Teach the panel callback normalization to understand both legacy artifact/list returns and the new zoomed result.

2. Add `z` to the artifact modal.
   - Reserve `z` in `_RESERVED_KEYS` so it is no longer assigned as a direct artifact selector.
   - Add a modal binding/action for `z`.
   - Make `z` mirror `enter` selection semantics: if any artifacts are marked, open the marked list; otherwise open the
     highlighted artifact. The only difference is `zoom=True`.
   - Update the hint text to include `z: zoom open`.

3. Thread zoom intent through the TUI artifact opening path.
   - Extend `_open_agent_artifact()` and `_open_agent_artifacts()` with `zoom: bool = False`.
   - When inside tmux, pass that flag to `view_agent_artifact_in_tmux_pane()` / `view_agent_artifacts_in_tmux_pane()`.
   - Outside tmux, open normally; optionally surface a concise warning if the user explicitly requested zoom and there
     is no tmux pane to zoom.

4. Add an initial-zoom tmux launch path.
   - Extend `view_artifact_file_in_tmux_pane()`, `view_artifact_files_in_tmux_pane()`,
     `view_agent_artifact_in_tmux_pane()`, and `view_agent_artifacts_in_tmux_pane()` with `zoom: bool = False`.
   - After `split-window` returns the new pane id, run `tmux resize-pane -Z -t <pane_id>` when `zoom=True`.
   - Reuse or lightly generalize the existing zoom helper so the same warning behavior and tmux availability checks are
     used.
   - If zoom fails after the pane was created, return a successful viewer result with the pane id plus a warning, so the
     TUI still tracks and can close/focus the live artifact pane.

5. Keep existing lifecycle behavior intact.
   - Do not change close/focus behavior for tracked artifact panes.
   - Keep parent notification pid handling unchanged.
   - Keep tmux decoration after launch unchanged; it should still run once the pane id is known.
   - Do not modify keymap config or app-level command catalog entries because this is a modal-local binding, not a
     configurable app keymap.

## Tests

Add or update focused tests:

- Modal interaction:
  - `z` returns a zoomed-open result for the highlighted artifact.
  - `z` returns marked artifacts in list order when marks exist.
  - selector-key generation reserves `z`.
  - hint text includes the new `z` option.
- Agent panel behavior:
  - zoomed modal result opens a single artifact in tmux with `zoom=True` and still tracks/decorates the returned pane.
  - zoomed modal result opens marked/multiple artifacts in tmux with `zoom=True`.
  - existing legacy artifact/list callback values still open exactly as before.
- Tmux launcher:
  - `zoom=True` launches the split and then runs `tmux resize-pane -Z -t <returned-pane-id>`.
  - a zoom failure after successful split preserves `ok=True` and `pane_id`, while surfacing a warning.
  - existing non-zoom tmux launch command shape remains unchanged.

## Verification

Run the targeted tests first:

```bash
pytest tests/ace/tui/modals/test_agent_artifacts_modal_interaction.py \
  tests/ace/tui/actions/test_agent_artifact_image_open.py \
  tests/ace/tui/artifact_viewer/test_tmux.py
```

Because this will change repo files, finish with the repository-required check:

```bash
just install
just check
```

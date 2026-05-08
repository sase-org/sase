---
create_time: 2026-05-08 00:03:01
status: done
prompt: sdd/prompts/202605/tmux_artifact_pane.md
---
# Plan: Open Agent Artifacts In A Tmux Side Pane

## Context

The Agents tab `A` keymap is bound to `open_agent_artifacts` in `src/sase/default_config.yml` and
`src/sase/ace/tui/bindings.py`. The action lives in `src/sase/ace/tui/actions/agents/_panels.py`: it lists artifacts for
the selected agent, optionally shows `AgentArtifactSelectionModal`, then calls `_open_agent_artifact()`.

Today `_open_agent_artifact()` suspends Textual and calls `view_agent_artifact()`. That enters
`src/sase/ace/tui/graphics/viewer.py`, renders images/Markdown/PDFs as page images, clears the current terminal, runs
`kitten icat`, and blocks on a small `n`/`p`/`q` page loop. This explains the bug: inside `sase ace`, artifact viewing
takes over the same pane that was rendering the TUI.

## Goal

When the user presses `A` on the Agents tab inside a tmux session, open the artifact viewer in a new pane to the right
of the current tmux pane instead of replacing the TUI in the current pane. Preserve the existing current-pane viewer
behavior outside tmux and preserve existing artifact selection behavior.

## Design

1. Keep artifact selection and artifact discovery in `AgentPanelsMixin`.

   `_list_selected_agent_artifacts()` and `AgentArtifactSelectionModal` should not need behavioral changes. The decision
   point remains `_open_agent_artifact()`, after the selected artifact is known.

2. Add tmux-pane launch support to `graphics.viewer`.

   Add a helper alongside `view_artifact_file()`/`view_agent_artifact()` that:
   - Detects tmux by checking `TMUX` or `TMUX_PANE`.
   - Validates that `tmux` is available.
   - Builds a command that runs the artifact viewer in a fresh process in the new pane.
   - Calls `tmux split-window -h ...` so the new pane is placed to the right of the current pane.
   - Returns the existing `ArtifactViewerResult` shape, with structured warnings on failure.

   This keeps terminal/viewer-specific behavior in the graphics/viewer layer instead of mixing tmux command details into
   the Agents action.

3. Give the viewer module a process entry point.

   Add a small `argparse` entry point in `src/sase/ace/tui/graphics/viewer.py`, for example:
   - `python -m sase.ace.tui.graphics.viewer --kind image /path/to/artifact`

   The entry point should call `view_artifact_file(path, kind=kind)` and print a concise warning before exiting non-zero
   if rendering or viewer dependencies fail. This avoids fragile `python -c ...` quoting and lets tests verify the pane
   command cleanly.

4. Prefer a tmux pane only when tmux is active.

   In `_open_agent_artifact()`:
   - If inside tmux, call the new tmux-pane helper without `self.suspend()`.
   - If not inside tmux, keep the existing `with self.suspend(): view_agent_artifact(artifact)` behavior.
   - Notify the user only if the result has a warning.

   For the first pass, use a normal `split-window -h` that creates a right-side pane and focuses it. That gives the
   viewer pane keyboard input for `n`/`p`/`q`, while still leaving the TUI visible in the original pane. If we later
   want the TUI to keep focus, make that a follow-up option using `split-window -d`, but that would make the current
   page-loop controls harder to use.

5. Keep non-image artifact support intact.

   The pane helper should reuse `render_artifact_pages()`/`run_artifact_page_loop()` through the module entry point, so
   Markdown and PDF artifacts continue to support pagination exactly like the current same-pane viewer.

## Testing

1. Extend `tests/ace/tui/test_artifact_viewer.py`.

   Add focused tests for:
   - tmux detection returns false outside tmux.
   - tmux pane launch returns a warning when `tmux` is unavailable.
   - tmux pane launch invokes `tmux split-window -h` with the current Python executable/module entry point, artifact
     path, and kind.
   - the module entry point delegates to `view_artifact_file()` and maps success/failure to exit codes.

2. Extend `tests/ace/tui/test_image_file_panels.py`.

   Update or add tests around `_open_agent_artifact()`:
   - Inside tmux, the action calls the tmux-pane helper and does not enter `self.suspend()`.
   - Outside tmux, the existing suspend/current-pane viewer behavior remains unchanged.
   - Warning notifications still surface when the viewer helper returns a warning.

3. Run the narrow tests first:

   ```bash
   pytest tests/ace/tui/test_artifact_viewer.py tests/ace/tui/test_image_file_panels.py
   ```

4. Because this repo memory requires it after code changes, run:

   ```bash
   just install
   just check
   ```

## Risks And Follow-Ups

- `kitten icat` rendering depends on the terminal inside the new tmux pane supporting the same graphics protocol. This
  is already a dependency of the current viewer; the change only moves where it runs.
- Focusing the new pane is intentional for the first implementation because the viewer has an interactive page loop. A
  later preference/config could choose detached launch if users want the TUI to keep focus.
- The new module entry point should stay internal and minimal. It is primarily a stable process boundary for tmux, not a
  new public CLI surface.

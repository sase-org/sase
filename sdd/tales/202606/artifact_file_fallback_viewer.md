---
create_time: 2026-06-03 08:31:33
status: done
prompt: sdd/prompts/202606/artifact_file_fallback_viewer.md
---
# Plan: Artifact File Fallback Viewer

## Goal

Allow SASE agent artifacts of any file type to be opened from the Agents artifact picker without returning the current
`Unsupported artifact type` error. Keep the existing image, PDF, and Markdown rendering path unchanged, and add a
terminal-text fallback that opens arbitrary files in the artifact tmux panel with `bat` when available or `cat` when
`bat` is missing.

## Current Behavior

- Agent artifact opening is launched from `src/sase/ace/tui/actions/agents/_panel_artifacts.py`.
- Artifact paths are normalized by `src/sase/ace/tui/graphics/_viewer_artifacts.py` and then routed through
  `src/sase/ace/tui/graphics/_viewer_launch.py`.
- Tmux launches run `python -m sase.ace.tui.graphics.viewer` from `src/sase/ace/tui/graphics/_viewer_tmux.py`.
- The viewer currently renders only images, PDFs, and Markdown. In `src/sase/ace/tui/graphics/_viewer_render.py`,
  anything else produces `unsupported_artifact_kind`.
- The artifact picker already binds `y` to copy contents and `Y` to copy path in
  `src/sase/ace/tui/modals/agent_artifacts_modal.py`; selector-key generation reserves lowercase `y`.

## Approach

1. Add a text/raw-file viewer mode.
   - Extend the artifact viewer type model with a terminal text mode for non-image, non-PDF, non-Markdown files.
   - Keep image/PDF/Markdown behavior on the existing `kitten icat` render loop.
   - Treat unknown artifact kinds and the existing `file` kind as viewable when the path points at a real file.

2. Add `bat`/`cat` fallback execution.
   - Add a small viewer helper that chooses `bat` via `shutil.which("bat")`; otherwise use `cat`.
   - Prefer `bat --paging=always --color=always --decorations=always -- <path>` so the tmux pane remains useful for long
     files.
   - For `cat`, print a normal artifact header, output the file, and wait for a quit key so the pane does not close
     immediately after output.
   - Preserve the artifact viewer cleanup/notification path so the parent TUI clears tracked tmux pane state when the
     fallback viewer exits.

3. Preserve keymap behavior.
   - Keep `y` and `Y` available in the artifact picker for copy contents and copy path.
   - If selector-key generation changes while implementing this, explicitly reserve both `y` and `Y` so these keymaps
     are not shadowed by per-artifact shortcuts.
   - Keep artifact opening on existing open actions (`Enter`, selector keys, and `A` open all).

4. Handle multi-artifact opens conservatively.
   - Continue using the current sequence loop for fully renderable selections.
   - For selections containing raw files, support opening them with the fallback viewer rather than aborting at the
     first unsupported artifact.
   - Avoid sending binary renderable artifacts through `cat`; route each artifact according to its resolved mode.

5. Test the behavior.
   - Update artifact viewer unit tests so a `.json`/unknown file no longer reports `unsupported_artifact_kind`.
   - Add coverage for command selection: `bat` is preferred, `cat` is used when `bat` is missing.
   - Add coverage that `cat` fallback waits for a quit key instead of immediately closing.
   - Keep existing tests for missing `kitten`/PDF/Markdown dependencies valid for renderable modes.
   - Keep or update artifact picker tests so `y`/`Y` remain copy/path keymaps and are not used as selector keys.

6. Verify.
   - Run the focused artifact viewer and artifact modal tests first.
   - Because this repo requires it after code changes, run `just install` if needed and then `just check`.

## Expected Result

Opening a SASE artifact such as `done.json`, `agent_meta.json`, logs, text files, or any other non-rendered artifact
from the Agents artifact picker opens an artifact tmux panel and displays the file with `bat` when installed, otherwise
with `cat`, instead of showing `Unsupported artifact type`.

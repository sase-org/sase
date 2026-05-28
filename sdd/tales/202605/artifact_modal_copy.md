---
create_time: 2026-05-28 14:26:16
status: done
---
# Plan: Copy Selected Artifact Content and Path from the Artifact Picker

## Goal

Add fast copy actions to the Agents-tab artifact picker opened with `A`:

- `y`: copy the selected Markdown file contents.
- `Y`: copy the selected artifact file path.

The behavior should be local to `AgentArtifactSelectionModal`, should not change the `A` open/view flow, and should keep
the modal open after copying so users can continue selecting or opening artifacts.

## Current Context

The `A` key on the Agents tab is handled by `AgentPanelArtifactMixin.action_open_agent_artifacts()`, which pushes
`AgentArtifactSelectionModal`. The picker already owns modal-local bindings for `m`, `A`, `enter`, `j/k`, and
`q/escape`; it is not driven by the configurable app keymap registry. Because of that, `src/sase/default_config.yml`
does not need a new app-level keymap entry for this change.

The modal currently reserves selector keys for navigation and modal actions. Lowercase `y` is still available as a row
selector for large artifact lists, so adding a `y` copy action must also reserve `y` to avoid a selector/action
conflict.

Artifact paths have display-specific behavior:

- Normal artifacts display `artifact.path`.
- Generated Markdown PDFs display `artifact.source_path` when present, while still opening `artifact.path`.
- Workspace-relative display is derived from `artifact.workspace_dir`.

Copy should follow the path the row is presenting to the user for Markdown-source cases, while still resolving relative
paths through `workspace_dir` before reading or copying.

## Design

1. Add focused path helpers in `agent_artifacts_modal.py`.
   - Keep `_artifact_display_path()` as the visible-path source.
   - Add a resolver that turns the selected display path into an actual filesystem path:
     - expand `~`;
     - if the path is relative and `workspace_dir` exists, resolve it under the workspace;
     - otherwise use the expanded path as-is.
   - Add a clipboard formatter that copies an absolute/home-relative path, matching nearby TUI copy conventions.
   - Treat `.md`, `.markdown`, `.mdown`, and `.mkd` as Markdown content targets.

2. Add modal actions and bindings.
   - Add `("y", "copy_contents", "Copy")`.
   - Add `("Y", "copy_path", "Copy path")`.
   - Add `y` to `_RESERVED_KEYS` so it never becomes a row selector.
   - Implement selected-row lookup once and share it across open/copy actions.
   - `action_copy_contents()` should:
     - warn if no row is highlighted;
     - warn if the selected path is not a Markdown file;
     - read with `encoding="utf-8", errors="replace"`;
     - copy the full contents, not stripped, so markdown formatting is preserved;
     - notify success with a short label/line count.
   - `action_copy_path()` should:
     - warn if no row/path is available;
     - copy the selected resolved path with home shortened to `~`;
     - notify with the copied path.

3. Update user-visible modal hints.
   - Include `y: copy` and `Y: path` in the hint string.
   - Preserve existing mark-count hint behavior.

4. Add focused regression tests.
   - `y` is not assigned as a selector key.
   - Pressing `y` copies the highlighted Markdown file contents and keeps the modal open.
   - Pressing `Y` copies the highlighted path and keeps the modal open.
   - A generated PDF row with a Markdown `source_path` copies the Markdown source contents/path, not the generated PDF.
   - Pressing `y` on a non-Markdown artifact warns and does not copy.
   - Hints include the new copy affordances.

5. Verification.
   - Run the focused modal tests first.
   - Because this repo requires it after code changes, run `just install` before final verification if needed, then
     `just check`.

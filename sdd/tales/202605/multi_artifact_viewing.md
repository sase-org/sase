---
create_time: 2026-05-08 12:38:30
status: done
prompt: sdd/prompts/202605/multi_artifact_viewing.md
---
# Multi-Artifact Viewing Plan

## Goal

Add support for opening multiple selected agent artifacts from the artifact picker and navigating between those
documents in the terminal viewer.

The user flow should be:

- Open the agent artifact picker with the existing agent-artifacts action.
- Use `m` in the artifact panel to mark or unmark artifacts.
- Press `<enter>`.
- If marks exist, open the marked artifacts in their existing list order and show the first document first.
- If no marks exist, preserve the current behavior: `<enter>` opens the highlighted artifact and selector keys open a
  single artifact directly.
- While viewing, keep existing lowercase page navigation for pages inside a document, and add uppercase document
  navigation:
  - `N` is available when the selected artifact set has a later document.
  - `P` is available when the selected artifact set has an earlier document.

## Current Shape

- `src/sase/ace/tui/modals/agent_artifacts_modal.py` owns the artifact picker.
  - It currently returns one artifact or `None`.
  - It supports direct single-key selectors, `<enter>`, `j/k`, and `q/esc`.
  - The selector-key pool currently can assign `m`, so `m` must become reserved for marking.
- `src/sase/ace/tui/actions/agents/_panels.py` opens one artifact from the picker callback.
  - Single artifacts are opened immediately.
  - Multiple available artifacts show `AgentArtifactSelectionModal`.
  - The viewer is launched either in the same terminal under `self.suspend()` or in a tmux split.
- `src/sase/ace/tui/graphics/viewer.py` renders one artifact to one or more image pages.
  - Lowercase `n`/`p` navigate pages inside the current document.
  - The module entrypoint accepts one path plus one optional kind.

## Implementation Plan

1. Extend the artifact picker modal to track marked rows.
   - Add `m` to the modal bindings as `toggle_mark`.
   - Add `m` to `_RESERVED_KEYS` so direct selector letters never conflict with marking.
   - Render a small checked/unchecked marker in each option row.
   - After marking, refresh the option list while preserving the highlighted row.
   - Update the hints line to show `m: mark`, and include the mark count when nonzero.
   - On `<enter>` or option activation:
     - If any rows are marked, dismiss with a list of marked artifacts in original list order.
     - Otherwise dismiss with the single highlighted artifact, preserving current behavior.
   - Keep direct selector keys as immediate single-artifact open for fast existing workflows.

2. Update the agent artifact action to accept either one artifact or a list of artifacts.
   - Normalize the callback value into a non-empty list.
   - Preserve the existing no-artifacts and single-artifact behavior.
   - Add `_open_agent_artifacts()` or equivalent helper that can open a sequence.
   - For same-pane viewing, call a multi-artifact viewer helper inside one `suspend()` block.
   - For tmux, call a tmux helper that launches the module entrypoint with all paths/kinds.
   - Preserve warning notification behavior by surfacing the first warning returned from the viewer.
   - Restore focus to the agent list after the picker callback, even for multi-open.

3. Extend the terminal viewer to support a selected artifact sequence.
   - Add a lightweight `ArtifactViewSpec` dataclass containing `path` and `kind`.
   - Keep existing `view_artifact_file()` and `view_agent_artifact()` APIs working by delegating to the new sequence
     helper for a single spec.
   - Add `view_artifact_files()` and `view_agent_artifacts()` helpers.
   - Render the currently selected document on demand into a shared temporary root, using a per-document cache
     directory. This avoids rendering all selected documents up front and still lets `P` return without re-rendering
     unnecessarily.
   - Preserve image, markdown, and PDF handling through the existing `render_artifact_pages()` path.

4. Extend the viewer key loop with document-level navigation.
   - Preserve lowercase `n`, `p`, `r`, and `q` behavior for pages.
   - Add uppercase `N` and `P` as document actions only when the current selected document has a next or previous
     artifact.
   - Reset page index to the first page when switching documents.
   - Update the prompt to include both document position and page position, for example:
     `Artifact 1/3  Page 1/2  n: next page  N: next artifact  r: refresh  q: quit`
   - Avoid lowercasing key input before availability checks so `N`/`P` remain distinct from `n`/`p`.

5. Extend the module entrypoint for tmux.
   - Accept one or more artifact paths.
   - Allow repeated `--kind` values, aligned by position with the path list.
   - Keep current one-path usage compatible.
   - For tmux launch, quote a module command that includes every selected artifact path and its kind metadata.

6. Add targeted tests.
   - Modal tests:
     - `m` toggles marks and `<enter>` returns marked artifacts in list order.
     - No marks plus `<enter>` still returns the highlighted artifact.
     - Selector keys reserve `m`.
   - Agent action tests:
     - Picker callback with marked artifacts opens the sequence and restores focus.
     - Single-artifact existing behavior remains unchanged.
     - Tmux multi-open launches the sequence helper without same-pane suspend.
   - Viewer tests:
     - Available keys include `N`/`P` only at document boundaries where appropriate.
     - The loop handles page navigation and document navigation distinctly.
     - The module entrypoint delegates multiple paths/kinds to the sequence viewer.

## Validation

Run focused tests first:

```bash
pytest tests/ace/tui/modals/test_agent_artifacts_modal.py tests/ace/tui/test_artifact_viewer.py tests/ace/tui/test_image_file_panels.py
```

Then, because this repo’s instructions require it after code changes, run:

```bash
just install
just check
```

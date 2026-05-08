---
create_time: 2026-05-08 15:44:33
status: done
prompt: sdd/prompts/202605/artifact_viewer_file_path_header.md
---
# Artifact Viewer File Path Header Plan

## Goal

When a user opens one or more selected artifacts from the agent artifact panel, the terminal image/PDF viewer should
show the path of the artifact currently being viewed above the rendered image. The header should be readable and
polished using Rich, and it must work for both single-artifact and multi-artifact navigation.

## Current Behavior

Agent artifact selection lives in `src/sase/ace/tui/modals/agent_artifacts_modal.py`. The selected artifact or marked
artifacts flow through `AgentPanelsMixin._open_agent_artifact()` / `_open_agent_artifacts()` in
`src/sase/ace/tui/actions/agents/_panels.py`.

The actual terminal viewer lives in `src/sase/ace/tui/graphics/viewer.py`:

- Artifact objects are reduced to `ArtifactViewSpec(path, kind)`.
- PDFs and markdown are rendered into temporary PNG pages.
- Images are displayed directly.
- `run_artifact_sequence_loop()` clears the terminal, runs `kitten icat <page>`, then prints a plain text navigation
  prompt.
- `run_artifact_page_loop()` is an older page-only helper used by tests and compatible callers.

The right insertion point is the viewer loop, not the artifact selection modal, because both single and multi-selection
eventually use the same viewer code.

## Design

Add a Rich-rendered header immediately after clearing the terminal and immediately before running `kitten icat`.

The header should include:

- A compact title such as `Viewing artifact`.
- The artifact file path from the current `ArtifactViewSpec.path`.
- Multi-artifact position when applicable, e.g. `Artifact 2/4`.
- Page position when applicable, e.g. `Page 3/7`.

The path should be normalized with `Path(...).expanduser().resolve(strict=False)` for consistency, but should not
require the file to exist. If resolution fails due to an OS-level path issue, fall back to the expanded string.

Use Rich in `viewer.py` for terminal output:

- Use `rich.console.Console` and `rich.panel.Panel` or a compact `Group`/`Text` composition.
- Keep width terminal-aware through Rich’s console defaults.
- Use restrained colors already common in this codebase, such as gold for the title and cyan for the path.
- Avoid excessive vertical space so the rendered image remains prominent.

## Implementation Steps

1. Add a small helper in `src/sase/ace/tui/graphics/viewer.py` to format a path for display without requiring the
   artifact to exist.
2. Add a Rich header rendering helper that accepts the current `ArtifactViewSpec`, page index/count, and artifact
   index/count.
3. Call the header helper in `run_artifact_sequence_loop()` after `_clear_terminal(run)` and before `kitten icat`.
4. Keep `run_artifact_page_loop()` unchanged unless needed, because it only receives rendered page paths and cannot
   reliably infer the source artifact path. The artifact-panel flow uses `run_artifact_sequence_loop()`.
5. Add focused tests in `tests/ace/tui/test_artifact_viewer.py` for the new header helper and for sequence-loop output
   with multiple artifacts.
6. Run the targeted artifact viewer tests, then run the repo check command required by this workspace after code
   changes.

## Risks and Mitigations

- Rich output can make exact string tests brittle. Keep tests focused on important text content instead of full
  ANSI/control-code snapshots.
- Rendering a header before `kitten icat` changes terminal layout. Keep the header compact so existing navigation still
  feels natural.
- The tmux path uses the same module entrypoint, so the change should apply automatically in split-pane viewing.

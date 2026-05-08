---
create_time: 2026-05-08 12:01:04
status: done
prompt: sdd/prompts/202605/artifacts_panel_paths.md
---
# Artifacts Panel Path Display Improvements

## Goal

Improve the recently added agent artifacts picker so artifact rows are easier to read and avoid duplicate plan entries:

- Display home-relative paths with `~` instead of `/home/bryan/`.
- Display workspace-relative paths for files under the workspace directory where the agent ran.
- Suppress the `~/.sase/plans/...` plan artifact when a workspace-relative plan file with the same filename is also
  listed.
- For generated Markdown PDFs, keep the artifact openable as a PDF, but display the original Markdown source path
  instead of the generated `markdown_pdfs/*.pdf` path.

## Current Shape

`src/sase/core/agent_artifact_facade.py` owns artifact synthesis. It reads `done.json`, `agent_meta.json`, and
`plan_path.json`, creates `AgentArtifact` records, and de-duplicates by openable `path`.

`src/sase/ace/tui/modals/agent_artifacts_modal.py` owns the picker row text. It currently expands every displayed path
with `Path(path).expanduser()`, so home paths show as `/home/bryan/...`, workspace files show as absolute paths, and PDF
artifacts show their generated PDF path.

Generated Markdown PDFs are accompanied by `markdown_pdfs/index.json`, written by
`src/sase/attachments/markdown_pdf.py`, which records `{source_path, pdf_path}` pairs. That index is the right source of
truth for displaying Markdown source paths while preserving the PDF as the path opened by the viewer.

## Implementation Plan

1. Extend artifact synthesis with display-oriented source metadata:
   - Read `done["workspace_dir"]` from the agent run metadata.
   - Read `markdown_pdfs/index.json` from the agent artifacts directory and map each generated PDF path back to its
     Markdown `source_path`.
   - For PDF artifacts, keep `path` as the PDF path so opening still renders the PDF, but set `source_path` to the
     Markdown source and set the label from the Markdown source filename/path rather than the generated PDF name.

2. Add small, testable path formatting helpers:
   - Prefer workspace-relative display for paths inside `done["workspace_dir"]`.
   - Otherwise show home-relative display by replacing the actual home prefix with `~`.
   - Fall back to the existing absolute path behavior for paths outside both scopes.
   - Use the artifact `source_path` for display when present on generated PDF artifacts; otherwise use `path`.

3. Suppress duplicate plan artifacts:
   - While synthesizing plan artifacts, distinguish home plan files under `~/.sase/plans/` from workspace-relative plan
     files.
   - If a workspace-contained plan with the same basename is already present, skip the matching `~/.sase/plans/` plan
     entry.
   - Keep normal path de-duplication in place for exact duplicates.

4. Keep behavior boundaries clear:
   - Do not change the artifact viewer’s open path contract.
   - Keep this in Python/TUI-facing code; the changes are presentation and artifact-list shaping, not shared Rust scan
     behavior.

5. Tests:
   - Add facade tests for generated PDF artifacts displaying Markdown source metadata.
   - Add facade tests for skipping a `~/.sase/plans/<name>.md` plan when a workspace plan with `<name>.md` exists.
   - Add modal tests for `~` display and workspace-relative display/truncation.
   - Run focused tests for the artifact facade and modal, then run `just install` and `just check` as required by repo
     instructions after code changes.

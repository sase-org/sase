---
create_time: 2026-05-10 01:19:36
status: wip
prompt: sdd/prompts/202605/hide_pdf_artifacts_panel.md
---
# Hide PDF Artifacts From ACE Artifacts Panel

## Problem

The ACE agent artifact picker currently shows generated Markdown PDF files. The snapshot shows a generated
`markdown_pdfs/*.md.pdf` row in the `Agent Artifacts` modal even though the selected agent's detail header already
suppresses PDF artifacts. This makes the modal noisy and exposes implementation artifacts that users do not need to
choose from directly.

## Product Behavior

The ACE artifacts panel should list user-meaningful artifacts only:

- Keep chat transcripts, plans, images, markdown artifacts, and generic file artifacts visible.
- Hide artifacts whose kind is `pdf`, including generated Markdown PDFs and explicit PDF artifacts.
- Keep PDF generation metadata and backend artifact records available for other consumers that still need them.
- Preserve the existing "No artifacts found" behavior when filtering leaves no visible artifacts.

## Technical Approach

1. Scope the change to the ACE TUI artifacts-panel selection boundary.
   - `sase.core.agent_artifact_facade.list_agent_artifacts()` is a shared backend-style catalog and currently feeds
     tests, mobile helpers, and notification/file attachment flows.
   - The details header already filters `artifact.kind == "pdf"` in
     `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py`.
   - Matching that behavior in `src/sase/ace/tui/actions/agents/_panel_artifacts.py` avoids changing shared artifact
     semantics or the explicit `sase artifact` contract.

2. Add a focused filter helper or inline filter in `_list_selected_agent_artifacts()`.
   - Fetch all artifacts via `list_agent_artifacts(artifacts_dir)` as today.
   - Return only artifacts where `getattr(artifact, "kind", None) != "pdf"`.
   - Keep broad exception handling unchanged so artifact-list failures remain non-fatal to the TUI.

3. Add regression coverage for the real failure mode.
   - Build a temporary agent artifacts directory with `done.json` containing chat/plan data plus `markdown_pdf_paths`.
   - Optionally include an explicit PDF artifact to prove all PDF artifacts are hidden.
   - Assert `_list_selected_agent_artifacts()` returns the non-PDF artifacts and excludes generated/explicit PDF rows.
   - Assert the action warns instead of opening the modal when an agent only has PDF artifacts after filtering.

4. Verification.
   - Run the focused artifact action tests.
   - Run the artifact facade/modal tests touched by nearby behavior if needed.
   - Because this repo requires it after changes, run `just install` if needed and then `just check` before final
     response.

## Non-Goals

- Do not stop generating Markdown PDFs.
- Do not remove PDF artifacts from `done.json`, notifications, mobile APIs, or the shared artifact facade.
- Do not change the artifact viewer's ability to open PDFs when another caller explicitly passes one.

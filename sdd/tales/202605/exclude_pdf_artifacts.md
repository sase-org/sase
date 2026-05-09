---
create_time: 2026-05-09 15:41:23
status: done
prompt: sdd/prompts/202605/exclude_pdf_artifacts.md
---
# Plan: Exclude PDFs from Agents-Tab ARTIFACTS Field

## Goal

Fix the Agents-tab details panel so the `ARTIFACTS` field never lists PDF files. Generated Markdown PDFs should still be
recorded in `done.json` and remain available to completion notifications and file-panel attachment flows; the change is
limited to the metadata field shown in `sase ace`.

## Diagnosis

The PDF in the snapshot is not coming from the row renderer. It is produced by the artifact metadata path:

- completed runs persist generated Markdown PDFs in `done.json["markdown_pdf_paths"]`;
- `synthesize_default_agent_artifacts()` in `src/sase/core/agent_artifact_defaults.py` turns those paths into default
  `AgentArtifact(kind="pdf")` entries;
- the Agents-tab header helper `_agent_artifact_paths()` in `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py`
  calls `list_agent_artifacts()` and renders every non-chat artifact;
- therefore generated PDFs are rendered in the `ARTIFACTS` field next to real user-facing source artifacts such as the
  committed plan file.

This is a presentation bug in the Agents-tab metadata field. The underlying PDF metadata is useful elsewhere:

- `src/sase/axe/run_agent_runner_finalize.py` and related runner code attach PDFs to completion notification flows;
- `src/sase/ace/tui/models/_loaders/_done_loaders.py` includes `markdown_pdf_paths` in completed-agent `extra_files` so
  file panels can show/cycle completion attachments;
- the artifact picker/modal already has PDF-specific display behavior and should not be broken by this metadata-field
  cleanup.

## Design

1. Filter PDFs at the prompt-panel metadata boundary.
   - Update `_agent_artifact_paths()` so it excludes artifacts with `kind == "pdf"` in addition to chat artifacts.
   - Apply the filter to all PDF artifacts, including generated Markdown PDFs and explicit PDF artifacts, matching the
     product rule that PDFs should never appear in the `ARTIFACTS` field.

2. Leave artifact generation and attachment plumbing intact.
   - Do not remove `markdown_pdf_paths` from `done.json`.
   - Do not change notification attachment ordering.
   - Do not change completed-agent `extra_files` handling.
   - Do not change the artifact modal or core artifact list unless tests show an unavoidable coupling.

3. Add focused regression tests.
   - Extend the existing Agents-tab artifact metadata tests to create a generated PDF path in `markdown_pdf_paths` and
     assert that the PDF path is absent while the source plan/explicit artifacts remain visible.
   - Add an explicit-PDF case if straightforward, to lock in the "never PDFs in this field" rule.
   - Keep existing tests that prove images, prompt images, plans, and explicit non-PDF artifacts still render.

4. Verify with targeted tests first, then repo check.
   - Run the affected metadata tests.
   - Run nearby artifact facade/modal tests if the change touches shared behavior.
   - Per repo memory, run `just install` if needed and `just check` before final handoff.

## Expected Files

- `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py`
- `tests/ace/tui/widgets/test_agent_display_metadata.py`

## Risk

The lowest-risk fix is display-layer filtering because it preserves the existing PDF lifecycle for notifications,
generated attachment persistence, and file-panel navigation. A deeper core change would likely regress those flows and
conflict with the Markdown PDF attachment design.

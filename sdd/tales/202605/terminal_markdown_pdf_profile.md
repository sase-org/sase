---
create_time: 2026-05-21 17:20:48
status: done
prompt: sdd/prompts/202605/terminal_markdown_pdf_profile.md
---
# Plan: Terminal Markdown PDF Source Rendering

## Goal

Make Markdown artifacts opened in the terminal artifact viewer always use the pane-aware terminal profile, even when the
artifact row points at a pre-generated Markdown PDF that was created with the mobile profile for notifications.

## Root Cause

SASE has two valid Markdown-to-PDF profiles:

- The default attachment profile in `src/sase/attachments/markdown_pdf.py` is intentionally mobile/narrow
  (`4.25in x 7in`). This is correct for smartphone and notification attachment use.
- The artifact viewer profile in `src/sase/ace/tui/graphics/_viewer_render.py` is pane-aware. It sizes the transient PDF
  to the tmux pane/image area before `pdftoppm` converts pages to images. This is the format that looks right in a
  terminal.

Generated Markdown PDF artifacts preserve the original Markdown path in `AgentArtifact.source_path`, and the picker
already displays that source path. However, `_open_agent_artifact()` and `_open_agent_artifacts()` pass the artifact
unchanged into `view_agent_artifact(s)`. The viewer therefore sees `kind="pdf"` and
`path=<artifacts_dir>/markdown_pdfs/*.pdf`, converts the already-mobile PDF, and produces many narrow pages. When the
user opens a direct Markdown artifact (`chat`, `plan`, or `markdown`), the viewer renders from the Markdown source and
gets the terminal-shaped profile.

## Design

1. Add a small normalization helper at the artifact-viewer boundary.
   - Keep attachment generation unchanged.
   - When opening an artifact whose `kind` is `pdf`, whose `source_path` points to an existing Markdown file, replace
     the viewer spec with `path=source_path` and `kind="markdown"`.
   - Preserve labels and modal display behavior; this is only about the viewer input.
   - If the source is missing or not Markdown, fall back to opening the PDF so older artifacts still work.

2. Put the normalization close to viewer launch code, not in core artifact synthesis.
   - Core artifact metadata should continue to report the actual generated PDF plus its source mapping.
   - The terminal viewer is a presentation surface, so choosing the source for re-rendering belongs in the TUI
     graphics/viewer layer or the Agents artifact opener.
   - Prefer a helper in `src/sase/ace/tui/graphics/_viewer_launch.py` so single and multi-artifact launches, tmux and
     non-tmux, share the same behavior.

3. Maintain explicit PDF behavior.
   - A normal PDF with no Markdown `source_path` still opens as a PDF.
   - A PDF with a non-Markdown or missing source still opens as a PDF.
   - Existing direct Markdown paths continue through the current pane-aware path.

4. Add focused tests.
   - Unit test the normalizer: generated Markdown PDF artifact becomes `ArtifactViewSpec(source_path, "markdown")`.
   - Unit test the fallback cases: missing source and non-Markdown source remain PDF.
   - Update viewer launch tests so `view_agent_artifact(s)` and `view_agent_artifact(s)_in_tmux_pane()` pass normalized
     specs to the underlying file viewers.
   - Add or adjust an integration-style rendering test proving a PDF artifact with a Markdown `source_path` reaches
     `render_artifact_pages()` as Markdown with an `image_area`, so it gets the pane-aware profile.

5. Verify.
   - Run focused tests for artifact viewer launch/rendering and agent artifact metadata.
   - Run `just install` if this workspace is not prepared.
   - Run `just check` before reporting completion, per repo instructions.

## Non-Goals

- Do not change the mobile/default Markdown PDF profile.
- Do not stop generating Markdown PDF attachments for notifications.
- Do not reclassify stored generated PDFs as Markdown in the core artifact model.
- Do not add a new user preference or configuration surface.

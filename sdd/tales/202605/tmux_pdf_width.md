---
title: Tmux Artifact PDF Width Fix
create_time: 2026-05-08 19:41:54
status: done
prompt: sdd/prompts/202605/tmux_pdf_width.md
---

# Plan: Make Markdown Artifact PDFs Fit The Tmux Pane

## Goal

Fix the regression after `e5559d305b37` where Markdown artifacts rendered as PDFs are a little too wide for the
right-side tmux artifact pane.

The fix should preserve the improved pane-aware rendering from that commit, but stop using every available terminal
column and avoid generating very wide Markdown pages that are likely to clip or feel oversized in a narrow split.
Mobile/notification Markdown PDF attachments should remain unchanged.

## Current Behavior

The current viewer path is:

1. `view_artifact_files_in_tmux_pane()` launches `python -m sase.ace.tui.graphics.viewer` in `tmux split-window -h`.
2. `run_artifact_sequence_loop()` computes `artifact_image_area()` from the pane's terminal size.
3. Markdown artifacts call `render_artifact_pages(..., image_area=...)`.
4. `_viewer_render.artifact_markdown_pdf_profile_for_image_area()` derives the PDF page aspect ratio from
   `columns / rows`.
5. `kitten_icat_command()` places the rendered page into exactly `<columns>x<rows>@0x<top>`.

The problem is that step 2 and step 5 currently target the full terminal width. In tmux/Kitty, exact-width placements
can be sensitive to borders, cell rounding, and placeholder wrapping. Separately, the Markdown profile permits a page
aspect ratio up to `3.0` and page width up to `11in`, so common right-side pane shapes can produce a very wide document.

## Design

Keep the behavior context-specific:

- Attachment PDFs keep `MOBILE_MARKDOWN_PDF_PROFILE` and the existing `render_markdown_pdf()` default.
- Existing PDF files continue to display as authored.
- The terminal artifact viewer gets a conservative display area and a narrower Markdown PDF profile.

Use two complementary safeguards:

1. Add a small horizontal gutter to `artifact_image_area()`.
   - Subtract a few columns from the terminal width before building `ArtifactImageArea`.
   - Keep a minimum display width for very small panes.
   - Keep `left=0` so the image still starts predictably at the pane's left edge.
   - This makes `kitten icat --place` avoid the pane's last cells, where tmux wrapping/clipping is most likely.

2. Narrow the Markdown artifact profile.
   - Reduce the maximum artifact page aspect ratio from the current `3.0` to a more document-like cap.
   - Reduce the maximum artifact Markdown page width from the current `11in` to roughly letter width.
   - Keep the existing readable font sizes and small margins.
   - Keep the minimum width at the current mobile width so very narrow panes do not produce worse wrapping than before.

This should make the generated page and the displayed image both fit with room to spare, while preserving the core
benefit of `e5559d305b37`: Markdown artifacts still adapt to the pane instead of using the phone-shaped attachment
profile.

## Implementation Steps

1. Update `_viewer_loop.artifact_image_area()`.
   - Introduce a small horizontal reserved-column constant.
   - Compute `columns = max(_MIN_IMAGE_COLUMNS, terminal_columns - reserved_columns)`.
   - Add an optional keyword-only `reserved_columns` parameter for tests and future tuning.
   - Leave row reservation and top offset behavior intact.

2. Update `_viewer_render.artifact_markdown_pdf_profile_for_image_area()`.
   - Lower `_MAX_ARTIFACT_PAGE_ASPECT`.
   - Lower `_MAX_ARTIFACT_PAGE_WIDTH_IN`.
   - Keep the existing `16px`/`12pt` typography and `0.18in` margin unless tests reveal a reason to adjust them.

3. Update focused tests.
   - Adjust `test_artifact_image_area_reserves_viewer_rows()` to expect the horizontal gutter.
   - Add or update coverage showing `reserved_columns=0` remains possible for explicit callers/tests.
   - Adjust `test_artifact_markdown_pdf_profile_uses_image_area_aspect()` and
     `test_render_markdown_artifact_passes_pane_aware_profile()` to expect the narrower page profile.
   - Keep `kitten_icat_command()` tests focused on honoring the supplied `ArtifactImageArea`; the command builder should
     not independently change dimensions.

4. Verify the focused surface.
   - Run `pytest tests/ace/tui/artifact_viewer/test_rendering.py tests/ace/tui/artifact_viewer/test_loops.py`.
   - Run `pytest tests/test_markdown_pdf.py` to confirm attachment PDF defaults and custom profile behavior still pass.

5. Run repository checks.
   - Run `just install` first if the workspace needs setup.
   - Run `just check` before finishing because the repo instructions require it after code changes.

## Acceptance Criteria

- Markdown artifact PDFs opened in the tmux artifact pane no longer target the full pane width.
- The generated Markdown artifact page is less wide than the current `11in`/`3.0` aspect cap for wide pane shapes.
- Mobile/notification Markdown PDF generation remains unchanged.
- Existing direct PDF artifacts are not re-authored or resized at render time beyond the viewer's bounded image
  placement.
- Focused viewer and Markdown PDF tests pass, followed by `just check`.

## Risks And Tradeoffs

- A narrower artifact profile can increase Markdown pagination. That is acceptable for interactive reading if it avoids
  clipping and preserves readability.
- The exact gutter size is a tuning choice. A small fixed value is preferable to deriving it from percentages because it
  addresses terminal edge behavior without wasting much space in normal panes.
- If the underlying issue is entirely in Kitty/tmux placement, the horizontal gutter is the key fix; if it is primarily
  document geometry, the profile cap is the key fix. Applying both keeps the change robust while staying narrowly scoped
  to the artifact viewer.

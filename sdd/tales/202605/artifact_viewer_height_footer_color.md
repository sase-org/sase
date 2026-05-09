---
title: Artifact Viewer Full-Height Markdown Pages And Stable Footer Color
create_time: 2026-05-08 22:12:14
status: done
prompt: sdd/prompts/202605/artifact_viewer_height_footer_color.md
---

# Plan: Fill The Artifact Viewer Pane More Completely

## Goal

Make Markdown artifacts render as tall as the current artifact viewer pane safely allows, and make the bottom footer use
one deterministic, readable color on every refresh.

The current behavior still leaves a large vertical gap between the rendered Markdown page and the footer in wide tmux
panes. The footer also appears to inherit whatever terminal foreground state was left behind by the image drawing path,
which makes its color vary across refreshes.

## Diagnosis

The current Markdown artifact path is:

1. `run_artifact_sequence_loop()` computes an `ArtifactImageArea` from the terminal cell size.
2. `render_artifact_pages(..., image_area=area)` converts Markdown to a temporary PDF using
   `artifact_markdown_pdf_profile_for_image_area(area)`.
3. `pdftoppm` converts the PDF page to a PNG.
4. `kitten icat --place <columns>x<rows>@<left>x<top>` draws that PNG into the reserved image rectangle.
5. `_move_cursor_below_image()` positions the footer below the reserved rectangle.

The cursor/footer placement is now bounded by the reserved rectangle, but the Markdown image itself does not necessarily
fill that rectangle. The current PDF profile caps the physical page aspect ratio at `1.75` and caps width at `8.50in`.
In a wide terminal, that produces `8.50in x 4.86in`. Because terminal cells are taller than they are wide, a page image
with a `1.75` pixel aspect ratio can still be too wide for the actual pixel shape of the cell rectangle, so `icat` fits
by width and leaves unused rows below the image.

The footer color issue is independent. `print_page_prompt()` uses plain `print()`, so it relies on whatever SGR state is
active after Rich header rendering and Kitty image output. It should explicitly reset/style the prompt instead.

## Design

### Height

Replace the fixed `1.75` aspect-cap behavior for artifact Markdown profiles with a target aspect ratio derived from the
actual terminal placement rectangle:

- Add a small terminal-cell pixel aspect helper used by the viewer profile code.
- Prefer runtime terminal pixel metadata when available from `TIOCGWINSZ` (`xpixels`, `ypixels`, `columns`, `rows`). The
  cell aspect is `(xpixels / columns) / (ypixels / rows)`.
- Fall back to a conservative constant near typical monospace terminal cells when pixel metadata is unavailable. A value
  around `0.50` is a better starting point than treating cells as square and should make the page substantially taller.
- Compute the target PDF aspect as: `target_aspect = (image_area.columns / image_area.rows) * cell_pixel_aspect`
- Clamp only to sane document bounds, not to the old wide-pane `1.75` behavior. Keep the existing minimum aspect guard
  so very narrow panes do not create extreme pages.
- Keep the width cap at `8.50in` for readability, then compute page height from `height = width / target_aspect`.
- Keep `kitten icat --place` unchanged. It remains the hard pane-overflow guard; the page image is still bounded by the
  reserved cell rectangle. If the computed page is slightly too tall because a terminal reports poor pixel metadata,
  `icat` will fit by height and leave horizontal space rather than overflowing into the footer.

This should use nearly all available vertical image rows in the provided pane shape while preserving the current bounded
image area and footer placement contract.

### Footer Color

Introduce a dedicated footer renderer instead of bare `print()`:

- Add constants for footer styling in `_viewer_loop.py`.
- Use a stable, restrained SASE accent color for the footer. I would use dim gold, e.g. `#D7AF5F`, because it matches
  existing artifact/header accents without competing with the image.
- Optionally render key tokens (`n`, `p`, `N`, `P`, `r`, `q`) in a stronger accent such as bold `#00D7AF`; keep the
  whole footer readable as a single status line.
- Explicitly reset terminal styling before and after rendering the footer, either through Rich's styled `Text` output or
  a small ANSI wrapper, so refreshes cannot inherit random foreground colors from `icat`.
- Preserve the current prompt text and available-key logic.

## Implementation Steps

1. Update `_viewer_render.py`.
   - Add a helper to resolve terminal cell pixel aspect, with injectable/testable inputs if practical.
   - Change `artifact_markdown_pdf_profile_for_image_area()` to derive page aspect from the image area and cell aspect.
   - Keep width, margin, and font settings unchanged.
   - Remove or reduce reliance on `_ARTIFACT_PAGE_HEIGHT_PER_ROW_IN` and `_MAX_ARTIFACT_PAGE_ASPECT` if the new aspect
     calculation makes them obsolete.

2. Update `_viewer_loop.py`.
   - Replace `print_page_prompt()`'s plain `print()` with a deterministic styled renderer.
   - Ensure the output begins from a reset style and ends reset.
   - Keep call sites and navigation behavior unchanged.

3. Update tests.
   - Rendering tests should cover:
     - Wide pane profiles become taller than the current `8.50in x 4.86in` case.
     - The computed page aspect tracks the pane's cell-adjusted aspect.
     - Width remains capped at `8.50in`.
     - Invalid/zero image areas still return `None`.
   - Add tests for the pixel-aspect fallback and, if the runtime helper is injectable, the nonzero pixel metadata path.
   - Loop/footer tests should cover:
     - The prompt text remains unchanged after stripping ANSI.
     - The footer output contains the selected stable color/reset sequence when color output is enabled.
     - Cursor positioning still happens before footer text in both single-page and artifact-sequence loops.

4. Verify.
   - Run focused tests:
     `.venv/bin/python -m pytest tests/ace/tui/artifact_viewer/test_rendering.py tests/ace/tui/artifact_viewer/test_loops.py tests/test_markdown_pdf.py`
   - Run `just install` first if the workspace virtualenv is stale.
   - Run `just check` before finishing because this will change source files.

## Acceptance Criteria

- Markdown artifact pages use substantially more of the available image-area height in wide panes like the provided
  snapshot.
- The image still cannot overflow into the footer because `kitten icat --place` remains bounded to the calculated image
  area.
- The footer appears below the image area and has the same chosen color on every refresh.
- Existing navigation text and key availability are unchanged.
- Focused tests and `just check` pass.

## Risks And Tradeoffs

- Terminal pixel dimensions are not always reported through `TIOCGWINSZ`, especially through tmux or older terminals.
  The fallback cell aspect should therefore be conservative and deterministic.
- If the fallback makes a page slightly too tall on a terminal with unusually square cells, the failure mode is
  horizontal margin inside the image area, not overflow.
- A taller page reduces pagination and fills the pane better, but it can reduce horizontal image scale if pushed too
  far. Deriving aspect from the placement rectangle avoids arbitrary height increases.

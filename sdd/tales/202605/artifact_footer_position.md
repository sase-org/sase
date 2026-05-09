---
title: Artifact Footer Position And Taller Markdown PDFs
create_time: 2026-05-08 21:58:20
status: done
prompt: sdd/prompts/202605/artifact_footer_position.md
---

# Plan: Keep Artifact Viewer Footer Below The Rendered Page

## Goal

Fix the artifact viewer regression where the footer/prompt renders in the middle of the displayed image after the tmux
PDF width change, and make pane-aware Markdown artifact PDF pages a bit taller.

The fix should preserve the successful narrower width behavior from `4beb99b8` while making the terminal placement
contract explicit: the image should occupy the reserved image area, and the footer should be printed below that area.

## Diagnosis

The current tmux artifact viewer path is:

1. `view_artifact_files_in_tmux_pane()` launches `python -m sase.ace.tui.graphics.viewer` in a split pane.
2. `run_artifact_sequence_loop()` clears the pane, prints a Rich header, computes `artifact_image_area()`, then calls
   `kitten_icat_command()` with `--place <columns>x<rows>@<left>x<top>`.
3. `kitten icat --place` paints the image into that fixed rectangle, but it does not make the shell cursor land after
   the placed rectangle.
4. `print_page_prompt()` then prints a leading newline and the footer at the current cursor position.

The root cause is therefore cursor placement, not the PDF image dimensions. The loop computes enough reserved rows for
header, image, and footer, but it never moves the cursor to the bottom of the image area before printing the footer.
After the header, the cursor is still near the top of the pane; the next newline can land inside the image rectangle, so
the footer overlays the rendered page.

The previous width fix made this easier to notice because the page now fits horizontally, but it did not change the
cursor semantics of `kitten icat`.

## Design

Add a small viewer-loop helper that prints an ANSI cursor-position escape to move the terminal cursor to the row just
below the image rectangle before printing the footer.

Important details:

- `ArtifactImageArea.top`, `left`, `columns`, and `rows` are kitty placement cell coordinates, with `top` behaving as a
  zero-based row offset for the image placement.
- The image occupies rows `top` through `top + rows - 1`.
- Because `print_page_prompt()` intentionally starts with `\n`, move the cursor to the image's last row (`top + rows` in
  one-based terminal coordinates) before calling it. The leading newline then places the prompt on the first row below
  the image.
- Keep the footer behavior reusable across both `run_artifact_page_loop()` and `run_artifact_sequence_loop()`.
- Keep `kitten_icat_command()` unchanged; it should continue to honor the supplied image area without side effects.

For the PDF height request, adjust only the artifact-viewer Markdown profile:

- Increase the maximum pane-aware Markdown PDF page height slightly.
- Increase the per-terminal-row height factor slightly so normal tmux pane shapes produce taller pages.
- Leave attachment/mobile Markdown PDF defaults unchanged.
- Keep the current 8.5in width cap and 1.75 aspect cap from the width fix.

## Implementation Steps

1. Update `_viewer_loop.py`.
   - Add a helper such as `_move_cursor_below_image(image_area)` that writes the correct ANSI cursor-position escape to
     stdout and flushes.
   - Call it after successful `kitten_icat_command()` execution and before `print_page_prompt()` in both loop paths.
   - Keep behavior deterministic for tests by making the helper visible through captured stdout rather than by adding
     subprocess commands.

2. Update loop tests.
   - Add focused assertions that the page loop and artifact sequence loop emit the cursor-position escape before the
     footer text.
   - Avoid broad terminal-emulator assumptions; assert only the calculated row for known `ArtifactImageArea` inputs.
   - Keep existing command-order tests intact so image rendering still uses the same `kitten icat` commands.

3. Update `_viewer_render.py`.
   - Raise `_MAX_ARTIFACT_PAGE_HEIGHT_IN` modestly.
   - Raise `_ARTIFACT_PAGE_HEIGHT_PER_ROW_IN` modestly.
   - Recalculate expected test values from the existing profile formula.

4. Update rendering tests.
   - Adjust `artifact_markdown_pdf_profile_for_image_area()` expectations to the new taller page height.
   - Keep tests confirming the width remains 8.5in and the margin/font choices are unchanged.
   - Keep Markdown attachment PDF tests unchanged except for running them to prove defaults were not affected.

5. Verify.
   - Run focused tests:
     `pytest tests/ace/tui/artifact_viewer/test_rendering.py tests/ace/tui/artifact_viewer/test_loops.py tests/test_markdown_pdf.py`
   - Run `just install` first if the workspace environment is missing dependencies.
   - Run `just check` before finishing because repository instructions require it after source changes.

## Acceptance Criteria

- The artifact footer/prompt appears below the image area in both single-page and multi-artifact viewer loops.
- The image placement command remains bounded to the same calculated image area.
- Pane-aware Markdown artifact PDFs are a bit taller while remaining capped at 8.5in wide.
- Mobile/notification Markdown PDF generation remains unchanged.
- Focused tests and `just check` pass.

## Risks And Tradeoffs

- ANSI cursor positioning assumes a normal terminal control sequence environment, which is already required by this
  interactive viewer.
- If the footer has more than one terminal row on very narrow panes, the existing reserved-row budget may still need
  future tuning. The immediate bug is the footer starting inside the image rectangle.
- Taller pages can reduce pagination but may slightly shrink the image scale in short panes. The change should be modest
  to keep the width fix's readability gains.

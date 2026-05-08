---
title: Tmux Markdown Artifact PDF Profile
create_time: 2026-05-08 18:44:13
status: done
prompt: sdd/prompts/202605/tmux_markdown_artifact_pdf_profile.md
---

# Plan: Tmux-Friendly Markdown Artifact Rendering

## Goal

Keep the recently improved mobile Markdown PDF defaults for notification attachments, but make Markdown artifacts opened
in the tmux artifact pane render as a large, readable page image that uses most of the pane while leaving room for the
viewer header and footer.

The key distinction is viewing context. A phone attachment benefits from a narrow fixed page. A tmux side pane benefits
from a page and display target derived from the current terminal cell geometry.

## Current Behavior

Markdown artifacts use this path:

1. `src/sase/ace/tui/graphics/_viewer_render.py::render_artifact_pages()`
2. `render_markdown_pdf(path, cache_dir / "<name>.pdf")`
3. `pdftoppm -png <pdf> <page-prefix>`
4. `src/sase/ace/tui/graphics/_viewer_loop.py` displays each PNG with `kitten icat`

`render_markdown_pdf()` currently has one built-in profile in `src/sase/attachments/markdown_pdf.py`:

- page size: `4.25in x 7in`
- margin: `0.22in`
- body font: `16px` in CSS / `12pt` in LaTeX fallback

That is good for mobile attachments, but it means the artifact viewer is using a phone-shaped document even when the
viewer is running in a much larger terminal pane. The display command also does not explicitly place/scale the image to
the available terminal cells, so the PNG can fail to occupy the useful pane area.

## Design

Introduce an explicit Markdown PDF render profile while preserving the current mobile profile as the default.

Add a small internal profile object in `src/sase/attachments/markdown_pdf.py`, for example:

- `MarkdownPdfProfile`
- built-in `MOBILE_MARKDOWN_PDF_PROFILE`
- dynamically constructed artifact-viewer profile

Keep the existing public behavior:

- `render_markdown_pdf(source, dest)` still uses the mobile profile by default.
- `render_markdown_pdf_attachments(...)` remains unchanged semantically.
- explicit `css_path` override remains supported.

For the artifact viewer only, compute a pane-aware profile from the terminal size:

- Reserve rows for the Rich header panel, the blank line around the prompt, and the footer prompt.
- Use the remaining rows and current columns as the target page aspect ratio.
- Keep margins small.
- Keep body text large, at least the current mobile-equivalent size.
- Clamp the page dimensions to sane bounds so unusual pane sizes do not produce absurd PDFs.

This should live in the viewer layer, not in attachment generation, because pane size is presentation context.

Also teach the viewer loop to display via an explicit `kitten icat --place <cols>x<rows>@0x0 <page.png>`-style target
when it knows the available image rows. That makes the rasterized page intentionally fill the useful pane area instead
of relying on terminal defaults. The header is printed first, so the placement should start at the cursor-relative image
area or use a simpler bounded mode if Kitty’s CLI handles placement after printed text reliably. If placement proves
fragile, prefer bounded `--scale-up --align left` options that respect the current cursor.

## Implementation Steps

1. Refactor the Markdown PDF constants into a profile.
   - Preserve current mobile values exactly as the default.
   - Add profile-derived CSS generation for dynamic artifact profiles, likely by writing a temporary CSS file alongside
     the temporary PDF cache.
   - Keep the packaged `markdown_pdf.css` for the default mobile profile.

2. Extend `render_markdown_pdf()`.
   - Add an optional keyword-only `profile` parameter.
   - Build Pandoc wkhtmltopdf and LaTeX options from the profile.
   - If a caller passes `css_path`, let it override profile CSS as it does today.

3. Add artifact-viewer layout calculation.
   - In `_viewer_loop.py`, compute available image columns/rows from `shutil.get_terminal_size()`.
   - Use a conservative reserved-row constant for the header/footer area.
   - Pass the resulting dimensions into `_viewer_render.render_artifact_pages()`.

4. Render Markdown artifacts with the pane-aware profile.
   - In `_viewer_render.py`, when mode is `markdown`, derive a PDF profile from the available image area.
   - Keep direct PDF artifacts unchanged; they should be displayed as authored.
   - Keep image artifacts unchanged except for the display sizing behavior.

5. Scale displayed pages to the available image area.
   - Update the `kitten icat` invocation in `_viewer_loop.py` to target the computed image area.
   - Keep tests injectable by threading the dimensions through existing `run_command`-based tests rather than requiring
     a real terminal.

6. Add focused tests.
   - `tests/test_markdown_pdf.py`: default profile remains mobile; custom profile changes page size, margins, CSS, and
     LaTeX variables; explicit `css_path` still overrides generated/profile CSS.
   - `tests/ace/tui/test_artifact_viewer.py`: terminal size produces expected available image dimensions; Markdown
     rendering receives a pane-aware profile; `kitten icat` is invoked with the bounded placement/scale options.
   - Existing mobile PDF and tmux pane launch tests should continue to pass.

7. Verify.
   - Run `pytest tests/test_markdown_pdf.py tests/ace/tui/test_artifact_viewer.py`.
   - Run `just install` if needed for the workspace.
   - Run `just check` before finishing because repo memory requires it after code changes.

## Risks And Tradeoffs

- Dynamic page geometry can change pagination between terminal sizes. That is acceptable for interactive artifact
  viewing, but it should not affect persisted notification PDFs.
- `kitten icat --place` behavior can be sensitive to cursor position and tmux. The implementation should keep the
  command construction isolated and covered by tests so it can be adjusted if manual testing reveals a better Kitty
  option combination.
- Wider pages can make text smaller if the display step scales the full page down. The artifact profile must keep large
  font defaults and should favor fitting the pane’s usable aspect ratio rather than simply making a letter-sized page.
- LaTeX fallback styling is less controllable than wkhtmltopdf. It should still receive the same page dimensions and
  readable font size, but wkhtmltopdf remains the best path for narrow/wrapped code.

## Acceptance Criteria

- Mobile/notification Markdown PDFs keep the current narrow, readable defaults.
- Markdown artifacts opened in the tmux artifact pane produce page images sized for the pane’s usable columns and rows.
- The displayed page image uses most of the pane while leaving the Rich header and prompt/footer visible.
- Body text remains at least as readable as today.
- Existing missing-tool and conversion-failure behavior remains non-fatal.

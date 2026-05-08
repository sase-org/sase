---
create_time: 2026-05-08 12:12:19
status: done
prompt: sdd/prompts/202605/mobile_markdown_pdfs.md
---
# Plan: Small-Screen Markdown PDF Defaults

## Goal

Improve the PDFs SASE generates from Markdown files so they are readable by default in the places they are actually
viewed: narrow tmux split panes and smartphones. The current renderer produces conventional document PDFs: `wkhtmltopdf`
uses a wide default page unless styled, and the LaTeX fallback uses `geometry:margin=1in`. That wastes too much width
and forces viewers to scale the content down.

This plan covers the core Markdown file attachment renderer in `src/sase/attachments/markdown_pdf.py`, which is used for
agent-generated Markdown PDFs and the ACE Markdown artifact viewer. The xprompt catalog renderer in
`src/sase/xprompt/_catalog_render.py` is a separate HTML catalog path and should remain out of scope unless we decide
the same small-screen profile should apply there too.

## Design

Use a single built-in "mobile/narrow" PDF profile for Markdown file PDFs:

- Narrow portrait page, roughly phone/ebook sized, instead of letter/A4. A good initial target is about `4.25in` wide
  and `7in` tall.
- Small margins, about `0.22in`, so the page width is used for content.
- Larger readable body text: about `12pt` for LaTeX engines and `16px` CSS for the wkhtmltopdf HTML path.
- Moderate line height, around `1.3` to `1.35`, to preserve scanability without wasting vertical space.
- Code and tables should degrade toward wrapping/scroll-like block layout rather than clipping off the right edge where
  the engine supports it.

Keep the renderer best-effort and dependency-neutral. Do not add a Python PDF stack or require a new system dependency.
Pandoc plus the existing engine order (`wkhtmltopdf`, then `xelatex`, then `pdflatex`) remains the contract.

## Implementation Steps

1. Add explicit layout constants to `src/sase/attachments/markdown_pdf.py`.
   - Define page width, page height, margin, body font, line height, and code font values in one place.
   - Keep the values module-private initially; this should be a better default, not a new public configuration surface.

2. Add a packaged CSS file for the wkhtmltopdf path.
   - Suggested path: `src/sase/attachments/markdown_pdf.css`.
   - Include `@page` size/margins and readable defaults for `body`, headings, links, blockquotes, lists, code blocks,
     inline code, tables, images, and horizontal rules.
   - Use wrapping rules for `pre`, `code`, table cells, and long URLs so narrow pages do not lose content off the right
     edge.
   - Load it by default in `render_markdown_pdf()` when the caller does not pass `css_path`; preserve the existing
     `css_path` override for tests or future callers.

3. Pass mobile-friendly `wkhtmltopdf` engine options through Pandoc.
   - Add `--pdf-engine-opt` entries for page width, page height, and all four margins.
   - Keep `--metadata title=<source.stem>`.
   - Keep `--highlight-style=tango`.
   - Continue appending a caller-provided CSS path only when the file exists.

4. Replace the LaTeX fallback's `geometry:margin=1in`.
   - Use Pandoc variables such as `-V geometry:paperwidth=4.25in,paperheight=7in,margin=0.22in`.
   - Use `-V fontsize=12pt` and a modest `linestretch` value.
   - Avoid complex LaTeX header customization unless testing proves it is needed; engine availability and non-fatal
     fallback behavior matter more than perfect code wrapping in the fallback engines.

5. Update tests in `tests/test_markdown_pdf.py`.
   - Adjust command assertions for the first engine test to expect CSS and wkhtmltopdf page/margin options.
   - Add a focused test that the default CSS is used when no `css_path` is passed.
   - Add a test that an explicit `css_path` still overrides the packaged default.
   - Add a LaTeX fallback test assertion for the new geometry/font variables.
   - Keep the existing failure/cleanup tests intact.

6. Update docs.
   - In `docs/agent_images.md`, describe the small-screen Markdown PDF defaults under the Markdown PDF attachment
     contract.
   - In `docs/axe.md` or `docs/notifications.md`, keep the note brief: generated Markdown PDFs are optimized for narrow
     viewers with small margins and larger type.

7. Verify.
   - Run the focused Markdown PDF tests first: `pytest tests/test_markdown_pdf.py`.
   - Run `just install` if the workspace has not been refreshed.
   - Run `just check` before finishing because this repo requires it after code changes.
   - If `pandoc` and a PDF engine are installed locally, optionally generate one sample Markdown PDF and inspect the
     Pandoc command behavior. The unit tests should not depend on these tools.

## Risks and Tradeoffs

- A narrower page increases page count. That is acceptable for the target viewing contexts because readable fit-to-width
  text matters more than print-style pagination.
- `wkhtmltopdf` CSS support is imperfect. Passing both CSS and explicit engine page/margin options reduces dependence on
  `@page` support.
- LaTeX code block wrapping is harder to make robust without template/header complexity. The first pass should improve
  page size, margins, and font size for all engines, while relying on the preferred wkhtmltopdf path for the best narrow
  layout.
- Changing defaults affects both completion notification PDFs and on-demand ACE Markdown artifact rendering, which is
  desirable because both are narrow-screen workflows.

## Acceptance Criteria

- Generated Markdown PDFs use a narrow page, small margins, and larger body text by default.
- The default applies without callers needing to pass a CSS path.
- Explicit `css_path` callers still work.
- Missing tools and conversion failures remain non-fatal and leave no partial PDFs.
- Existing Markdown PDF attachment ordering, sidecar index behavior, and `done.json.markdown_pdf_paths` behavior are
  unchanged.

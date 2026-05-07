# Markdown `V` View Image Keymap Research

Research date: 2026-05-07

## Question

Can the existing `V` view-image keymap also work for Markdown files by converting the selected Markdown file to PDF and
showing the result in Kitty?

Short answer: yes, but the reliable implementation is not "show a PDF in Kitty" directly. It should be:

1. Resolve the currently selected Markdown file.
2. Render it to a cached PDF with the existing `sase.attachments.markdown_pdf.render_markdown_pdf()`.
3. Rasterize one PDF page to a temporary PNG.
4. Suspend Textual and run `kitten icat` on the PNG.

Kitty's `icat` kitten is an image-display utility. Its docs describe supported builtin image formats as
PNG/JPG/GIF/BMP/TIFF/WEBP, with ImageMagick required for a broader set of image types; they do not make PDF a
portable first-class target. For SASE, rendering the PDF page to a PNG ourselves keeps the behavior deterministic and
avoids depending on host ImageMagick/Ghostscript policy.

## Existing SASE Shape

Already implemented:

- `src/sase/default_config.yml` binds `view_image: "V"`.
- `src/sase/ace/tui/graphics/viewer.py` validates image files and opens them with `kitten icat` while the app is
  suspended by the caller.
- `src/sase/ace/tui/widgets/file_panel/__init__.py::get_current_file_path()` returns the currently selected static file
  path in the agent file panel.
- `src/sase/ace/tui/widgets/file_panel/__init__.py::get_current_image_path()` narrows that file path to supported image
  extensions.
- `src/sase/ace/tui/actions/agents/_panels.py::action_view_image()` gets the current image from `AgentDetail`, suspends
  Textual, and runs the viewer helper. If no image is visible, it falls back to attempt view when applicable.
- `src/sase/ace/tui/modals/notification_modal_attachments.py::action_view_image()` does the same for notification
  attachments.
- `src/sase/attachments/markdown_pdf.py::render_markdown_pdf()` already converts `.md` / `.markdown` to PDF using
  `pandoc`, trying `wkhtmltopdf`, `xelatex`, then `pdflatex`.
- `src/sase/attachments/markdown_pdf.py::render_markdown_pdf_attachments()` writes generated PDFs under
  `artifacts_dir/markdown_pdfs/` and records a sidecar `index.json`.
- `pyproject.toml` already depends on `pillow`, which is enough for image resizing/saving after a PDF page has been
  rasterized.

Important gap: there is no current PDF rasterizer dependency. The April TUI image/PDF research recommended
`pypdfium2` because it is permissively licensed and ships PDFium in wheels for common platforms.

## Kitty Findings

`kitten icat` is the right primitive for the current "suspend Textual, show something, wait for a key" UX. Kitty's docs
also warn that `icat` reads and writes the TTY, so host programs must stop doing TTY I/O while it runs. The existing
SASE implementation already follows that rule by calling the helper inside `self.suspend()`.

For SSH, Kitty's `icat --transfer-mode stream` is the safest option because file and shared-memory transfer modes do not
work across a remote session. The current helper leaves transfer mode on `detect`, which is probably fine locally but
less explicit than it could be for SASE's common SSH/tmux workflow.

If we later want inline rendering inside Textual rather than a suspended full-screen view, the April 2026 research still
applies: use Kitty graphics protocol with Unicode placeholders, not direct cursor placement. That is a different project
from extending `V`.

## PDF Rasterization Options

Recommended for SASE: `pypdfium2`.

Why:

- It is a Python binding to PDFium with liberal licensing.
- It provides helpers for rendering PDF pages and converting bitmaps to PIL images.
- It avoids the system `poppler-utils`, ImageMagick, or Ghostscript dependency stack.

Relevant API shape:

```python
import pypdfium2 as pdfium

pdf = pdfium.PdfDocument(str(pdf_path))
page = pdf[0]
width, height = page.get_size()
bitmap = page.render(scale=scale)
image = bitmap.to_pil()
image.save(str(png_path))
```

Threading caveat: PDFium is not thread-safe. If rasterization happens in Textual workers, guard PDFium calls with a
module-level lock or run them in one process. The first version can rasterize synchronously while the TUI is suspended,
which is simpler and avoids concurrent PDFium calls.

Avoid:

- PyMuPDF as a default dependency, because its AGPL/commercial licensing is a bad fit for the MIT SASE project.
- `pdf2image`/Poppler for v1, because it adds system dependencies and shell-outs.
- `kitten icat markdown.pdf` directly, because support depends on ImageMagick/Ghostscript being installed and configured.

## Recommended Implementation

Add one markdown-aware helper instead of teaching `view_image_file()` about non-image files:

```text
src/sase/ace/tui/graphics/markdown_viewer.py
```

Responsibilities:

- Validate `.md` / `.markdown`.
- Choose a cache location.
- Call `render_markdown_pdf(source, pdf_dest)`.
- Rasterize page 1 of the PDF to PNG.
- Run the existing image viewer on the PNG.
- Return the same `ImageViewerResult` shape so callers can keep the current notification/toast behavior.

Suggested cache policy:

- For agent artifacts, prefer an artifact-local cache, for example
  `<artifacts_dir>/markdown_viewer/<source-cache-key>/source.pdf` and `page-1.png`.
- If the current surface does not know an artifacts dir, use `~/.sase/cache/markdown_viewer/`.
- Key by absolute source path plus `mtime_ns` and file size. This avoids stale renders without hashing large files.
- Delete old cache entries opportunistically by age or cap total entries later; v1 can leave cache files behind.

Suggested first-page behavior:

- V1 displays the first page only.
- If page count is greater than 1, print a small pre-`icat` line after returning or in the "press any key" prompt:
  `Rendered page 1 of N`.
- Page navigation should be a follow-up feature. A real PDF viewer needs page state, zoom, re-rendering, and key handling;
  that is larger than extending `V`.

Suggested display command:

```bash
kitten icat --transfer-mode stream "$png_path"
```

Then keep the existing "Press any key to return to SASE..." behavior.

## TUI Integration Points

Agents tab:

- Add `AgentFilePanel.get_current_markdown_path() -> str | None`, parallel to `get_current_image_path()`.
- Add `AgentDetail.get_current_markdown_path()` that delegates to the file panel only when visible.
- Extend `action_view_image()`:
  - image path: current behavior;
  - markdown path: suspend, render PDF/PNG, then `icat`;
  - neither: existing attempt-view fallback.

Notification modal:

- Add `_get_current_markdown_path()` next to `_get_current_image_path()`.
- Extend `action_view_image()`:
  - image attachment: current behavior;
  - markdown attachment: render and view;
  - neither: `No image or Markdown file visible`.

Naming:

- Keep the action name `view_image` and key `V` for compatibility.
- User-facing help could say `View image/Markdown` or `View rendered file`.
- Internally, avoid broadening `is_supported_image_path()` to Markdown. Markdown is a source document that needs a
  conversion pipeline, not an image.

## Failure Modes To Surface

Return warnings rather than raising:

- Markdown file missing.
- `pandoc` missing.
- No PDF engine found.
- PDF render failed.
- `pypdfium2` missing, if dependency is optional.
- PDF has zero pages or is encrypted/unsupported.
- PNG save failed.
- `kitten` missing.
- `kitten icat` exited non-zero.

The current `render_markdown_pdf()` returns `None` for tool and conversion failures, so the helper can preserve that
style and report a compact message like `Could not render Markdown PDF`.

## Test Plan

Focused tests should cover behavior without running real `pandoc`, PDFium, or Kitty:

- `get_current_markdown_path()` returns expanded existing Markdown paths and rejects live diffs, images, text files, and
  missing files.
- Markdown helper calls `render_markdown_pdf()` with a deterministic cache destination.
- Markdown helper rasterizes page 1 and calls `view_image_file()` with the PNG path.
- Markdown helper reuses a fresh cache entry when source size/mtime has not changed.
- Agent `action_view_image()` prefers real images over Markdown and prefers Markdown over attempt-view fallback.
- Notification modal `action_view_image()` opens Markdown attachments when the selected file is Markdown.
- Missing `pandoc` / failed PDF render yields warning and does not call `kitten`.
- If `pypdfium2` is added as a required dependency, run `just install` so `uv.lock` is updated and checked.

## Open Decisions

- Add `pypdfium2` as a required dependency, or make Markdown `V` support optional with a clear missing-dependency
  warning? Required is simpler and likely acceptable given the project already depends on `pillow`.
- Should `V` display page 1 only, or should it launch a small one-off PDF viewer loop with `n`/`p` page navigation?
  Page 1 is the right v1 unless users immediately ask for multipage navigation.
- Should `view_image_file()` force `--transfer-mode stream` globally? This helps SSH and should still work locally, but
  it may be slower than file/shared-memory transfer for very large local images.
- Where should cache cleanup live? A shared `~/.sase/cache` cleanup utility may be useful beyond this feature.

## Sources

- Local: `src/sase/attachments/markdown_pdf.py`
- Local: `src/sase/ace/tui/graphics/viewer.py`
- Local: `src/sase/ace/tui/actions/agents/_panels.py`
- Local: `src/sase/ace/tui/modals/notification_modal_attachments.py`
- Local: `sdd/research/202604/tui_image_pdf_support.md`
- Kitty `icat` docs: https://sw.kovidgoyal.net/kitty/kittens/icat/
- Kitty graphics protocol docs: https://sw.kovidgoyal.net/kitty/graphics-protocol/
- pypdfium2 introduction: https://pypdfium2.readthedocs.io/en/stable/readme.html
- pypdfium2 Python API: https://pypdfium2-team.github.io/pypdfium2/python_api.html
- termpdf.py reference project: https://github.com/dsanson/termpdf

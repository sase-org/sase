# Markdown `V` View Image Keymap Research

Research date: 2026-05-07 (revised)

## Question

Can the existing `V` view-image keymap also work for Markdown files by converting the selected Markdown file to PDF and
showing the result in Kitty?

Short answer: yes, but the reliable implementation is not "show a PDF in Kitty" directly. It should be:

1. Resolve the currently selected Markdown file.
2. Get a PDF for it — preferring an already-cached agent artifact, falling back to
   `sase.attachments.markdown_pdf.render_markdown_pdf()`.
3. Rasterize the PDF page(s) to PNG with `pypdfium2`.
4. Suspend Textual and run `kitten icat --hold` on the PNG(s).

Kitty's `icat` kitten is an image-display utility. Its docs describe supported builtin formats as
PNG/JPG/GIF/BMP/TIFF/WEBP, with ImageMagick required for a broader set of image types and **PDF only via ImageMagick
+ Ghostscript** delegate; PDF is therefore not a portable first-class target. Rendering the PDF to PNG(s) ourselves
keeps the behavior deterministic and avoids depending on host ImageMagick/Ghostscript policy.

## Existing SASE Shape

Already implemented:

- `src/sase/default_config.yml` binds `view_image: "V"` (line 88).
- `src/sase/ace/tui/graphics/viewer.py` validates image files and runs `kitten icat` inside a small bash wrapper that
  prints "Press any key to return to SASE..." and waits on `read -r -n 1`.
- `src/sase/ace/tui/graphics/images.py::is_supported_image_path()` accepts `.png .jpg .jpeg .webp .gif` only.
- `src/sase/ace/tui/widgets/file_panel/__init__.py::get_current_file_path()` /
  `get_current_image_path()` return the focused agent file panel selection.
- `src/sase/ace/tui/actions/agents/_panels.py::action_view_image()` (line 307) suspends Textual, calls the viewer,
  and falls back to attempt-view toggle when no image is visible.
- `src/sase/ace/tui/modals/notification_modal_attachments.py::action_view_image()` (line 207) does the same for
  notification attachments.
- `src/sase/attachments/markdown_pdf.py::render_markdown_pdf()` converts `.md` / `.markdown` to PDF using `pandoc`,
  trying `wkhtmltopdf`, `xelatex`, then `pdflatex`, with a 120s default timeout and atomic temp-file replacement.
- `src/sase/attachments/markdown_pdf.py::render_markdown_pdf_attachments()` writes generated PDFs under
  `artifacts_dir/markdown_pdfs/` and emits a sidecar `index.json` with `source_path → pdf_path` records.
- `pyproject.toml` already depends on `pillow`, sufficient for PNG save/resize after PDF rasterization.
- `sase.core.paths.get_sase_tmpdir()` is already used by `action_edit_panel` for ephemeral files outside an artifacts
  dir; the Markdown viewer should use it for the same reason.

Important gap: there is no PDF rasterizer dependency yet. The April 2026 research
(`sdd/research/202604/tui_image_pdf_support.md`) recommended `pypdfium2` (Apache-2.0 / BSD-3, PDFium ships in the
wheel, no system deps) and rejected PyMuPDF (AGPL incompatible with MIT SASE) and `pdf2image` (system
`poppler-utils` dependency, ~10× slower). Reuse that decision; do not re-litigate it here.

## Kitty Findings

`kitten icat` is the right primitive for the current "suspend Textual, show something, wait for a key" UX. Kitty's docs
also warn that `icat` reads and writes the TTY, so host programs must stop doing TTY I/O while it runs. The existing
SASE viewer already follows that rule by calling the helper inside `self.suspend()`.

Three icat flags worth using for the Markdown path:

- `--hold` — `icat` waits for a key press before exiting and clears the image on return. This **replaces the bash
  `read -r -n 1` wrapper** the current viewer uses, simplifying the helper to a single subprocess call. The existing
  image viewer can be migrated to it independently; nothing about Markdown forces the choice.
- `--align center` — centers a page-rendered PNG horizontally in the terminal. Looks better than the default
  left-aligned placement for a portrait page.
- `--transfer-mode stream` — required over SSH because file/temp/shared-memory transports assume a shared
  filesystem with the terminal emulator. The current SASE helper leaves transfer mode on `detect`, which is fine
  locally but less explicit than it could be for SASE's common SSH/tmux workflow. Forcing stream globally is safe.

Multi-image input: `kitten icat page-1.png page-2.png` displays the images sequentially in the scrollback. Combined
with `--hold`, this gives a usable "scroll with PageUp/PageDown after icat exits" multi-page UX without writing a key
loop ourselves. It is not a true paginated viewer — the user scrolls Kitty's own scrollback — but it is one
subprocess call and it works over SSH.

If we later want true page-at-a-time navigation (`n`/`p`/zoom), the right shape is a small in-suspend loop that
re-invokes `icat` per page on key press. `termpdf.py` is the reference. That is a follow-up, not part of `V` v1.

If we later want **inline** rendering inside Textual rather than a suspended full-screen view, the April 2026 research
applies in full: TGP with Unicode placeholders, pre-`App.run()` capability probe, tmux passthrough wrapping, single
upload + many placements. That is a different, much larger project from extending `V`.

## Reuse Existing Artifact PDFs (Important)

`render_markdown_pdf_attachments()` already pre-renders agent-attached Markdown into
`<artifacts_dir>/markdown_pdfs/<source-cache-key>.pdf` and records the mapping in `index.json`. **The Markdown
viewer should consult that index first.** When the focused Markdown file matches a record's `source_path`, the
existing PDF is the cache — no `pandoc` invocation needed at `V` time, no UI freeze, no PDF-engine dependency on the
host.

Lookup order at `V`:

1. If the surface knows an `artifacts_dir`, read `<artifacts_dir>/markdown_pdfs/index.json`. If it lists the focused
   source path **and** the recorded PDF mtime is at or after the source mtime, use the recorded PDF.
2. Otherwise, render via `render_markdown_pdf()` to a viewer-owned cache (see policy below).

This matters because pandoc + wkhtmltopdf/xelatex routinely takes 1–5 seconds for a small doc and longer for one with
many code blocks. Reusing the artifact PDF makes `V` feel instant on the common case (agent emitted the markdown,
attachments pipeline already rendered it).

`index.json` lookup must tolerate corrupt/missing index files — fall through to fresh render rather than erroring.

## PDF Rasterization (`pypdfium2`)

Decided in April 2026 research; reproducing here for self-containment.

```python
import pypdfium2 as pdfium

pdf = pdfium.PdfDocument(str(pdf_path))
n_pages = len(pdf)
page = pdf[0]
w_pts, h_pts = page.get_size()             # PDF user units (1/72")
scale = target_px_w / w_pts                # fit widget rect / terminal width
bitmap = page.render(scale=scale)
image = bitmap.to_pil()
image.save(str(png_path))
pdf.close()
```

Notes specific to the Markdown `V` flow:

- **Threading caveat.** PDFium is not thread-safe. The first version should rasterize synchronously while the TUI is
  suspended. If we ever move rasterization into a Textual worker, guard PDFium calls with a module-level lock.
- **Encrypted / unsupported PDFs.** `PdfDocument` raises `PdfiumError` for password-protected or malformed PDFs.
  Catch and surface a warning rather than letting it propagate into the suspend block.
- **Resolution targeting.** v1 can pick a fixed scale (e.g. `scale=2.0` ≈ 144 DPI) — `kitten icat --scale-up`
  handles the rest. A future improvement queries `CSI 14 t` for terminal pixel dims (see April research §8) and
  scales to fit, but that requires a one-shot probe before suspending Textual.
- **Page count.** v1 can render page 1 only and post a `Rendered page 1 of N` notify when `n_pages > 1`. The
  multi-image `kitten icat page-*.png` form is a strict improvement when `n_pages` is small (say ≤ 10) — we have
  the PDF, rendering all pages adds maybe 100–300 ms per page, and the user gets the whole document.

## HTML → PNG Alternative (Considered, Not Recommended for v1)

Instead of `Markdown → PDF → PNG`, we could do `Markdown → HTML → PNG` directly with one of:

- `pandoc -t html` then `wkhtmltoimage` (already a wkhtmltopdf sibling — same package).
- `pandoc -t html` then headless Chromium screenshot.
- `pandoc -t html` rendered through Pillow + a CSS engine (no good options).

Trade-offs vs the PDF path:

- **Pro:** skips the PDFium dependency entirely; produces a single tall PNG with no page boundaries; no scaling math.
- **Con:** wkhtmltoimage is being deprecated upstream (same trajectory as wkhtmltopdf); headless Chromium is a much
  heavier dependency than `pypdfium2`; SASE's existing pipeline already produces PDFs and we get cache reuse "for
  free" by going through them.
- **Con:** Loses page-boundary semantics, which an agent reading the file sometimes wants to see.

Recommendation: stick with `Markdown → PDF → PNG`. Revisit if `pandoc + pdf-engine` turns out to be too brittle on
user systems and `pypdfium2` adds meaningful install friction.

## Render UX (Latency)

`render_markdown_pdf()` runs `pandoc` synchronously and can take multiple seconds. The order of operations in the
TUI handler matters:

- **Bad:** `self.suspend(); render_markdown_pdf(...); icat ...` — the user sees a black/frozen terminal for the
  duration of rendering with no feedback.
- **Better:** notify "Rendering Markdown…" → render off-screen → if success, `self.suspend(); icat ...`. The TUI
  remains responsive during render; on failure we show a notify and never suspend.
- **Best (deferred):** dispatch `render_markdown_pdf()` in a Textual `@work` worker, accumulate a single in-flight
  render per `(source_path, mtime_ns)` so a held-down `V` doesn't queue duplicates, then suspend + icat from the
  worker's completion callback. v1 can keep it synchronous and just add the notify.

When the artifact-PDF cache hit path is taken, all of this is moot — go straight to suspend + icat.

## Cache Strategy (Viewer-Owned)

Used only when the artifact-PDF lookup misses.

- **Location.** Prefer `<artifacts_dir>/markdown_viewer/...` when the surface has an artifacts dir. Otherwise use
  `get_sase_tmpdir() / "markdown_viewer"`. Avoid hardcoding `~/.sase/cache/`; reuse `get_sase_tmpdir()` for
  consistency with other ephemeral viewer data.
- **Cache key.** Absolute source path + source `mtime_ns` + source size. **Also include CSS path + CSS mtime** when
  a CSS file is passed to `render_markdown_pdf()` — wkhtmltopdf output depends on CSS, and a CSS edit must
  invalidate the cached PDF/PNGs.
- **Layout per key.** `<key>/source.pdf`, `<key>/page-1.png`, `<key>/page-2.png`, …. Page PNGs are a separate
  cache layer — re-rendering only the PNGs (e.g. when terminal pixel dims change) is cheap.
- **Cleanup.** v1 can leave entries behind. A future shared `~/.sase/cache` cleanup utility can sweep them by age.

## Recommended Implementation

Add a markdown-aware helper rather than teaching `view_image_file()` about non-image files:

```text
src/sase/ace/tui/graphics/markdown_viewer.py
```

Responsibilities:

- Validate `.md` / `.markdown` (reuse `SUPPORTED_MARKDOWN_EXTENSIONS` from `markdown_pdf.py`; do **not** add
  `.qmd` / `.rmd` / `.mdx` here — pandoc handles them but our render path is not tested for them, defer).
- Resolve the PDF (artifact-cache lookup → viewer cache → fresh render).
- Rasterize page 1 to PNG (and additional pages opportunistically when `n_pages` is small).
- Run `kitten icat --hold --align center [--transfer-mode stream] <png>...`.
- Return the same `ImageViewerResult` shape so callers keep the current notify/toast behavior.

Keep `view_image_file()` and `is_supported_image_path()` unchanged. Markdown is a source document that needs a
conversion pipeline — broadening the image predicate would be a category error.

## TUI Integration Points

Agents tab:

- Add `AgentFilePanel.get_current_markdown_path() -> str | None`, parallel to `get_current_image_path()`.
- Add `AgentDetail.get_current_markdown_path()` that delegates to the file panel only when visible.
- Add `AgentDetail.get_current_artifacts_dir()` (or surface an existing accessor) so the viewer can find the
  matching `markdown_pdfs/index.json`.
- Extend `action_view_image()` in `actions/agents/_panels.py`:
  - image path: current behavior;
  - markdown path: notify "Rendering…" → render PDF/PNG → suspend → icat;
  - neither: existing attempt-view fallback.

Notification modal:

- Add `_get_current_markdown_path()` next to `_get_current_image_path()`.
- The notification's source `Notification` carries the artifacts dir of the agent that emitted it; pass that into
  the markdown viewer so it can reuse pre-rendered artifact PDFs.
- Extend `action_view_image()` to dispatch on image / markdown / neither.

Naming and discoverability:

- Keep the action name `view_image` and key `V` for keymap-config compatibility.
- **Help modal.** `src/sase/ace/tui/modals/help_modal/bindings.py` line 347 currently labels the binding
  `View image / attempt fallback`. Update to `View image/Markdown / attempt fallback` (or similar; box width is
  capped at 32 chars per `src/sase/ace/AGENTS.md`).
- **Footer.** The `V` keymap is already conditional on a viewable image; extend that condition to
  `image_or_markdown_visible` so the binding shows in the footer when the focused file is `.md`.
- **Keymap config (`default_config.yml`).** No change — same key, broadened action behavior.

## Failure Modes To Surface

Return warnings rather than raising:

- Markdown file missing or unreadable.
- `pandoc` missing.
- No PDF engine installed (`render_markdown_pdf()` already returns `None` for this).
- Pandoc timeout (120s default — unlikely for a single file but possible for a very large one).
- `pypdfium2` missing (only relevant if it is made an optional dep; required is simpler).
- PDF has zero pages, is encrypted, or is malformed.
- PNG save failed (disk full, permission, etc.).
- `kitten` missing on PATH.
- `kitten icat` exited non-zero.
- Selected file is the live "in-flight" agent output (its mtime is younger than ~1 s and the file size is still
  growing). Optional but cheap — log the warning and render anyway, since users may explicitly want a snapshot.

The current `render_markdown_pdf()` already returns `None` for tool/conversion failures, so the helper preserves
that style and reports a compact message like `Could not render Markdown PDF`.

## Test Plan

Tests should cover behavior without running real `pandoc`, PDFium, or Kitty (mock the boundaries):

- `get_current_markdown_path()` returns expanded existing Markdown paths and rejects live diffs, images, text files,
  and missing files.
- Markdown viewer prefers `<artifacts_dir>/markdown_pdfs/index.json` when source_path matches and the recorded PDF
  is at least as new as the source.
- Markdown viewer falls through to `render_markdown_pdf()` when the index is missing, malformed, or stale.
- Markdown viewer rasterizes page 1 (and page 2..N when `n_pages` is small) and calls `view_image_file()` /
  `kitten icat` with the PNG path(s).
- Markdown viewer reuses a fresh cache entry when source size/mtime + CSS mtime are unchanged.
- CSS edit invalidates the cached PDF/PNGs.
- Agent `action_view_image()` prefers real images over Markdown and prefers Markdown over attempt-view fallback.
- Notification modal `action_view_image()` opens Markdown attachments when the selected file is Markdown.
- Missing `pandoc` / failed PDF render yields a warning and does not call `kitten`.
- Encrypted / zero-page PDF yields a warning and does not call `kitten`.
- Help modal `View image/Markdown / attempt fallback` label fits within the 32-char binding-description budget
  enforced by `src/sase/ace/AGENTS.md`.
- If `pypdfium2` is added as a required dependency, run `just install` so `uv.lock` is regenerated and committed.

## Open Decisions

- **Required vs optional `pypdfium2`.** Required is simpler, the wheel ships PDFium so installs are uniform, and
  SASE already depends on `pillow`. Recommend required.
- **Page-1 only vs all pages via `kitten icat path...`.** All-pages is a small extra cost and dramatically better
  UX for typical agent-emitted Markdown (1–5 pages). Recommend all pages when `n_pages ≤ 10`, page 1 + warning
  beyond that.
- **Force `--transfer-mode stream` globally.** Helps SSH; should still work locally with negligible latency cost
  for the page-PNG sizes we will produce. Recommend yes.
- **Migrate the existing image viewer to `kitten icat --hold` and drop the bash `read` wrapper.** Independent of
  Markdown; removes a small amount of shell. Recommend yes, in a separate change.
- **Synchronous render at `V` time vs Textual `@work` worker.** Synchronous is fine for v1 with a "Rendering…"
  notify; revisit if users hit it on large docs.
- **Where to put cache cleanup.** Out of scope for this feature. A separate `sase cache prune` command can sweep
  `markdown_viewer/` and other transient caches in one place.

## tmux / SSH Caveats

The Markdown `V` flow inherits the existing image-viewer's behavior: `kitten icat` runs as its own process while
Textual is suspended, so it owns the TTY directly. This is **less** affected by tmux passthrough issues than the
inline-rendering path described in `sdd/research/202604/tui_image_pdf_support.md` — there is no Textual frame loop
fighting over the wire. The April research's tmux/SSH section still applies the moment we move toward inline TGP.

`kitten icat --transfer-mode stream` is the only safe transport for SSH (file/temp/shared-memory transports assume
a local shared filesystem). Forcing it for both image and Markdown viewing is the simplest policy.

## Sources

- Local: `src/sase/attachments/markdown_pdf.py`
- Local: `src/sase/ace/tui/graphics/viewer.py`
- Local: `src/sase/ace/tui/graphics/images.py`
- Local: `src/sase/ace/tui/actions/agents/_panels.py` (`action_view_image`, line 307)
- Local: `src/sase/ace/tui/modals/notification_modal_attachments.py` (`action_view_image`, line 207)
- Local: `src/sase/ace/tui/modals/help_modal/bindings.py` (label at line 347)
- Local: `src/sase/default_config.yml` (`view_image: "V"`, line 88)
- Local: `src/sase/ace/AGENTS.md` (help modal width, footer convention, help-popup maintenance rule)
- Local: `sdd/research/202604/tui_image_pdf_support.md` (PDF library decision, tmux/SSH detail, inline-render path)
- Kitty `icat` docs (incl. `--hold`, `--transfer-mode`, `--align`, format support):
  https://sw.kovidgoyal.net/kitty/kittens/icat/
- Kitty graphics protocol spec: https://sw.kovidgoyal.net/kitty/graphics-protocol/
- Kitty `kitten ssh` (terminfo install, transfer-mode notes): https://sw.kovidgoyal.net/kitty/kittens/ssh/
- pypdfium2 introduction: https://pypdfium2.readthedocs.io/en/stable/readme.html
- pypdfium2 Python API: https://pypdfium2-team.github.io/pypdfium2/python_api.html
- Pandoc PDF engines (wkhtmltopdf, xelatex, pdflatex): https://pandoc.org/MANUAL.html#creating-a-pdf
- termpdf.py reference (suspended-terminal PDF reader pattern): https://github.com/dsanson/termpdf
- ImageMagick PDF delegate (Ghostscript dependency, why not to rely on icat-handles-PDF):
  https://imagemagick.org/script/formats.php

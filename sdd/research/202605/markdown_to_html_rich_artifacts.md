# Markdown → HTML for Rich Artifacts

Research date: 2026-05-11

## Question

Should SASE add a Markdown → HTML conversion step so agents can produce **rich
artifacts** that render with proper typography, tables, code highlighting, and
images? The HTML output should be usable in three surfaces:

1. The terminal (TUI / `kitten icat` flow), parallel to today's
   Markdown → PDF → PNG path.
2. An eventual web client (browser, mobile WebView, or Textual-Serve).
3. The static `sase.sh` docs site (already MkDocs Material — see below).

Short answer: **yes, add it**, but as a *parallel render target* under
`src/sase/attachments/` rather than a replacement for the PDF pipeline. The
web client motivates this on its own; everything else is a nice byproduct.
Concretely:

- Add `src/sase/attachments/markdown_html.py` with a `render_markdown_html()`
  function and a batched `render_markdown_html_attachments()` mirror of the
  PDF helper, writing under `<artifacts_dir>/markdown_html/`.
- Add `"html"` to `AgentArtifactKind` (currently `chat | plan | image |
  markdown | pdf | file`) so the index can carry rendered HTML directly.
- Render terminal HTML by rasterizing through a headless browser only when
  the user explicitly asks for it (`V` keeps using PDF→PNG; a new key or
  `view_html` action does HTML→PNG via Playwright/Chromium when installed).
  This is a follow-up, not v1.
- Reuse the **markdown-it-py + linkify + mdit-py-plugins** stack rather than
  pandoc for the HTML path — pure Python, ~3 ms per typical artifact, no
  system deps, deterministic output.

The rest of the doc spells out why.

## Existing SASE Shape

What's already there (from `src/sase/attachments/`, `src/sase/core/`,
`src/sase/ace/tui/graphics/`, and `docs/`):

- `src/sase/attachments/markdown_pdf.py` — only Markdown converter in the
  repo. Shells out to `pandoc` with `--pdf-engine={wkhtmltopdf|xelatex|
  pdflatex}`, writes `<artifacts_dir>/markdown_pdfs/<key>.pdf` and an
  `index.json` of `source_path → pdf_path`. ~120 s timeout, atomic rename,
  CSS profile injected via `--css`. Pandoc internally goes
  Markdown → HTML → PDF when `wkhtmltopdf` is the engine, which is the
  important point for this research: **we are already generating HTML on
  every run, then throwing it away.**
- `src/sase/core/agent_artifact_types.py:9` — `AgentArtifactKind = Literal[
  "chat", "plan", "image", "markdown", "pdf", "file"]`. No `html`. Index
  schema version is 1.
- `src/sase/integrations/_mobile_notification_attachments.py` classifies
  attachments by extension and stamps a MIME type. `.md` → `"markdown"` /
  `text/markdown`. No `.html` branch.
- `src/sase/ace/tui/graphics/_viewer_render.py:201-232` — the artifact
  viewer dispatches on kind. `"markdown"` → `render_markdown_pdf()` →
  `pdftoppm -png` → `kitten icat`. There is no `"html"` branch.
- `src/sase/xprompt/_catalog_render.py:127-150` — already does **HTML
  generation** via Jinja2 templates (`catalog_template.html.j2`) and
  `render_pdf()` via wkhtmltopdf. This is the closest in-tree precedent for
  what we want — but it's structured xprompt-catalog data, not arbitrary
  Markdown.
- `mkdocs.yml` + `docs/blog/posts/*.md` — the docs site uses **MkDocs
  Material**, which means Markdown → HTML is already happening in CI for
  the public site, just not in the agent pipeline. Worth noting because
  MkDocs uses `python-markdown` with extensions like `pymdownx.superfences`;
  our agent-artifact pipeline doesn't have to match that exactly, but
  consistency in *user-visible* rendering would be nice.
- `pyproject.toml` already depends on `jinja2`. No `markdown-it-py`,
  `python-markdown`, `mistune`, `markdown2`, `bleach`, or `nh3`.
  (`markdown-it-py 4.2` shows up in `.venv/` transitively via
  `mkdocs-material`, but it is **not** a declared runtime dep — adding it
  to `pyproject.toml` makes it explicit and version-pinnable.)
- `src/sase/sdd/frontmatter.py` already exposes a YAML-frontmatter parser
  (`parse_frontmatter(text) -> (dict, body, had_frontmatter)`). SDD
  markdown and memory files use this. **`markdown_pdf.py` does not strip
  frontmatter today** — pandoc treats unrecognized YAML between `---`
  fences as content and often emits visible junk at the top of the PDF.
  The new HTML path should `parse_frontmatter()` first, render only the
  body, and (optionally) surface selected frontmatter keys as `<meta>`
  tags or a small header block.
- `src/sase/ace/tui/models/agent_content_search.py:59-60` hardcodes the
  artifact files it indexes for in-TUI search (`raw_xprompt.md`,
  `live_reply.md`). Adding `markdown_html/*.html` does **not** break
  search, but search should continue to read from the Markdown *source*,
  not the generated HTML — grepping rendered HTML is a regression in
  precision and recall (tags, entities, inlined CSS).
- `src/sase/integrations/_mobile_notification_attachments.py:145-161`
  classifies by extension. `.html` currently falls through to
  `"unknown"` with no MIME and `can_inline=False`. Needs a branch.
- No usage of `textual.widgets.Markdown` anywhere; the TUI uses
  `rich.markdown.Markdown` for inline previews. Either remains a valid
  HTML-free path for inline rendering (see "Inline TUI Preview" below).
- No mermaid generation in agent code today (171 hits, all in docs / blog
  posts that get rendered by MkDocs-Material's own mermaid integration).
  Agents *will* start emitting mermaid blocks once we tell them they can.
- No existing base64 image inlining in any renderer. Pandoc handles
  image refs natively in the PDF path; the HTML renderer has to do it
  itself.
- Tier 1 memory `memory/short/rust_core_backend_boundary.md`: shared
  backend behavior belongs in `../sase-core`. Markdown→HTML rendering is
  borderline — see "Boundary Question" below.

## Why HTML At All

Three independent motivations, in increasing order of urgency:

1. **Better TUI rendering than PDF→PNG.** PDF is fixed-page; HTML reflows.
   For a long agent-emitted report or a chat-log artifact, the page-break
   semantics are noise. A single tall PNG rasterized from a width-matched
   HTML render is a more honest representation of the document. (This is
   the same argument we already considered in `markdown_view_image_keymap.md`
   §HTML → PNG Alternative — we rejected it for v1 of the `V` keymap, not
   forever.)

2. **No more pandoc + LaTeX/wkhtmltopdf dependency for the common case.**
   Today, `render_markdown_pdf()` returns `None` whenever pandoc or its
   PDF engine is missing — silent degradation. A pure-Python Markdown→HTML
   pipeline always succeeds in CI/dev/mobile environments and gives us a
   visible fallback even when the PDF path fails.

3. **Required for the eventual web client.** A browser surface can't show
   `kitten icat`. It needs HTML. Whether the web client is a thin viewer
   over `~/.sase/artifacts/` or a Textual-Serve session, the wire format
   for a rich artifact is HTML, not PDF, and definitely not PNG. Building
   the renderer **now** means the artifact index already carries `.html`
   paths when the web client lands, instead of forcing a backfill.

The web-client argument is the load-bearing one. Even if we never display
HTML in the terminal, we'll want it for the web. Adding it as a generic
attachment-renderer means it pays for itself in two surfaces and could
later replace PDF→PNG entirely in the TUI.

## Library Choice

Three serious candidates for the Markdown→HTML step:

| Library          | License    | Speed  | Extensibility | CommonMark | GFM tables | Footnotes | Math |
|------------------|------------|--------|---------------|------------|------------|-----------|------|
| `markdown-it-py` | MIT        | fast   | plugin API    | ✅          | ✅ via plugin | ✅          | ✅ via plugin |
| `python-markdown`| BSD        | medium | extensions    | ⚠️ (legacy dialect) | ✅ via ext | ✅ via ext  | ✅ via ext |
| `mistune`        | BSD        | fastest| renderer subclass | ✅       | ✅ built-in | ✅ built-in | manual |

**Recommendation: `markdown-it-py` + `mdit-py-plugins` + `linkify-it-py`.**

- It is the Python port of the same `markdown-it` JS parser that powers
  MkDocs-Material's `pymdownx` stack and most editor previews — meaning
  agents writing Markdown will see consistent rendering across SASE's docs
  site, the TUI artifact viewer, and the future web client.
- Plugin ecosystem covers tables, footnotes, task lists, definition lists,
  anchors, attrs, GitHub-style alerts (`> [!NOTE]`), math (KaTeX / MathJax),
  and admonitions. We probably want tables, footnotes, task lists, and
  anchors on day one.
- Pure Python wheel, no system deps. Important for the mobile gateway and
  for the ephemeral `sase_<N>` workspaces — adding C-extension deps to a
  workspace clone has hurt us before (cf. visual snapshot tests).
- Active maintenance; current major is `3.x`.

Reasons not to use the alternatives:

- `python-markdown` is older and slower, and its default flavor diverges
  from CommonMark in surprising ways (e.g. one-newline soft breaks vs.
  hard breaks). MkDocs uses it because of historical inertia, not because
  it's the best choice for new code.
- `mistune` is faster (~2×) but the v3 plugin API is awkward and its
  community is smaller. Speed is irrelevant at our document sizes — we are
  talking about sub-10-ms parses either way.
- `pandoc -t html` would work but inherits the same "system tool must be
  installed" problem we have with PDF rendering. Defeats the point.

### Sanitization

Agent-emitted Markdown is **untrusted by default** — an agent could
hallucinate `<script>` tags, malformed `<a href="javascript:...">`, or
SVG with embedded JS. For terminal rendering this matters less (no JS
runtime), but for the web client it is critical.

- **Use `nh3`** (Rust-based, fast, sane defaults — successor to `bleach`,
  which is now deprecated). `bleach` is unmaintained as of 2024.
- Build an allowlist that matches markdown-it's output: headings, lists,
  tables, code blocks, blockquotes, anchors with `href` (no `javascript:`,
  no `data:` except `image/png` and friends), images with `src` similarly
  constrained, plus the common inline elements.
- Sanitize **after** rendering, not at the Markdown level — that way
  custom-HTML inside the source Markdown gets the same treatment as
  generated HTML.

This is the only new C-extension dep on the table (`nh3` builds a Rust
extension). Worth it — Python HTML sanitizers are slow and have had
parser-confusion CVEs.

### Frontmatter

SDD markdown files, memory entries, and many agent-emitted artifacts
have YAML frontmatter:

```markdown
---
name: foo
type: feedback
---

# Body starts here
```

`render_markdown_html()` must:

1. Call `sase.sdd.frontmatter.parse_frontmatter()` first.
2. Render only the body via markdown-it-py.
3. Emit selected frontmatter keys as `<meta name="sase-{key}" content="…">`
   — at minimum `name`, `type`, `description`. This makes the HTML
   self-describing for the web client (filter / facet by type without
   re-parsing source markdown).
4. *Optionally* render a small `<header class="sase-frontmatter">` block
   at the top with `<dt>/<dd>` pairs. Behind a profile flag; the
   `HTML_DESKTOP_PROFILE` should default to "on", the
   `HTML_MOBILE_PROFILE` to "off" (no room).

This also closes a latent bug in `render_markdown_pdf()`, which silently
renders frontmatter as visible content. Fix that in passing or open a
follow-up bead.

### Mermaid and Other Diagram Blocks

Markdown-it-py treats ```` ```mermaid ```` as a fenced code block by
default and emits `<pre><code class="language-mermaid">…</code></pre>`.
Three render strategies:

- **v1 (no diagram support):** Leave as a fenced code block. Source is
  legible; nothing breaks. Document this explicitly so agents don't
  silently start emitting mermaid expecting it to render.
- **v2 (server-side SVG):** Use `mermaid-cli` (`mmdc`) to convert each
  block to inlined SVG at render time. External Node binary dep — same
  trap pattern as pandoc; opt-in only.
- **v3 (client-side in web view):** Ship `mermaid.js` in the web client
  and execute the language-mermaid blocks at view time. Zero impact on
  the artifact files.

Recommend (1) now, (3) when the web client lands, skip (2). Same calculus
applies to PlantUML, Graphviz, etc.

### Syntax Highlighting

Code blocks need highlighting. Two options:

- **Server-side via Pygments** — same library Textual already uses for
  `Syntax`. Output is `<pre><code class="...">` with inline color spans.
  Self-contained, no JS dep.
- **Client-side via highlight.js or Prism** — only useful for the web
  client; would force us to ship JS in the artifact HTML. Skip for now.

Pygments is already a transitive dep (Textual / Rich). Use it.

## Output Layout

Mirror the PDF helper for symmetry:

```
<artifacts_dir>/markdown_html/
    index.json                # [{source_path, html_path, css_path}]
    <source-cache-key>.html   # self-contained, inlined CSS, no external assets
    <source-cache-key>.css    # only if we ever externalize CSS
```

Self-containment matters because the web client may serve artifacts from a
different origin than where the agent produced them. Inlined CSS + base64
images means a single `.html` file is portable. The trade-off is file size
for image-heavy artifacts; we can revisit if it becomes a problem.

**Cache key.** Absolute source path + source `mtime_ns` + source size +
CSS-profile hash + **renderer-version hash** (markdown-it-py version +
plugin set + sanitizer allowlist hash). The renderer-version component
is new compared to the PDF cache key; markdown-it-py output is
sensitive to plugin lineup in a way pandoc-pdf isn't, and we don't want
to serve stale HTML after upgrading the parser.

**Atomic `index.json` writes.** `markdown_pdf.py` writes individual
`.pdf` files atomically (tmp file + `Path.replace()`) but writes
`index.json` directly with `Path.write_text()` (see
`markdown_pdf.py:146-149`). A concurrent renderer can read a torn
index. The new HTML helper should fix this for itself (tmp + fsync +
rename) **and** the same fix should be backported to `markdown_pdf.py`
in a small follow-up — both pipelines may run in parallel from the
mobile-notification path. No file locks needed; atomic rename is
sufficient on Linux/macOS.

**HTML size budget.** Base64 inlining of images is the easy win but can
balloon a single `.html` to tens of MB. Cap per-artifact size at 10 MB
(configurable). On overflow:

  - For images: write the image as a sidecar under `markdown_html/`
    and emit a relative `<img src>` pointing to it. The artifact loses
    "single-file portability" only for the affected blobs.
  - For text: truncate-with-warning and surface the truncation in the
    artifact index so the TUI / web client can show "artifact too
    large — open source".

**Index schema bump.** Adding a parallel `markdown_html/` directory does
not require touching `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` because the
existing schema treats artifact kinds as a discriminated union. Adding
`"html"` to `AgentArtifactKind` *does* technically widen the contract,
but every consumer uses `coerce_artifact_kind()` which raises on unknown
values — old readers will hard-fail on new `"html"` entries. Either:

  - Bump the index schema version to 2 and gate `"html"` entries behind it
    (safe, slightly more work), **or**
  - Treat `"html"` like `"file"` in the legacy path so old readers see it
    as a generic file (lossy on the consumer side, simpler).

Recommend the schema version bump. We are still pre-1.0; doing it cleanly
is cheap.

## CSS / Styling

`render_markdown_pdf()` already has a CSS profile concept
(`MarkdownPdfProfile`) tuned for the 4.25"×7" mobile-PDF page. HTML needs
its own profile — viewport-sized, not page-sized.

Two profiles are enough:

- **`HTML_DESKTOP_PROFILE`** — body 720px max-width, system font stack,
  fluid line-length, Pygments default code colors. For TUI rasterization
  and the eventual web client.
- **`HTML_MOBILE_PROFILE`** — body 100%, narrower line-length, slightly
  larger base font. For mobile notification previews.

Both share base typography. The existing `markdown_pdf.css` is a good
starting point; fork it into `markdown_html.css` rather than try to share
across paging contexts (page-break rules don't translate; viewport rules
don't translate).

**Dark mode.** Add `@media (prefers-color-scheme: dark)` overrides from
day one. The web client and the future Textual-Serve session will inherit
the user's system preference; cheap to support, expensive to bolt on later.

**Print stylesheet.** Add `@media print` rules (page-break-inside:
avoid for tables and code blocks, restore page margins, drop the dark
scheme). With print CSS in place, the same `.html` file can be
"printed to PDF" by any browser — meaning the *long-term* version of
this work could deprecate the pandoc/wkhtmltopdf path entirely:
HTML is the source, PDF is just `chromium --headless --print-to-pdf`.
That's a v3 conversation; mention only because it argues for getting
print CSS right *now* rather than retrofitting.

**Accessibility (a11y).** markdown-it-py emits semantic HTML by
default (`<h1>`–`<h6>`, `<ul>`, `<table>` with `<thead>`/`<tbody>`,
etc.), so we mostly inherit a good baseline. Two concrete asks:

  - **Require alt text on images** at the renderer level — if the
    Markdown is `![](path.png)` with no alt, emit a warning *and* a
    placeholder alt like `"unlabeled image"`. Agents that produce
    artifacts will learn the convention quickly.
  - **Heading-level continuity.** Markdown that jumps from `#` to
    `###` is technically valid but trips screen readers. Warn at
    render time; do not auto-fix.

Skip ARIA roles — semantic HTML is enough at our complexity.

## Terminal Rendering Options

If we want to render HTML in the terminal (instead of via the existing
Markdown→PDF→PNG path), there are four practical options:

1. **HTML → PNG via headless Chromium (Playwright).**
   - Pros: pixel-perfect, matches what the web client will show, handles
     CSS / fonts / dark-mode automatically.
   - Cons: heavy dep (~150 MB browser download on first install), slow
     startup (~500 ms cold even with `--no-sandbox`), and an opinion about
     Linux distros (system libs). Bad fit for default install; reasonable
     as an *opt-in* dep behind a `pip install sase[html-render]` extra.
2. **HTML → PNG via `wkhtmltoimage`.**
   - Pros: same package as `wkhtmltopdf` (which some users already have).
   - Cons: upstream-archived, last release 2022, security holes (CVE-2024-
     22424 stalled), broken CSS3 / flexbox / grid support. **Reject.**
3. **HTML → terminal via Rich's `Markdown` renderer (skip HTML entirely).**
   - Rich has a `Markdown` widget that renders directly to the terminal
     without going through HTML. We could expose that for an "inline TUI
     preview" mode, separate from the rasterized full-screen view. Lower
     fidelity (no tables-with-cell-alignment, limited images), but
     instant and no dependencies.
   - This is the right answer for **inline preview** (file panel, chat
     panel), not for the full-screen `V` view.
4. **HTML → terminal via `glow` / `mdcat` / `frogmouth`.**
   - These are external CLI tools. `glow` is Charm's; `mdcat` is Rust;
     `frogmouth` is Textual-based. All shell out, all give better
     rendering than Rich.Markdown for tables and links. But adding a
     binary-on-PATH dependency for a default code path is the same trap
     we keep hitting (`pandoc`, `wkhtmltopdf`, `pdftoppm`, `kitten`).

**Recommendation tier list:**

- **v1 (always available):** Keep the existing Markdown→PDF→PNG path for
  the `V` keymap. Add HTML generation as a parallel artifact target. Do
  **not** add HTML→PNG rendering in the terminal yet.
- **v2 (opt-in):** Add Playwright as an optional extra and a
  `view_html_artifact` action that uses it. The artifact HTML files are
  there waiting; rasterizing them is mechanical.
- **v3 (when web client lands):** The web client renders the same HTML
  files natively, no terminal rasterization needed. Most users will read
  artifacts in the browser; the TUI rasterization becomes a niche
  fallback for SSH-only users.

## Inline TUI Preview (Tangential But Worth Noting)

Rich's `rich.markdown.Markdown` class renders Markdown to a styled
`Renderable` in the terminal. We already use `rich.syntax.Syntax` for
syntax-highlighting Markdown source in the file/prompt panels
(`src/sase/ace/tui/util/lazy_syntax.py:45-85`). Swapping that for
`Markdown` would render headings as headings, lists as lists, links as
underlined cyan, etc. — without going through HTML at all.

This is **not** what this research is about, but it's worth flagging
because it might be confused with HTML rendering. Treat it as a separate
feature: "render Markdown source nicely in the inline panels." HTML
rendering is for the artifact viewer and the web client.

## Web Client Implications

Even though there is no web client today, designing the HTML output for
web reuse costs nothing now and saves a migration later. Specifically:

- **Self-contained `.html` files** with inlined CSS and base64 images.
  Serveable from any static-file origin.
- **No JS.** Code highlighting via Pygments server-side, no live MathJax
  unless the artifact actually contains math (and even then, prefer
  KaTeX-rendered SSR).
- **Stable anchor IDs** generated from heading text + a hash suffix for
  collisions. Lets the web client deep-link into a long artifact.
- **`<base target="_blank">`** so any links in the artifact open in a new
  tab when embedded in an iframe in the web client.
- **`<meta charset="utf-8">`** as the *first* element under `<head>` —
  required by HTML5 for charset detection to be reliable across browsers
  (especially mobile WebView).
- **`<meta name="viewport" content="width=device-width, initial-scale=1">`**
  so mobile renders sanely.
- **`<meta name="generator" content="sase markdown-html v1">`** for
  debugging and so future readers know what produced the file.
- **Sandbox the iframe.** Recommended attribute set for the web
  client's `<iframe>`: `sandbox="allow-same-origin allow-popups"` (no
  `allow-scripts`, no `allow-top-navigation`). With our "no JS"
  guarantee plus nh3 sanitization, this is safe and prevents
  artifact-borne XSS from escaping the iframe.
- **CSP via `<meta http-equiv="Content-Security-Policy">`** inside the
  artifact itself: `default-src 'none'; img-src data:; style-src
  'unsafe-inline'; font-src data:`. Belt-and-suspenders with the
  sanitizer.

The web-client repo can then be a thin viewer: list artifacts from the
JSONL index, render each `<artifact>.html` in an iframe (sandboxed:
`allow-same-origin` only, no scripts), and call it done.

## Integration Points

In rough dependency order:

1. **`pyproject.toml`** — add `markdown-it-py`, `mdit-py-plugins`,
   `linkify-it-py`, `nh3`. Run `just install` to regenerate `uv.lock`.
2. **`src/sase/attachments/markdown_html.py`** — new module mirroring
   `markdown_pdf.py`:
    - `SUPPORTED_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})`
      (same as PDF; do not broaden).
    - `render_markdown_html(source_path, *, css, profile, …) -> str | None`.
    - `render_markdown_html_attachments(...) -> list[str]` writing under
      `<artifacts_dir>/markdown_html/` and emitting `index.json`.
    - Same `MarkdownPdfProgressEvent`-style progress callback (we should
      factor a shared `MarkdownRenderProgressEvent` in a small follow-up
      but it doesn't block v1).
3. **`src/sase/attachments/__init__.py`** — re-export the new API.
4. **`src/sase/core/agent_artifact_types.py`** — add `"html"` to
   `AgentArtifactKind` / `AGENT_ARTIFACT_KINDS`. Add `_HTML_SUFFIXES =
   {".html", ".htm"}` and an arm in `infer_artifact_kind()`. Bump
   `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` to 2.
5. **`src/sase/integrations/_mobile_notification_attachments.py`** —
   classify `.html` as kind `"html"` with MIME `text/html; charset=utf-8`.
   Set `can_inline=False`: Telegram's `parse_mode=HTML` accepts only a
   ~10-tag subset (`b`, `i`, `u`, `s`, `a`, `code`, `pre`, `tg-spoiler`,
   `blockquote`, `tg-emoji`) and will reject the artifact's full HTML
   body. HTML attachments must travel as `sendDocument` files, same as
   the PDF path.
6. **`src/sase/ace/tui/graphics/_viewer_render.py`** — no change for v1.
   Once Playwright is wired in, add an `"html"` arm next to the existing
   `"markdown"` arm, going HTML → PNG → `kitten icat`.
7. **Wire renderer to the attachments pipeline.** Wherever
   `render_markdown_pdf_attachments()` is called today (search:
   `render_markdown_pdf_attachments` — at least the mobile-notification
   pipeline), call `render_markdown_html_attachments()` in parallel.
   They're independent; failure of one shouldn't fail the other.
8. **`src/sase/ace/tui/models/agent_content_search.py:59-60`** — *do
   not* add `.html` files to the search index. Search reads the
   `.md` source; the `.html` is derived. Add a comment to that effect
   so the next contributor doesn't "fix" it.
9. **Tests under `tests/test_markdown_html.py`** — model on
   `tests/test_markdown_pdf.py`'s `tmp_path` + mocked-binary pattern,
   but since markdown-it-py is a pure-Python library, the new tests
   can call it directly with no `shutil.which()` / `subprocess.run()`
   mocking. Simpler and more deterministic than the PDF tests.

## Boundary Question — sase-core?

`memory/short/rust_core_backend_boundary.md` says shared backend behavior
belongs in `../sase-core`. Does Markdown → HTML qualify?

Litmus: "if a web app, CLI, editor integration, or another frontend would
need the behavior to match the TUI, treat it as core backend logic."
HTML rendering would absolutely need to match across TUI, mobile, and web
client.

**However:** the actual conversion is one function call to a Python
library. Moving that to Rust means choosing a Rust Markdown parser
(`pulldown-cmark`, `comrak`) and threading sanitization (`ammonia`) and
syntax highlighting (`syntect`) through PyO3 bindings. That's not free,
and the rendering would no longer match what MkDocs renders for the docs
site (different parser, different extension behavior).

Pragmatic call: **keep this in Python for v1.** Re-evaluate when:

- The mobile-Android Rust path needs to render artifacts without a Python
  interpreter (see `android_mobile_rust_core_api.md`), or
- The web client is built in Rust/WASM rather than as a thin Python
  service.

Until then, Python `markdown-it-py` is the right tool.

## Failure Modes To Surface

`render_markdown_html()` should return `None` and log a warning, never
raise, mirroring `render_markdown_pdf()` semantics:

- Source missing / unreadable.
- Source bigger than a sanity cap (start at 2 MB — way bigger than any
  legitimate agent artifact).
- Parser raises (extremely unlikely with markdown-it-py; defensive only).
- Sanitizer strips everything (would indicate adversarial input or a
  rendering bug — log loudly).
- Disk full / cannot write into `markdown_html/`.

Index-corruption: `index.json` writes should be atomic (write to tmp,
fsync, rename) — same pattern as `markdown_pdf.py` already uses.

## Test Plan

- Unit: `render_markdown_html()` produces well-formed HTML for fixtures
  (heading, list, table, code block with language, link, image,
  blockquote, GFM task list, footnote).
- Unit: sanitizer strips `<script>`, `javascript:` URLs, and
  `data:text/html` srcs but preserves `data:image/png` srcs.
- Unit: CSS profile is inlined into `<style>`; no external `<link>` tags.
- Unit: `infer_artifact_kind("foo.html")` returns `"html"`.
- Unit: writing then reading back an index entry round-trips with kind
  `"html"`.
- Unit: schema-version bump rejects old-schema readers on new-schema
  files (or vice versa, depending on which direction we promise).
- Integration: `render_markdown_html_attachments()` on a directory of
  Markdown sources produces the expected file layout and an `index.json`
  that matches.
- Integration: parallel invocation with the PDF helper — both succeed
  independently when both engines are available; HTML still succeeds
  when pandoc/PDF engine is missing.
- Visual snapshot (PNG): if Playwright is added in v2, snapshot a few
  representative artifacts at fixed viewport size and pin them in
  `tests/visual/`.

## Open Decisions

- **Schema bump vs. legacy-as-`file` fallback for `"html"`.** Recommend
  schema bump; we're pre-1.0.
- **Sanitization library: `nh3` vs. write our own.** Recommend `nh3`. The
  Rust extension is worth the runtime safety guarantee. Don't roll our
  own HTML sanitizer.
- **CSS profile: fork from PDF or share a base.** Recommend fork. Page-
  oriented vs. viewport-oriented CSS share almost nothing in practice.
- **Pygments class names vs. inline color.** Recommend **inline** in v1
  (self-contained HTML is more important than file size). Switch to
  class-based when the web client lands and can ship a single CSS file
  for all artifacts.
- **MathJax / KaTeX support.** Defer. Add the markdown-it math plugin
  but render math as escaped TeX source for now. Wire to KaTeX SSR when
  someone actually emits an artifact with math.
- **Single `.html` per artifact vs. a directory with sidecar assets.**
  Recommend single self-contained file. Revisit if image sizes blow up.
- **Whether to retire the PDF path long-term.** Out of scope today.
  But: once HTML has a working `@media print` profile, a future
  `chromium --headless --print-to-pdf` could replace pandoc entirely.
  Worth a follow-up bead, not a v1 blocker.
- **Mermaid / diagrams.** Render as fenced code blocks for v1 (no
  visual diagram). Decide v2 between server-side `mermaid-cli` and
  web-client `mermaid.js`. Recommend the latter.
- **Should `render_markdown_pdf()` learn to strip frontmatter** as
  part of this work, or leave that bug as-is? Recommend fixing it in
  the same PR — `parse_frontmatter()` is a couple of lines and the
  PDF output is visibly nicer with frontmatter gone.
- **HTML size cap.** Recommend 10 MB; will need empirical tuning once
  agents actually start emitting large rich artifacts.

## tmux / SSH Caveats

This research's v1 deliverable is a file artifact — no terminal rendering
— so there are no tmux/SSH concerns until v2 (Playwright HTML→PNG). At
that point the same caveats from `markdown_view_image_keymap.md` apply:
`kitten icat --transfer-mode stream` for SSH, and the rasterization must
happen outside the Textual frame loop (suspended app or worker thread).

## Sources

- Local: `src/sase/attachments/markdown_pdf.py` (also: `index.json`
  write is not atomic at lines 146-149 — fix-in-passing candidate)
- Local: `src/sase/sdd/frontmatter.py` (YAML frontmatter parser
  already in the repo)
- Local: `tests/test_markdown_pdf.py` (test-fixture pattern to mirror)
- Local: `src/sase/core/agent_artifact_types.py` (artifact kinds, schema
  version, `infer_artifact_kind`)
- Local: `src/sase/integrations/_mobile_notification_attachments.py`
  (MIME / kind classification)
- Local: `src/sase/ace/tui/graphics/_viewer_render.py` (artifact viewer
  dispatch, lines 201-232)
- Local: `src/sase/xprompt/_catalog_render.py` (existing HTML / Jinja2
  pipeline for xprompt catalogs)
- Local: `src/sase/ace/tui/util/lazy_syntax.py` (Rich Syntax usage for
  inline Markdown display)
- Local: `mkdocs.yml` + `docs/blog/posts/` (existing Markdown→HTML
  pipeline for the public site)
- Local: `sdd/research/202605/markdown_view_image_keymap.md` (HTML→PNG
  alternative, rejected for the `V` keymap)
- Local: `sdd/research/202604/tui_image_pdf_support.md` (PDFium decision,
  tmux/SSH detail, inline-render path)
- Local: `sdd/research/202605/android_mobile_rust_core_api.md` (Rust-core
  boundary motivation for shared backend behavior)
- Local: `memory/short/rust_core_backend_boundary.md`
- `markdown-it-py` docs: https://markdown-it-py.readthedocs.io/en/latest/
- `mdit-py-plugins`: https://mdit-py-plugins.readthedocs.io/en/latest/
- `nh3` (Rust-based HTML sanitizer, successor to `bleach`):
  https://nh3.readthedocs.io/en/latest/
- `bleach` deprecation notice: https://github.com/mozilla/bleach
- Pygments HTML formatter:
  https://pygments.org/docs/formatters/#HtmlFormatter
- Rich Markdown renderer (terminal, not HTML):
  https://rich.readthedocs.io/en/stable/markdown.html
- MkDocs Material Markdown extensions:
  https://squidfunk.github.io/mkdocs-material/setup/extensions/
- Playwright Python (HTML→PNG candidate for v2):
  https://playwright.dev/python/docs/api/class-page#page-screenshot
- wkhtmltoimage / wkhtmltopdf upstream archive notice:
  https://github.com/wkhtmltopdf/wkhtmltopdf
- glow (CLI Markdown viewer): https://github.com/charmbracelet/glow
- mdcat (CLI Markdown viewer): https://github.com/swsnr/mdcat
- frogmouth (Textual-based Markdown viewer):
  https://github.com/Textualize/frogmouth
- Telegram Bot API HTML parse-mode tag allowlist:
  https://core.telegram.org/bots/api#html-style
- `mermaid-cli` (server-side mermaid → SVG):
  https://github.com/mermaid-js/mermaid-cli
- MDN iframe `sandbox` reference:
  https://developer.mozilla.org/en-US/docs/Web/HTML/Element/iframe#sandbox

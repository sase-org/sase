# `sase.sh` Single PDF Download Research

Date: 2026-05-09

## Question

How should `sase.sh` let users download all SASE documentation and blog articles as one polished PDF, while keeping the
current MkDocs Material site workflow?

## Short Answer

Generate a static PDF during the docs build and publish it as a normal site asset, e.g.
`https://sase.sh/downloads/sase-handbook.pdf`. Do not generate it per request.

The best first implementation path is:

1. Add a PDF-specific MkDocs config, probably `mkdocs-pdf.yml`, that inherits the current site structure but enables PDF
   generation only for explicit PDF builds.
2. Prototype `mkdocs-to-pdf` first because it is made for MkDocs, supports Material/PyMdown content, generates a cover
   and table of contents, and writes directly into the built `site/` directory.
3. Keep a fallback path using `mkdocs-print-site-plugin` plus Playwright/Chromium if `mkdocs-to-pdf` cannot include
   Material blog posts cleanly or if browser-rendered visual fidelity matters more than a pure Python build.
4. Add one visible download link in the homepage hero/next-clicks area and one in the docs nav/reference area. The link
   should point at a stable URL such as `/downloads/sase-handbook.pdf`.

The key design choice is to treat the PDF as a release artifact of the static site, not as another dynamic service.

## Current Site Context

The repo currently uses:

- `mkdocs.yml` with `theme.name: material`.
- `docs_dir: docs`, `site_dir: site`, `site_url: https://sase.sh/`, and `use_directory_urls: true`.
- Material blog plugin with `post_url_format: "{slug}"`.
- `mkdocs-rss-plugin`.
- A curated `nav:` that includes docs, blog home, and the agentic software engineering series hub.
- `docs/stylesheets/extra.css` for custom visual polish.
- Cloudflare Pages conventions through `docs/_headers` and `docs/_redirects`.

Current content that must be included:

- Documentation pages under `docs/*.md`.
- The series hub at `docs/series/agentic-software-engineering.md`.
- Blog articles under `docs/blog/posts/*.md`, currently including
  `docs/blog/posts/why-coding-agents-need-orchestration.md`.

Important implication: Material's blog plugin generates post pages from `docs/blog/posts/*.md`. Any PDF pipeline must
confirm whether it includes generated blog post pages, not just explicit `nav:` entries.

## Evaluation Criteria

- **Single direct download:** the website should offer one `.pdf` URL, not "print this page yourself" as the primary
  experience.
- **Covers docs and blog posts:** no silent omission of generated Material blog article pages.
- **Looks intentional:** cover page, table of contents, page numbers, readable code blocks, good image scaling, and
  predictable page breaks.
- **Fits static hosting:** output should live under `site/` and deploy through the same Cloudflare Pages static asset
  path.
- **Low operational risk:** avoid a runtime PDF service, queue, Worker, or server-side render path unless the static
  build approach fails.
- **Reproducible:** local `just docs-check` should stay fast; PDF generation should be opt-in or isolated so normal docs
  iteration does not pay the PDF cost every time.

## Options

### Option A: `mkdocs-to-pdf`

`mkdocs-to-pdf` is a maintained fork of `mkdocs-with-pdf` that generates a PDF from a MkDocs repository. Its docs call
out support for MkDocs Material, PyMdown extensions, an automatically generated cover page, table of contents, and
numbered headings.

Relevant source notes:

- The plugin is specifically "to generate a PDF from an MkDocs repository" and lists Material/PyMdown support plus
  cover/TOC features: <https://mkdocs-to-pdf.readthedocs.io/>
- Usage is just adding `to-pdf` as a MkDocs plugin; `mkdocs build` then converts articles to PDF:
  <https://mkdocs-to-pdf.readthedocs.io/en/stable/usage/>
- It can write to a configured `output_path` under `site/`, and supports `enabled_if_env` so PDF generation can be
  gated behind an environment variable:
  <https://mkdocs-to-pdf.readthedocs.io/en/stable/usage/>
- It depends on WeasyPrint, which has OS-specific dependencies:
  <https://mkdocs-to-pdf.readthedocs.io/en/stable/installation/>

Pros:

- Closest match to "one downloadable PDF from MkDocs."
- Python-native, which fits this repo better than introducing a full JavaScript build stack.
- Built-in cover, TOC, heading numbering, headers/footers, and output path options.
- `enabled_if_env` lets normal `mkdocs serve` and `just docs-check` stay lightweight.
- Output can be a static file under `site/downloads/sase-handbook.pdf`.

Cons and risks:

- WeasyPrint native/system dependencies can be the main friction point, especially on hosted build environments.
- Browser-only behavior, client-side JavaScript, and some complex CSS may not match Material's browser output exactly.
- Need a prototype to confirm generated Material blog post pages are included in the combined PDF.
- If Mermaid or other client-rendered diagrams are added later, they may need offline pre-rendering before WeasyPrint.

Implementation shape:

```yaml
# mkdocs-pdf.yml
INHERIT: mkdocs.yml

plugins:
  - search
  - blog:
      post_url_format: "{slug}"
  - rss:
      match_path: blog/posts/.*
      use_git: false
      date_from_meta:
        as_creation: date
      categories:
        - categories
      image: https://sase.sh/images/sase_overview.jpg
  - to-pdf:
      enabled_if_env: SASE_DOCS_PDF
      output_path: downloads/sase-handbook.pdf
      cover_title: Structured Agentic Software Engineering
      cover_subtitle: Documentation and Articles
      toc_level: 3
      ordered_chapter_level: 2
```

Build command:

```bash
SASE_DOCS_PDF=1 mkdocs build -f mkdocs-pdf.yml --strict
```

Recommendation for this option: prototype first. If the PDF includes all docs and blog posts and looks acceptable after
targeted CSS, keep it.

### Option B: `mkdocs-print-site-plugin` Plus Playwright

`mkdocs-print-site-plugin` adds a combined single-page version of the MkDocs site. Its docs describe a page that combines
all pages and can be saved as PDF from the browser. The docs also mention automating PDF creation with headless Chrome.

Relevant source notes:

- The plugin creates a combined page for the whole site:
  <https://timvink.github.io/mkdocs-print-site-plugin/print_page.html>
- The generated page is available at `/print_page/` or `/print_page.html`, depending on `use_directory_urls`, and can be
  saved as PDF from a browser:
  <https://timvink.github.io/mkdocs-print-site-plugin/how-to/export-PDF.html>
- It supports cover page, table of contents, heading/figure enumeration, full URL expansion, and content exclusion with
  `.print-site-plugin-ignore`:
  <https://timvink.github.io/mkdocs-print-site-plugin/print_page.html>
- Playwright can emulate print media, which is useful for deterministic PDF styling:
  <https://playwright.dev/docs/api/class-page>
- Chromium exposes `Page.printToPDF` controls such as paper size, margins, backgrounds, and page ranges:
  <https://chromedevtools.github.io/devtools-protocol/tot/Page/>

Pros:

- Browser rendering is usually closer to the live `sase.sh` visual design than WeasyPrint.
- The combined HTML page is inspectable at a URL, so PDF debugging is easier.
- Avoids WeasyPrint's Pango/Cairo dependency path.
- Works well with custom `@media print` CSS in `docs/stylesheets/extra.css`.

Cons and risks:

- Requires adding Node/Playwright or another Chromium automation path to the docs build.
- Cloudflare Pages may not be the best place to run a headless browser; GitHub Actions would be safer for PDF generation.
- Still needs validation that generated blog post pages are included.
- More moving parts than `mkdocs-to-pdf`: combined HTML page, local server, browser automation, PDF copy into `site/`.

Implementation shape:

1. Add `mkdocs-print-site-plugin` to a PDF-specific docs requirements file or optional dependency group.
2. Add `print-site` at the end of the plugin list so it sees changes from earlier plugins.
3. Build the site.
4. Serve `site/` locally in CI.
5. Use Playwright/Chromium to open `/print_page/`, emulate print media, and write `site/downloads/sase-handbook.pdf`.
6. Deploy `site/` after the PDF exists.

Recommendation for this option: use it if `mkdocs-to-pdf` cannot include or style the blog/docs corpus well enough.

### Option C: Pandoc Book Pipeline

Pandoc can produce PDFs from Markdown using LaTeX or another PDF engine. Its manual documents PDF output through a
`.pdf` target and `--pdf-engine`, and it supports a broad Markdown feature set.

Relevant source:

- Pandoc PDF generation and `--pdf-engine`: <https://pandoc.org/MANUAL.html>

Pros:

- Very mature for book-like documents.
- Strong for citations, front matter, templates, LaTeX-grade typography, and long-form PDF publishing.
- Good if SASE eventually wants a separate "SASE Handbook" manuscript rather than a direct site export.

Cons and risks:

- Would bypass much of the existing MkDocs Material rendering path.
- Requires mapping Material/PyMdown features, admonitions, tabs, HTML blocks, blog metadata, and internal links into a
  separate book format.
- Higher editorial maintenance burden because the PDF could drift from the website.

Recommendation for this option: avoid for the first implementation. Reconsider only if the PDF becomes a separately
edited book.

### Option D: Custom Python Aggregator Plus WeasyPrint

This would read MkDocs configuration/content, render or extract page HTML, build a custom single-book HTML template, and
run WeasyPrint directly.

Relevant source:

- WeasyPrint can render HTML/CSS to a single PDF through the CLI or Python API, and supports custom stylesheets:
  <https://doc.courtbouillon.org/weasyprint/stable/first_steps.html>

Pros:

- Maximum control over cover, ordering, page breaks, generated front matter, exclusions, and metadata.
- Python-native and testable.
- Can be made deterministic and tailored to SASE.

Cons and risks:

- Reimplements work that MkDocs plugins already do.
- Must carefully preserve MkDocs Markdown extension behavior and Material/blog page generation.
- Highest implementation cost among realistic static options.

Recommendation for this option: keep as a later fallback if off-the-shelf plugins fail in ways that are easy to define
but hard to patch upstream.

## Recommended Implementation

Start with Option A and structure it so Option B can replace the PDF renderer without changing the public URL.

### Phase 1: Prototype `mkdocs-to-pdf`

Create a separate PDF build path:

- Add `mkdocs-to-pdf` to docs-only dependencies, not the base runtime dependencies.
- Add `mkdocs-pdf.yml` with `INHERIT: mkdocs.yml`.
- Enable `to-pdf` only in `mkdocs-pdf.yml`.
- Gate with `SASE_DOCS_PDF=1`.
- Output to `downloads/sase-handbook.pdf`.

Validation checklist:

- The PDF contains every `docs/*.md` page that appears in the nav.
- The PDF contains every file under `docs/blog/posts/*.md`, not just `docs/blog/index.md`.
- Internal links are usable enough for reader navigation.
- Images are included and scaled sanely.
- Code blocks do not overflow page width.
- The generated PDF has a cover, TOC, page numbers, and useful PDF bookmarks.

If generated blog posts are missing, either:

- add explicit blog post entries to the PDF nav/config if the plugin supports that cleanly, or
- move to Option B.

### Phase 2: Polish The PDF Surface

Add PDF-specific CSS rather than overloading the website design:

- Keep the web homepage expressive, but make the PDF feel like a technical handbook.
- Hide website-only controls, buttons, nav chrome, RSS links, and marketing CTAs.
- Add forced page breaks before top-level docs sections and blog posts.
- Keep code blocks readable with smaller type, wrapping where necessary, and enough contrast on white paper.
- Use the SASE overview image on the cover or first interior page only if it survives print scaling.
- Prefer light theme colors for print even when the reader's browser/site theme is dark.

Potential file layout:

```text
docs/stylesheets/extra.css
docs/stylesheets/pdf.css
mkdocs.yml
mkdocs-pdf.yml
```

### Phase 3: Add The Download Entry Points

Add links after the PDF is reliably generated:

- Homepage hero secondary action: `Download PDF`.
- Footer or nav item: `PDF Handbook`.
- Blog index/sidebar note: `Download docs and articles as PDF`.
- Optional `_headers` rule for the PDF:

```text
/downloads/*.pdf
  Content-Type: application/pdf
  Cache-Control: public, max-age=3600
```

Use a short cache duration at first because the PDF will change often while the docs/blog are growing. Increase later
when the publishing cadence stabilizes.

### Phase 4: CI/Deploy Strategy

Prefer one of these:

1. **Cloudflare Pages builds everything** if `mkdocs-to-pdf` and WeasyPrint dependencies work reliably in the Pages build
   image.
2. **GitHub Actions builds the full `site/` and deploys prebuilt assets to Cloudflare Pages** if PDF generation needs
   system packages or headless browser dependencies that are awkward in Pages.

Cloudflare Pages' current build image supports Python and Node and can pin language versions through environment
variables or version files, but native PDF/browser dependencies are still the risk to prove early:
<https://developers.cloudflare.com/pages/configuration/build-image/>

## Open Questions To Resolve In A Spike

- Does `mkdocs-to-pdf` include Material blog plugin post pages by default?
- Does the generated table of contents place blog posts where SASE wants them, or only according to current nav order?
- Are image-heavy infographic pages too large for a single PDF?
- Should the PDF include generated prompt files under `docs/images/*.prompt.md`? They currently build as pages under
  `site/images/...`, but they may not belong in a public handbook.
- Should the PDF include runbooks like `mobile_mvp_runbook.md` and `perf_runbook.md`, or should "all docs" literally
  mean every public docs page?
- Is the intended artifact "latest only" or should releases archive versioned PDFs later?

## Decision

Prototype `mkdocs-to-pdf` first because it has the shortest path to a direct static PDF download and matches the current
Python/MkDocs stack. Keep the public URL renderer-agnostic:

```text
/downloads/sase-handbook.pdf
```

If the prototype fails on generated blog coverage or visual fidelity, switch the renderer to `mkdocs-print-site-plugin`
plus Playwright while keeping the same published PDF URL.

## Sources

- Material blog plugin: <https://squidfunk.github.io/mkdocs-material/plugins/blog/>
- Material customization: <https://squidfunk.github.io/mkdocs-material/customization/>
- MkDocs plugin lifecycle: <https://www.mkdocs.org/dev-guide/plugins/>
- `mkdocs-to-pdf`: <https://mkdocs-to-pdf.readthedocs.io/>
- `mkdocs-to-pdf` usage/options: <https://mkdocs-to-pdf.readthedocs.io/en/stable/usage/>
- `mkdocs-to-pdf` installation/dependencies: <https://mkdocs-to-pdf.readthedocs.io/en/stable/installation/>
- `mkdocs-print-site-plugin`: <https://timvink.github.io/mkdocs-print-site-plugin/print_page.html>
- `mkdocs-print-site-plugin` PDF export: <https://timvink.github.io/mkdocs-print-site-plugin/how-to/export-PDF.html>
- WeasyPrint first steps/API: <https://doc.courtbouillon.org/weasyprint/stable/first_steps.html>
- Playwright `Page` API: <https://playwright.dev/docs/api/class-page>
- Chrome DevTools Protocol `Page.printToPDF`: <https://chromedevtools.github.io/devtools-protocol/tot/Page/>
- Pandoc manual: <https://pandoc.org/MANUAL.html>
- Cloudflare Pages build image: <https://developers.cloudflare.com/pages/configuration/build-image/>

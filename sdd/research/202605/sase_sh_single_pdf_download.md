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
2. Prototype two candidates side-by-side on the same `mkdocs-pdf.yml` skeleton, then pick a winner:
   - `mkdocs-exporter` (Playwright + Paged.js, actively maintained, MIT, last release 2024-10-29). Has a built-in
     aggregator that combines all pages into one PDF.
   - `mkdocs-to-pdf` (WeasyPrint, fork of `mkdocs-with-pdf`). Pure-Python, no headless browser, but the upstream parent
     has not released since 2021-07 — verify the fork's release cadence as the first step of the spike.
3. Keep a fallback path using `mkdocs-print-site-plugin` plus Playwright/Chromium if neither plugin can include Material
   blog posts cleanly or if visual fidelity is unacceptable.
4. Add one visible download link in the homepage hero/next-clicks area and one in the docs nav/reference area. The link
   should point at a stable URL such as `/downloads/sase-handbook.pdf`.

The key design choice is to treat the PDF as a release artifact of the static site, not as another dynamic service.

The hard constraint to remember from the start: **Cloudflare Pages caps a single asset at 25 MiB**. A combined
docs+blog PDF with images can plausibly exceed that. The mitigations — splitting into two PDFs, hosting on R2 with a
custom subdomain, or aggressive image downsampling — should be picked before implementation begins.

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
- **Covers docs and blog posts:** no silent omission of generated Material blog article pages, and `draft: true` posts
  must be excluded.
- **Looks intentional:** cover page, table of contents, page numbers, readable code blocks, good image scaling, and
  predictable page breaks.
- **Fits static hosting:** output should live under `site/`, stay under Cloudflare Pages' **25 MiB per-file limit**,
  and complete within Pages' **20-minute build cap** when built in CI.
- **Accessible:** the PDF should be tagged (PDF/UA-style) and contain a usable bookmark outline, not just a flat scroll.
  This matters for screen reader users and is a low-cost win when the renderer supports it.
- **JS-rendered content:** any client-rendered diagram (Mermaid via Material's superfences, KaTeX/MathJax if added
  later) must either be pre-rendered to SVG/PNG before PDF generation or skipped intentionally — silent blanks are not
  acceptable.
- **Low operational risk:** avoid a runtime PDF service, queue, Worker, or server-side render path unless the static
  build approach fails.
- **Reproducible:** local `just docs-check` should stay fast; PDF generation should be opt-in or isolated so normal docs
  iteration does not pay the PDF cost every time.

## Constraints From Hosting And Build

These are not preferences — they are hard limits the chosen pipeline must respect.

### Cloudflare Pages Asset And Build Limits

- **25 MiB per file.** Cloudflare Pages refuses to deploy any single asset larger than 25 MiB. Workaround paths if the
  combined PDF gets close to that ceiling: split into "Docs Handbook" and "Blog Compendium" PDFs, pre-process images to
  reduce embedded resolution, or move PDF hosting to Cloudflare R2 behind a custom subdomain such as
  `https://downloads.sase.sh/sase-handbook.pdf`.
- **20-minute build timeout.** Pages cancels builds that exceed 20 minutes. Headless-browser pipelines
  (`mkdocs-exporter`, `mkdocs-print-site-plugin` + Playwright) are the most likely to brush this ceiling on a cold
  build because Chromium downloads, fonts, and per-page navigation add up fast.
- **20,000 file deployment cap on the free plan.** Not relevant for a single PDF, but the build environment shares this
  limit with everything else `site/` produces.
- **Source:** <https://developers.cloudflare.com/pages/platform/limits/>

### Material Blog Plugin Quirks

- Posts under `docs/blog/posts/*.md` are generated dynamically by the blog plugin. Any PDF/print plugin must run
  **after** the `blog` plugin in the MkDocs `plugins:` list so the generated post pages are visible in the file/nav set
  that the PDF plugin walks. Plugin order in `mkdocs.yml` is the configuration knob here.
- The blog plugin already filters drafts via `draft: false` (default) and `draft_if_future_date`. The PDF build must
  inherit `draft: false` so unpublished posts do not leak into the public PDF — this is automatic if `mkdocs-pdf.yml`
  uses `INHERIT: mkdocs.yml` and does not override the blog plugin block.
- **Source:** <https://squidfunk.github.io/mkdocs-material/plugins/blog/>

### JavaScript-Rendered Content

- WeasyPrint executes **no JavaScript at all**. Material's Mermaid integration relies on a client-side renderer, so any
  `mermaid` block in a docs page or blog post will appear as a raw fenced code block in WeasyPrint output unless
  pre-rendered. Same caveat for KaTeX, MathJax, syntax highlighting features that depend on JS, and any custom JS
  widgets.
- Chromium-based pipelines (`mkdocs-exporter`, Playwright over print-site) do execute JS and generally render Mermaid
  fine, but only after the page settles — a deterministic wait or a `waitFor*` hook is needed for reliability.
- Recommended posture for the SASE corpus today: there are no Mermaid blocks in the current docs (verify in the spike),
  so either renderer is fine. If/when Mermaid lands, prefer pre-rendering with the Mermaid CLI to SVG so both renderers
  produce identical output, rather than relying on Chromium-side execution timing.
- **Source:** <https://doc.courtbouillon.org/weasyprint/stable/features.html>

## Options

### Option A: `mkdocs-to-pdf`

`mkdocs-to-pdf` is a fork of `mkdocs-with-pdf` that generates a PDF from a MkDocs repository. Its docs call out support
for MkDocs Material, PyMdown extensions, an automatically generated cover page, table of contents, and numbered
headings.

**Lineage caveat the spike must clear before committing to this option:** the upstream parent `mkdocs-with-pdf` has not
released since 2021-07-03 (v0.9.3) and is classified as Beta on PyPI. The fork's release cadence and open-issue
backlog should be the first thing the spike checks — if the fork is also stale, this option's apparent "Python-native
simplicity" advantage evaporates because WeasyPrint and Material both keep moving.

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

### Option C: `mkdocs-exporter`

`mkdocs-exporter` (Adrien Brignon, MIT, latest release v6.2.0 on 2024-10-29) is the most modern entry. It pairs
Playwright with the Paged.js polyfill so the printed output uses the same CSS Paged Media features as a browser print
dialog, and it explicitly supports an aggregator step that combines every page into one PDF — exactly the artifact this
research is about.

Relevant source notes:

- PyPI page for `mkdocs-exporter`: <https://pypi.org/project/mkdocs-exporter/>
- GitHub repo: <https://github.com/adrienbrignon/mkdocs-exporter>
- Plugin name to register in `mkdocs.yml`: `exporter`. Requires Python ≥3.9 and MkDocs ≥1.4.

Pros:

- Single combined PDF is a first-class feature, not an afterthought.
- Browser-grade rendering for Mermaid, syntax highlighting, complex CSS, and any future JS-rendered content.
- Concurrent per-page rendering keeps wall-clock build time low even with many pages.
- Active development: most recent of the three plugin candidates.
- MIT licensed, no LGPL/Pango/Cairo dependency chain.

Cons and risks:

- Headless Chromium adds ~150–300 MiB of build dependencies and meaningful cold-start time, which presses against
  Cloudflare Pages' 20-minute build cap. GitHub Actions is the safer build host.
- Paged.js is a polyfill — page break rules and running headers behave subtly differently from native print. Expect
  some print-CSS iteration.
- One more plugin to keep current with Material theme upgrades.

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
  - exporter:
      formats:
        pdf:
          enabled: !ENV [SASE_DOCS_PDF, false]
          aggregator:
            enabled: true
            output: downloads/sase-handbook.pdf
            covers: front
          stylesheets:
            - docs/stylesheets/pdf.css
          concurrency: 4
```

Recommendation for this option: prototype this in parallel with Option A. If the aggregator output is acceptable on
the first pass, prefer this over Option A because the rendering toolchain is the same one users see in their browser.

### Option D: Pandoc Book Pipeline

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

### Option E: Custom Python Aggregator Plus WeasyPrint

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

Run a one-day spike that prototypes Option A and Option C in parallel against the same `mkdocs-pdf.yml` skeleton, then
pick a winner. Whichever wins, structure the build so the renderer can be swapped later without changing the public
URL.

### Phase 1: Prototype `mkdocs-to-pdf` And `mkdocs-exporter` In Parallel

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

Concrete defaults to start from in `docs/stylesheets/pdf.css` (paged-media features supported by both WeasyPrint and
Paged.js):

```css
@page {
  size: Letter;
  margin: 22mm 18mm 22mm 18mm;
  @top-right { content: "SASE Handbook"; font-size: 9pt; color: #666; }
  @bottom-right { content: counter(page) " / " counter(pages); font-size: 9pt; color: #666; }
}
@page :first { @top-right { content: ""; } @bottom-right { content: ""; } }

h1 { break-before: page; }
h2, h3 { break-after: avoid; }
pre, table, figure { break-inside: avoid; }

.md-header, .md-tabs, .md-sidebar, .md-footer, .md-search, .md-source { display: none !important; }

a[href^="http"]::after { content: " (" attr(href) ")"; font-size: 0.85em; color: #555; }
a[href^="#"]::after, a[href^="/"]::after { content: ""; }

img { max-width: 100%; }
pre, code { font-size: 9.5pt; }
```

Use `Letter` (US default) since the SASE audience skews North American; switch to `A4` only if reader feedback warrants
it. The trailing `(url)` annotation on external links is a print convention — useful in PDF, hidden on the web.

Potential file layout:

```text
docs/stylesheets/extra.css
docs/stylesheets/pdf.css
mkdocs.yml
mkdocs-pdf.yml
```

#### PDF Accessibility

WeasyPrint supports tagged PDFs via the `--pdf-tags` CLI flag and PDF/UA-1 / PDF/UA-2 / PDF/A variants; Chromium
similarly emits a tagged outline by default when generating PDFs. Configure the chosen renderer to:

- Emit tagged PDF output. WeasyPrint: pass `--pdf-tags`; `mkdocs-exporter`: enable `pdf.tags: true` (or equivalent) per
  the plugin's docs at spike time.
- Preserve heading hierarchy so the bookmark outline matches the docs nav.
- Require `alt=` on all images at lint time. Markdown's `![alt](src)` syntax already encodes this; a docs-check rule
  that fails on empty alts is a cheap permanent guarantee.
- Mark the cover image as decorative (`role="presentation"` or empty alt) so screen readers skip it.

Don't pursue formal PDF/UA conformance certification on day one — WeasyPrint explicitly notes generated documents are
not guaranteed to be spec-valid even with the flag set. The pragmatic goal is "screen reader can navigate by heading
and read in order," not a compliance certificate.

**Source:** <https://doc.courtbouillon.org/weasyprint/stable/features.html>

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
  X-Robots-Tag: index, follow
```

Use a short cache duration at first because the PDF will change often while the docs/blog are growing. Increase later
when the publishing cadence stabilizes.

#### Versioning, Filename, And Content-Disposition

Keep the canonical URL stable, but archive dated copies for citation:

```text
/downloads/sase-handbook.pdf                 # always-latest (no Content-Disposition; browsers display inline)
/downloads/archive/sase-handbook-2026-05.pdf # immutable monthly snapshot, cache forever
```

Two link variants on the site:

- `<a href="/downloads/sase-handbook.pdf">View handbook</a>` — opens in browser.
- `<a href="/downloads/sase-handbook.pdf" download="sase-handbook.pdf">Download PDF</a>` — uses the HTML `download`
  attribute to force-save without needing a `Content-Disposition` header.

Embed identity inside the PDF itself so an archived copy is self-describing:

- PDF metadata: `Title=SASE Handbook`, `Author=SASE contributors`, `Subject=Documentation and Articles`,
  `Keywords=sase,sdd,axe,ace,xprompt`.
- Cover footer: build date and short git SHA (e.g. "Built 2026-05-09 from `8b06e68b`"). Both renderers can inject
  this from environment variables at build time.
- Add `<link rel="alternate" type="application/pdf" href="/downloads/sase-handbook.pdf">` to the docs/blog HTML head
  so feed readers and crawlers can find the PDF. Include the URL in `sitemap.xml` as well.

### Phase 4: CI/Deploy Strategy

Prefer one of these:

1. **Cloudflare Pages builds everything** if `mkdocs-to-pdf` and WeasyPrint dependencies work reliably in the Pages build
   image.
2. **GitHub Actions builds the full `site/` and deploys prebuilt assets to Cloudflare Pages** if PDF generation needs
   system packages or headless browser dependencies that are awkward in Pages.

Cloudflare Pages' current build image supports Python and Node and can pin language versions through environment
variables or version files, but native PDF/browser dependencies are still the risk to prove early:
<https://developers.cloudflare.com/pages/configuration/build-image/>

For Option C specifically, `actions/setup-python` plus `microsoft/playwright-github-action` (or a manual
`playwright install --with-deps chromium` step) and a cache key on `playwright --version` keeps cold builds well under
the Pages 20-minute window. Pin the Chromium revision in CI so PDF output is deterministic across builds.

### Phase 5: Validation Gate

A PDF that silently drops content is worse than no PDF at all. Add a CI step after PDF generation that asserts:

- File exists at `site/downloads/sase-handbook.pdf` and is non-empty.
- File size is **under 25 MiB** (Cloudflare Pages hard limit). Fail loudly above 22 MiB to leave headroom.
- Page count is at least the number of `docs/*.md` files in the nav plus the number of `docs/blog/posts/*.md` files,
  minus a tolerance. This catches plugin ordering bugs that drop blog posts.
- A grep over the extracted text (via `pdftotext` or `pypdf`) finds known sentinel strings from each major docs
  section and from each published blog post. The sentinel list lives in a small YAML file checked into the repo.
- The PDF passes `qpdf --check` (structural validity) and ideally `verapdf` if PDF/UA conformance is being claimed.

This validation runs in the same job as `mkdocs build`, so a broken PDF blocks deploy the same way a broken site does.

### Phase 6: Download Telemetry

Once the PDF is reachable, measure use:

- Cloudflare Web Analytics records `Content-Type: application/pdf` requests by default — no extra code needed for
  basic counts.
- For richer event tracking (referrer, country, repeat downloads), add a lightweight Cloudflare Worker on the
  `/downloads/sase-handbook.pdf` route that logs to a Workers Analytics Engine dataset before serving the asset. Keep
  the Worker simple — fetch from origin and pass through — so it does not become a critical path.
- Avoid client-side analytics on the download click because most clients (curl, wget, RSS readers, email previewers)
  never run JS.

## Open Questions To Resolve In A Spike

- Does `mkdocs-to-pdf` include Material blog plugin post pages by default? Does `mkdocs-exporter`'s aggregator?
- Does the generated table of contents place blog posts where SASE wants them, or only according to current nav order?
- Are image-heavy infographic pages too large for a single PDF? Specifically, what is the byte size of the combined
  PDF on the current corpus, and how close is it to the 25 MiB Cloudflare Pages limit?
- What is the actual cold-build wall-clock time for `mkdocs-exporter` on the current corpus in GitHub Actions, and is
  it under 8 minutes (a comfortable margin below Pages' 20-minute cap if we ever move builds back to Pages)?
- Is the `mkdocs-to-pdf` fork itself actively maintained (recent releases, low issue churn), or has it stalled like its
  upstream parent? This is the gating question for keeping Option A as a serious candidate.
- Should the PDF include generated prompt files under `docs/images/*.prompt.md`? They currently build as pages under
  `site/images/...`, but they may not belong in a public handbook.
- Should the PDF include runbooks like `mobile_mvp_runbook.md` and `perf_runbook.md`, or should "all docs" literally
  mean every public docs page?
- Is the intended artifact "latest only" or should releases archive versioned PDFs later?
- Should the docs PDF and blog PDF be **one combined artifact** or **two separate artifacts**? Splitting hedges
  against the 25 MiB limit and lets the blog PDF refresh on a faster cadence without touching the docs PDF cache.
- Should the blog plugin's `draft_if_future_date` be flipped on so a future-dated post is auto-drafted out of both the
  site and the PDF until its date arrives?

## Decision

Run a one-day spike that prototypes Option A (`mkdocs-to-pdf`) **and** Option C (`mkdocs-exporter`) against the same
`mkdocs-pdf.yml` skeleton, then pick the renderer whose output is acceptable with the least CSS work. Lean toward
Option C if the spike shows it produces a clean combined PDF — its renderer matches what users see in the browser, it
is the most actively maintained of the three plugin candidates, and Mermaid/JS-rendered content "just works" if it
appears later. Lean toward Option A only if its dependency footprint is meaningfully simpler and the fork has visible
recent activity.

Either way, keep the public URL renderer-agnostic:

```text
/downloads/sase-handbook.pdf
```

If both prototypes fail on generated blog coverage or visual fidelity, fall back to Option B
(`mkdocs-print-site-plugin` plus Playwright) while keeping the same published PDF URL.

## Sources

- Material blog plugin: <https://squidfunk.github.io/mkdocs-material/plugins/blog/>
- Material customization: <https://squidfunk.github.io/mkdocs-material/customization/>
- MkDocs plugin lifecycle: <https://www.mkdocs.org/dev-guide/plugins/>
- `mkdocs-to-pdf`: <https://mkdocs-to-pdf.readthedocs.io/>
- `mkdocs-to-pdf` usage/options: <https://mkdocs-to-pdf.readthedocs.io/en/stable/usage/>
- `mkdocs-to-pdf` installation/dependencies: <https://mkdocs-to-pdf.readthedocs.io/en/stable/installation/>
- `mkdocs-with-pdf` (parent project, last release 2021-07): <https://pypi.org/project/mkdocs-with-pdf/>
- `mkdocs-exporter` PyPI: <https://pypi.org/project/mkdocs-exporter/>
- `mkdocs-exporter` repo: <https://github.com/adrienbrignon/mkdocs-exporter>
- `mkdocs-print-site-plugin`: <https://timvink.github.io/mkdocs-print-site-plugin/print_page.html>
- `mkdocs-print-site-plugin` PDF export: <https://timvink.github.io/mkdocs-print-site-plugin/how-to/export-PDF.html>
- WeasyPrint first steps/API: <https://doc.courtbouillon.org/weasyprint/stable/first_steps.html>
- WeasyPrint features (JS, tagged PDF, paged media, fonts): <https://doc.courtbouillon.org/weasyprint/stable/features.html>
- Paged.js (used by `mkdocs-exporter`): <https://pagedjs.org/>
- Playwright `Page` API: <https://playwright.dev/docs/api/class-page>
- Chrome DevTools Protocol `Page.printToPDF`: <https://chromedevtools.github.io/devtools-protocol/tot/Page/>
- Pandoc manual: <https://pandoc.org/MANUAL.html>
- Cloudflare Pages build image: <https://developers.cloudflare.com/pages/configuration/build-image/>
- Cloudflare Pages limits (25 MiB per file, 20-minute build, file count caps): <https://developers.cloudflare.com/pages/platform/limits/>
- Material blog plugin (post generation, draft handling): <https://squidfunk.github.io/mkdocs-material/plugins/blog/>

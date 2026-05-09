# `sase.sh` Site Design And Structure Research

Date: 2026-05-09

## Question

Now that `https://sase.sh/` is online, what are the realistic options for making it feel beautiful, coherent, and
better structured while preserving the repo-backed docs/blog workflow?

## Short Answer

Keep the current MkDocs Material + Cloudflare Pages stack for the next design iteration. It can be pushed much further
than the current default-looking docs index without a migration:

1. Build a custom public homepage at `/`.
2. Reorganize navigation into product-facing sections instead of a flat reference list.
3. Add a series hub for the launch blog arc.
4. Add a restrained visual identity: logo mark, palette, homepage illustration/screenshot, card-grid entry points,
   better typography rhythm, footer, social cards, RSS, and canonical metadata.
5. Only migrate to Astro Starlight, Docusaurus, or Nextra if SASE later needs substantial custom components, MDX-heavy
   marketing pages, or a multi-product developer portal.

The current site is working, but it reads like generated documentation, not like a project with a thesis. The fastest
path is to keep MkDocs for docs/blog and give the front door enough editorial structure to explain the SASE idea.

## Context Read

Relevant recent chats and local research:

- Recent `sase.sh` setup chats from `~/.sase/chats/202605/`, especially the Cloudflare Pages/custom-domain sequence on
  2026-05-08 and 2026-05-09.
- `sdd/research/202605/cloudflare_pages_sase_blog_launch.md`: chose Cloudflare Pages, MkDocs Material, canonical apex
  `https://sase.sh/`, and blog at `/blog/`.
- `sdd/research/202605/sase_blog_series_platform_decision_matrix.md`: chose canonical-first publishing, with SASE-owned
  static site as the source of truth and DEV/Hashnode/LinkedIn as distribution.
- `sdd/research/202605/blog_series_deep_research.md`: framed the blog series as developer education plus project
  positioning.

Current repo/site state:

- `mkdocs.yml` already uses Material, search, the built-in blog plugin, strict builds, `site_url: https://sase.sh/`, and
  `use_directory_urls: true`.
- `docs/index.md` is mostly a short documentation index with one overview image and flat "Start Here" links.
- `docs/blog/posts/why-coding-agents-need-orchestration.md` is a launch stub, not yet the full first article.
- There are no source-level `docs/stylesheets`, `docs/javascripts`, or `overrides` directories yet.
- The live homepage at `https://sase.sh/` exposes a flat MkDocs navigation list, then a simple intro, image, feature
  list, and start links.
- `docs/_headers` already sets `X-Content-Type-Options`, `Referrer-Policy`, and a year-long immutable cache for
  `/assets/*`. `docs/_redirects` has one rule (`/blog -> /blog/`). Both are Cloudflare Pages conventions and are part of
  the deployed bundle. Any future redirect or security-header work should extend these files rather than introduce new
  mechanisms.
- The blog plugin currently runs with only `post_url_format: "{slug}"` set. No authors file, no `categories_allowed`,
  no excerpt separator, no draft handling, and no RSS plugin.
- `pymdownx.superfences` is enabled but no `custom_fences` are configured, so Mermaid blocks would render as plain code
  today even though the rest of the toolchain is ready for them.

## What MkDocs Material Can Already Do

### 1. Custom visual layer without forking

Material supports adding custom CSS and JavaScript through files under `docs/`, configured via `extra_css` and
`extra_javascript`. It also supports theme extension through `theme.custom_dir`, with overrides for templates and
partials such as `main.html`, `base.html`, `blog.html`, `blog-post.html`, header, footer, nav, social links, and logo.

Source: Material customization docs:
<https://squidfunk.github.io/mkdocs-material/customization/>

Implication for SASE:

- Use `docs/stylesheets/extra.css` for most polish: color tokens, homepage blocks, image treatment, tighter cards,
  footer rhythm, and dark-mode tuning.
- Use `overrides/main.html` or a dedicated home template only if the homepage cannot be expressed cleanly in Markdown
  plus Material's built-in classes.
- Avoid forking Material. The official extension model is enough for this phase.

### 2. Better homepage and index pages with Markdown grids

Material's grid/card reference is explicitly intended for index pages. It supports card grids using `attr_list` and
`md_in_html`, both already enabled in this repo.

Source: Material grid reference:
<https://squidfunk.github.io/mkdocs-material/reference/grids/>

Implication for SASE:

- `docs/index.md` can become a real project front door without leaving Markdown.
- Section index pages can become visual maps for docs areas: "Use SASE", "Core Concepts", "Automation", "Providers",
  "Reference".
- The existing docs can stay Markdown-first, but readers stop landing on a wall of flat nav links.

### 3. Navigation can be structured without changing URLs

Material supports section index pages via `navigation.indexes`; this repo already enables that feature. The official
navigation docs recommend `index.md` files attached to nav sections for overview pages.

Source: Material navigation docs:
<https://squidfunk.github.io/mkdocs-material/setup/setting-up-navigation/>

Implication for SASE:

- Add an explicit `nav:` tree in `mkdocs.yml` instead of relying on filesystem ordering.
- Keep existing URLs stable while changing the left nav shape.
- Group the docs by reader intent:

```yaml
nav:
  - Home: index.md
  - Blog: blog/index.md
  - Start:
      - ACE TUI: ace.md
      - SDD: sdd.md
      - XPrompt: xprompt.md
      - Workflows: workflow_spec.md
  - Concepts:
      - ChangeSpecs: change_spec.md
      - Beads: beads.md
      - Mentors: mentors.md
      - Workspaces: workspace.md
  - Operations:
      - AXE: axe.md
      - Notifications: notifications.md
      - Commit Workflows: commit_workflows.md
      - Performance Runbook: perf_runbook.md
  - Integrations:
      - Plugins: plugins.md
      - VCS: vcs.md
      - LLM Providers: llms.md
      - Mobile Gateway: mobile_gateway.md
  - Reference:
      - Configuration: configuration.md
      - Query Language: query_language.md
      - ProjectSpec: project_spec.md
      - Telemetry: telemetry.md
      - Rust Backend: rust_backend.md
```

This is illustrative, not a final nav spec. The key is to separate "start here" from "full reference".

### 4. Blog can support a real launch series

The built-in Material blog plugin scans `docs/blog/posts`, generates the blog index, archive/category pages, pagination,
post slugs, excerpts, reading time, authors, categories, and draft controls. The setup docs also call out RSS support
through `mkdocs-rss-plugin`.

Sources:

- Material blog plugin: <https://squidfunk.github.io/mkdocs-material/plugins/blog/>
- Material blog setup and RSS: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-a-blog/>

Implication for SASE:

- Keep `/blog/<slug>/` date-free evergreen URLs.
- Add a `/series/agentic-software-engineering/` landing page with the 5-10 part arc, status, and links.
- Add categories sparingly. The current `Agentic Software Engineering` category is fine, but add tags only if there is
  a reader-facing use for them.
- Add RSS now if the blog series will be promoted outside GitHub.

### 5. Social cards and share previews are available

Material has a social plugin that can generate preview images for pages when image-processing dependencies are
installed and `site_url` is set.

Source: Material social cards docs:
<https://squidfunk.github.io/mkdocs-material/setup/setting-up-social-cards/>

Implication for SASE:

- Social cards matter because the publishing strategy depends on link distribution through LinkedIn, DEV, Hashnode,
  Hacker News, Reddit, and AI-agent communities.
- If image-processing dependencies are too much for Cloudflare Pages initially, a simpler first step is a manually
  designed OpenGraph default image plus per-post `image` metadata where supported.

### 6. Mermaid diagrams without extra build steps

Material renders Mermaid client-side via `pymdownx.superfences` `custom_fences`. The runtime is initialized
automatically and inherits the site's fonts and color schemes (light and dark).

Source: <https://squidfunk.github.io/mkdocs-material/reference/diagrams/>

Implication for SASE:

- Architecture diagrams that today live as PNG infographics can be authored in Markdown, version-controlled as text,
  and stay legible across themes. Good fit for: ChangeSpec lifecycle, AXE/ACE process boundaries, retry-chain handoff,
  workspace claim transfer, multi-agent xprompt fan-out, Rust-core/Python boundary.
- The static infographics still have a place for hero/social use, but most internal documentation diagrams should
  migrate to Mermaid so they update with the code.
- One config change is enough:

```yaml
markdown_extensions:
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
```

### 7. Content-rich Markdown features that are off by default

Several Material/PyMdown features that fit a developer-tool docs site are not yet enabled in `mkdocs.yml`:

- `pymdownx.tabbed` (with `alternate_style: true`): code/CLI tabs for Claude / Gemini / Codex examples, or Python /
  Bash variants — directly useful given SASE's runtime-uniform stance.
- `pymdownx.snippets`: include shared fragments (e.g. a one-paragraph definition of ChangeSpec) across multiple pages
  so terminology stays consistent.
- `pymdownx.highlight` plus `pymdownx.inlinehilite` with `linenums`, `anchor_linenums`, and `pymdownx.keys` for
  keyboard chord rendering (relevant for ACE TUI bindings).
- `pymdownx.tasklist` with `custom_checkbox: true`: aligns task lists with the visual style of the rest of the page.
- `pymdownx.emoji` with the Material twemoji shortname index: gives access to Material's icon set (`:material-...:`)
  for inline icons in cards and admonitions.
- `pymdownx.caret`, `pymdownx.tilde`, `pymdownx.mark`, `footnotes`, `abbr`, `def_list`: small typographic primitives
  that make explanatory pages read more like a book and less like a wiki.
- `tags` plugin (built into Material Insiders, available via the open-source `mkdocs-material[tags]`): generate a
  `/tags/` index from `tags:` front matter, useful for cross-cutting topics like "providers", "rust-core", "tui".

Sources:

- PyMdown Extensions reference: <https://facelessuser.github.io/pymdown-extensions/>
- Material content-tabs reference: <https://squidfunk.github.io/mkdocs-material/reference/content-tabs/>
- Material code-blocks reference: <https://squidfunk.github.io/mkdocs-material/reference/code-blocks/>
- Material tags plugin: <https://squidfunk.github.io/mkdocs-material/plugins/tags/>

### 8. Theme features that are off by default

The current `theme.features` list enables only `navigation.indexes`, `navigation.sections`, `navigation.top`,
`search.highlight`, and `search.suggest`. Material exposes more behavior that costs nothing to turn on:

- `navigation.tabs` and `navigation.tabs.sticky`: top-level tabs (Home, Docs, Blog, Series, Reference) — much closer
  to a product site shape than a sidebar-only layout.
- `navigation.instant`, `navigation.instant.progress`: SPA-style page swaps with a progress indicator. Faster perceived
  loads on mobile and Cloudflare Pages.
- `navigation.tracking`: keeps the URL anchor in sync with the active section — handy for deep-linking from blog posts
  to specific concept paragraphs.
- `navigation.path`: breadcrumbs. Useful once nav is grouped.
- `toc.follow`: right-rail TOC follows scroll position.
- `content.code.copy`, `content.code.annotate`, `content.code.select`: copy buttons, annotation callouts, and
  shareable line-range selection on code blocks.
- `content.action.edit`, `content.action.view`: "Edit this page" / "View source" links wired to `repo_url`.
- `content.tabs.link`: synchronize tab choices across pages (so picking "Claude" in one example sets it everywhere).
- `header.autohide`, `announce.dismiss`: usable announcement banner for launch-series posts and release notes.
- `palette` with `media: "(prefers-color-scheme: ...)"` and a toggle: deliberate light/dark scheme rather than
  Material's defaults.

Source: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-navigation/>

## Information Architecture: Diátaxis As The Frame

The current docs are organized by feature name, which is what filesystem ordering produces. Diátaxis (Daniele
Procida) is the de facto framework for technical documentation IA and splits content into four modes by reader
intent:

| Mode         | Reader's question     | Tone                  | SASE example                                           |
| ------------ | --------------------- | --------------------- | ------------------------------------------------------ |
| Tutorials    | "Teach me"            | Learning, hand-held   | "First agent run with ACE", "Your first ChangeSpec"    |
| How-to       | "Help me do X"        | Task-focused, terse   | "Add a new XPrompt", "Cross-post a blog post"          |
| Reference    | "Tell me exactly"     | Dry, complete         | ChangeSpec format, Configuration, Query Language       |
| Explanation  | "Help me understand"  | Discursive, opinion   | "Why SASE", retry-chain rationale, Rust-core boundary  |

Source: <https://diataxis.fr/>

Implication for SASE:

- The proposed nav grouping in the previous "Recommended Structure" section ("Start", "Concepts", "Operations",
  "Integrations", "Reference") maps cleanly onto Diátaxis: "Start" ≈ tutorials, "Operations"/"Integrations" ≈ how-to,
  "Reference" ≈ reference, "Concepts" ≈ explanation.
- Most existing docs (`ace.md`, `axe.md`, `xprompt.md`, ...) currently mix all four modes in one page. They do not
  need to be split immediately, but new content should be written into one mode and linked to the others rather than
  re-explained.
- Use Diátaxis to settle disagreements about where a page belongs. "Where does the workspace doc live?" is a
  Diátaxis question, not an aesthetic one.

## Plugins Worth Adding

In rough order of leverage:

- `mkdocs-rss-plugin` — generates `feed_rss_created.xml` and `feed_rss_updated.xml`. Required for distributing the
  launch series via RSS readers, DEV/Hashnode imports, and aggregator pickups.
  <https://guts.github.io/mkdocs-rss-plugin/>
- Material `social` plugin — auto-generated OpenGraph cards with the site's font and palette; matters for LinkedIn /
  Twitter / DEV / Hacker News previews. Requires Pillow + cairosvg in the build environment.
  <https://squidfunk.github.io/mkdocs-material/setup/setting-up-social-cards/>
- Material `tags` plugin — cross-cutting topical index. Cheap structure for the blog series.
  <https://squidfunk.github.io/mkdocs-material/plugins/tags/>
- `mkdocs-glightbox` — click-to-zoom for screenshots and infographics. Worth it because most SASE images are dense
  diagrams that don't work well at the in-flow size.
  <https://blueswen.github.io/mkdocs-glightbox/>
- `mkdocs-redirects` — declarative source-to-target redirects authored in `mkdocs.yml`. Better than ad-hoc
  `_redirects` rules for content moves because it stays inside the build (and produces `meta refresh` HTML for
  generators that don't read Cloudflare's file).
  <https://github.com/mkdocs/mkdocs-redirects>
- `mkdocs-awesome-nav` (formerly `mkdocs-awesome-pages-plugin`) — per-directory `.nav.yml` files plus glob patterns,
  rather than one giant `nav:` tree. Reasonable once docs split into many subfolders.
  <https://github.com/lukasgeiter/mkdocs-awesome-nav>
- `mkdocs-git-revision-date-localized-plugin` — "last updated" stamp on each page from git history. Gives the docs
  an obvious recency signal.
  <https://timvink.github.io/mkdocs-git-revision-date-localized-plugin/>
- Material `optimize` plugin — recompresses PNG/JPEG/SVG at build time. Useful given the existing infographic-heavy
  image directory.
  <https://squidfunk.github.io/mkdocs-material/plugins/optimize/>
- `mkdocs-minify-plugin` — minifies HTML/CSS/JS. Marginal on Cloudflare Pages (which already compresses), but
  trivial to add.
  <https://github.com/byrnereese/mkdocs-minify-plugin>

Each plugin is a single `pip install` plus a few lines in `mkdocs.yml` and is reversible. Avoid adopting all of them
at once; the RSS, social, tags, and glightbox plugins are the high-leverage four.

## Diagrams and Recorded Demos

Beyond static PNG infographics:

- **Mermaid in Markdown** — see "What MkDocs Material Can Already Do" §6. First-class for state machines, flows, and
  sequence diagrams. Minimal cost.
- **D2** (`d2lang.com`) — alternative diagram-as-code language with a more designed default look. Output is SVG.
  Either rendered offline and committed, or via `mkdocs-d2-plugin`. Use when Mermaid's default look feels too
  "wireframe-y" for hero diagrams. <https://d2lang.com/>
- **Excalidraw** — hand-drawn aesthetic diagrams; export as SVG and embed. Pairs well with explanatory ("why")
  pages where a slightly informal sketch reads better than a formal UML-ish diagram.
  <https://excalidraw.com/>
- **asciinema** — record terminal sessions as `.cast` JSON, embed via the asciinema-player web component. Plays
  back as text, so it's accessible, copy-pasteable, and tiny. Best for interactive REPL/CLI tours.
  <https://asciinema.org/>
- **VHS** by Charm — script terminal recordings as `.tape` files; outputs GIF/MP4/WebM/PNG sequences. Reproducible,
  CI-able, and version-controlled alongside code. Better than asciinema for marketing/blog hero clips because it
  produces an actual rendered video and looks polished by default.
  <https://github.com/charmbracelet/vhs>
- **Static infographics** — the existing `docs/images/*-infographic.png` family is good and should stay. Treat it
  as the "hero/social" tier; Mermaid as the "in-flow concept" tier; VHS/asciinema as the "show, don't tell" tier.

## Cloudflare Pages Capabilities Beyond Hosting

Pages is more than static file serving, and SASE is leaving most of it on the table:

- **`_headers`** — already in repo. Worth extending with a strict `Content-Security-Policy`, `Permissions-Policy`,
  and `X-Frame-Options: DENY`. CSP needs care for Material's inline styles (uses `style-src 'self' 'unsafe-inline'`
  in practice) and Mermaid (`script-src` for the JS bundle). Validate via securityheaders.com and Cloudflare's CSP
  observatory.
- **`_redirects`** — already in repo. Use for legacy URL coverage as the IA changes (e.g. `/docs/...` aliases if you
  ever move docs under `/docs/`). Combine with the `mkdocs-redirects` plugin for in-build coverage.
- **Cloudflare Web Analytics** — privacy-first, cookie-free, free on all plans. One JS snippet. Works on any static
  site without DNS-proxying, so it is compatible with Cloudflare Pages out of the box. Comparable in spirit to
  Plausible/Umami; less feature-rich, but free and zero-config.
  <https://developers.cloudflare.com/web-analytics/>
- **Cloudflare Pages Functions** — tiny edge handlers in `functions/`. Almost certainly not needed for a docs site,
  but worth knowing for things like a future `/api/share-preview` or short-link redirector.
  <https://developers.cloudflare.com/pages/functions/>
- **Cache rules and Speed → Optimization** — Brotli, early hints, and HTTP/3 are on by default; Cloudflare's image
  resizing/transformations are paid features and not necessary for this site.
- **Branch previews** — every Pages deployment gets a preview URL. Hook a "Preview docs" link into PRs and use that
  to review design changes before merging to `master`.

## SEO, Metadata, and Discoverability

Already in place: canonical `site_url`, `use_directory_urls`, sitemap.xml (auto-generated by MkDocs), per-page
titles and descriptions when `description:` is set in front matter.

Gaps:

- No `robots.txt`. Add one (allow all, point at `/sitemap.xml`).
- No site-wide default OpenGraph/Twitter image. Until the social plugin is configured, ship a hand-designed
  `docs/images/sase-og.png` (1200×630) and reference it in an `overrides/partials/meta.html` partial or via
  `extra` metadata.
- No JSON-LD. For the homepage and key reference pages, add a `SoftwareApplication` or `TechArticle` JSON-LD block
  through a template override. Modest SEO benefit, real benefit for AI-search and "feature snippet" coverage.
- No per-post structured front matter on existing blog posts (`description`, `image`, `authors`). The decision-matrix
  research already chose canonical-first publishing — that strategy depends on these fields existing.
- No "edit this page on GitHub" link. `theme.features: [content.action.edit, content.action.view]` plus an
  `edit_uri` setting in `mkdocs.yml` is enough.

## Analytics Options

Material has a built-in `extra.analytics` block that supports Google Analytics 4 and Plausible, plus a feedback
widget ("Was this page helpful?") that posts events to whichever analytics provider is configured.

Source: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-site-analytics/>

Recommendation order:

1. **Cloudflare Web Analytics** — free, privacy-first, no cookies, no consent banner, already in the same vendor
   account, zero new infra. Right default for SASE.
2. **Plausible** or **Umami** (self-hosted) — if more granular event tracking is needed than Cloudflare's
   page-level data, both are GDPR-friendly and have first-class Material integration patterns.
3. **GoatCounter** — minimalist, very cheap; good for a side-project mindset.
4. **Google Analytics 4** — only if there is a specific reason (existing org dashboards, ad attribution). Otherwise
   the privacy/consent overhead is not worth it for a docs/blog site.

Whichever is picked, wire the Material feedback widget so blog posts can collect a "was this useful?" signal —
particularly valuable for the launch series.

## Comments via Giscus

Giscus stores comments as GitHub Discussions and is the documented Material recommendation. It's a fit for SASE
because the readership is GitHub-native and the org already exists.

Source: <https://squidfunk.github.io/mkdocs-material/setup/adding-a-comment-system/>

Setup outline:

1. Enable Discussions on `sase-org/sase` (or a dedicated `sase-org/sase-discussions` if comments should not live on
   the main repo).
2. Install the Giscus GitHub App.
3. Generate a config snippet at `giscus.app`.
4. Override `overrides/partials/comments.html` with the snippet plus a small `postMessage` block that mirrors the
   site's color palette into Giscus.
5. Opt pages in by setting `comments: true` in front matter (or recursively via a `.meta.yml`).

Recommendation: enable on blog posts only. Reference and tutorial pages don't need comments and tend to attract
low-signal noise.

## Search Beyond The Default

- **MkDocs Material default** (Lunr-based) — already enabled, runs entirely in the browser. Fine for the current
  site size. Watch the JSON index size as docs grow; once it crosses ~1 MB the perceived load on cold cache hurts.
- **Pagefind** — modern static-site search that builds an on-disk fragment index and only loads the bits it needs.
  Better than Lunr at scale; not a Material first-class plugin but easy to integrate via a custom partial.
  <https://pagefind.app/>
- **Algolia DocSearch** — hosted index, modal UI, very fast. Free for open-source documentation projects after
  application/approval. Material has built-in DocSearch wiring. Reasonable next step if launch traffic is heavy and
  the default search starts to feel slow. <https://docsearch.algolia.com/>

Recommendation: keep the built-in search through the launch; revisit once the docs/blog corpus crosses ~50 pages
or analytics show search drop-off.

## Alternative Site Generators

### Astro Starlight

Starlight is a strong alternative if SASE wants a richer custom homepage/product-site layer. It supports Markdown/MDX,
type-safe frontmatter, custom Astro pages in `src/pages`, Starlight layout reuse for custom pages, built-in docs UX,
search, i18n, SEO, dark mode, and UI components.

Sources:

- Starlight homepage: <https://starlight.astro.build/>
- Starlight pages/custom pages: <https://starlight.astro.build/guides/pages/>

Why it might win later:

- Best fit if SASE wants a highly designed landing page, animated architecture demos, rich visual case studies, or
  custom UI components while staying mostly static.
- Easier to build a product-marketing front door than in pure MkDocs.

Why not migrate now:

- The current site is already live.
- Docs content is already in MkDocs shape.
- The immediate gaps are information architecture and visual design, not framework capability.

### Docusaurus

Docusaurus is a mature docs/blog/project-site framework with React customization, docs sidebars, versioning, blog
features, and custom styling. Its styling docs emphasize global CSS for simple cases and React component customization
for more advanced DOM changes.

Sources:

- Docusaurus docs structure: <https://docusaurus.io/docs/docs-introduction>
- Docusaurus blog: <https://docusaurus.io/docs/blog>
- Docusaurus styling: <https://docusaurus.io/docs/styling-layout>

Why it might win later:

- Strong choice if SASE wants versioned docs, React components, MDX-heavy examples, or a more app-like developer portal.

Why not migrate now:

- It introduces a Node/React site stack into a Python project.
- The benefit is mostly future optionality, while current polish work can be done in MkDocs.

### Nextra

Nextra is a Next.js + MDX documentation/blog generator with optimized links/images, Pagefind search, static export
support, and the full Next.js rendering model.

Sources:

- Nextra homepage: <https://nextra.site/>
- Nextra docs theme: <https://nextra.site/docs/docs-theme/start>
- Nextra static exports: <https://nextra.site/docs/guide/static-exports>

Why it might win later:

- Strong if SASE wants Next.js, MDX, server/client components, or a more programmable front-end platform.

Why not migrate now:

- Too much framework surface for a Markdown-heavy open-source docs/blog launch.
- Static export and deployment details become more complex than MkDocs for little immediate gain.

### VitePress

VitePress is a Vite + Vue static site generator from the Vue.js team. It powers Vite, Vue, Pinia, Vitest, Rollup, and
many other tools' docs. Markdown-first, with optional Vue components in `.md` and a "default theme" tuned for docs.

Sources:

- VitePress site: <https://vitepress.dev/>
- VitePress default theme: <https://vitepress.dev/reference/default-theme-home-page>

Why it might win later:

- Excellent default look out of the box — closer to "product site" than MkDocs Material defaults without writing
  custom CSS.
- Trivial to drop a custom Vue homepage component while keeping docs Markdown.
- Strong build performance and developer experience.

Why not migrate now:

- Vue/Node toolchain in a Python project. SASE plugins live in separate repos, but the main repo is Python-first.
- The 2.x line is alpha at the time of writing; 1.x is stable and widely used.

### Hugo

Hugo is a Go-based static site generator with a very large theme ecosystem (Doks, Hextra, Lotus Docs, geekdoc,
hugo-book). Build times are extremely fast and it has no Node/Python dependency at runtime.

Sources:

- Hugo: <https://gohugo.io/>
- Hextra theme (docs/blog hybrid): <https://imfing.github.io/hextra/>

Why it might win later:

- Very fast builds, cleanest deployment story (single binary).
- Good fit if SASE wants total control over templates without learning a frontend framework.

Why not migrate now:

- Go templating is its own learning curve.
- Less natural fit for the kinds of Material-quality docs UX (admonitions, content tabs, code annotations) that
  the blog series will lean on.

## Recommended Structure

### Public URL Shape

```text
https://sase.sh/                                  public homepage
https://sase.sh/blog/                             canonical blog index
https://sase.sh/blog/<slug>/                      evergreen posts
https://sase.sh/series/agentic-software-engineering/
https://sase.sh/docs/ or existing top-level docs  optional future docs grouping
```

Important decision: whether to keep docs at top-level URLs or move them under `/docs/`.

Recommendation for now: keep existing top-level docs URLs. They are already published, and a migration to `/docs/`
creates redirect work. Instead, make the navigation clearer and consider `/docs/` only if a larger IA redesign happens.

### Homepage Content Model

The homepage should answer four questions above the fold:

1. What is SASE?
2. Who is it for?
3. What problem does it solve that a single coding-agent CLI does not?
4. What should I click next?

Suggested first-screen hierarchy:

- H1: "Structured Agentic Software Engineering"
- Subhead: "A workflow layer for planning, supervising, resuming, and reviewing coding-agent work."
- Primary action: "Read the launch essay" or "Start with ACE"
- Secondary action: "View on GitHub"
- Visual: real ACE/TUI screenshot, architecture map, or generated concept image that shows agents/workspaces/plans,
  not an abstract gradient.

Below the fold:

- "The coordination layer" with 3-4 short blocks:
  - Durable work units: ChangeSpecs and Beads.
  - Reusable prompt logic: XPrompts and workflows.
  - Supervision: ACE and AXE.
  - Portability: provider plugins and workspace/VCS abstraction.
- "Start by role":
  - I use coding agents.
  - I build agent workflows.
  - I maintain the SASE repo.
  - I want the blog series.
- Latest blog post or launch-series progress.
- Footer with GitHub, Blog, Docs, RSS, and canonical social links.

### Visual Direction

SASE should look like a serious engineering tool, not a SaaS marketing template.

Use:

- Clean technical typography.
- Light and dark modes tuned deliberately.
- Neutral base with a few accent colors mapped to concepts:
  - planning/state
  - agents/runs
  - review/VCS
  - automation/hooks
- Real product surfaces where possible: ACE screenshots, architecture maps, command snippets, artifact panels.
- The existing infographic family as supporting material, but do not let generated infographics become the whole brand.

Avoid:

- Decorative gradients as the main identity.
- Abstract AI imagery.
- Overly rounded card-heavy hero pages.
- Marketing copy that says "AI-powered" without explaining the workflow primitive.
- A homepage that requires readers to understand SASE terminology before they know why it matters.

### Design System Pieces To Add

Low-effort, high-leverage pieces:

- `docs/stylesheets/extra.css`
- `docs/images/sase-og.png` or similar default OpenGraph image.
- A simple logo mark or wordmark treatment.
- Homepage card grid.
- Explicit footer metadata.
- RSS plugin if not already added.
- `nav:` tree in `mkdocs.yml`.
- `extra.social` links in `mkdocs.yml`.

Medium-effort pieces:

- `overrides/main.html` or `overrides/home.html` for a custom homepage template.
- Homepage-specific CSS classes.
- Per-section index pages with card grids.
- Author metadata for blog posts.
- Social cards plugin or manual OpenGraph image metadata.

Higher-effort pieces:

- Interactive architecture diagram.
- Embedded terminal/TUI demo recordings.
- Docs search tuning and analytics.
- Versioned docs.
- Full migration to Astro/Docusaurus/Nextra.

## Visual Inspiration And Peer Positioning

### Reference MkDocs Material sites

The fastest way to disprove the "MkDocs always looks like default docs" assumption is to look at projects that took
it further:

- **Material for MkDocs** itself — the most polished example of what the theme can do without forking, including a
  homepage that is clearly a product site. <https://squidfunk.github.io/mkdocs-material/>
- **FastAPI** — heavy use of admonitions, content tabs, an opinionated homepage hero, and visual consistency between
  docs and blog. <https://fastapi.tiangolo.com/>
- **Pydantic** — restrained typography, dense reference material, strong dark-mode tuning.
  <https://docs.pydantic.dev/latest/>
- **Typer** — Tiangolo's CLI library; relevant because SASE is also a CLI/TUI project. Shows how rich text-based
  interface examples can sit beside reference docs. <https://typer.tiangolo.com/>
- **HTTPX** — clean, minimal, code-forward. <https://www.python-httpx.org/>
- **Datasette** — long-form developer documentation with a strong personal-blog-meets-tool feel; close in spirit
  to what SASE could be. <https://docs.datasette.io/>
- **Mermaid** — uses Material with extensive diagram embedding. <https://mermaid.js.org/>

These are all "MkDocs Material with custom CSS and a thoughtfully written homepage." None of them are framework
migrations.

### Peer/competitor positioning

What other agentic coding-CLI projects use for their public surface, as of mid-2026:

- **Aider** (`aider.chat`) — terminal-pair-programming CLI. Hero is a video/GIF of the terminal in action, plus
  prominent star/install/token-volume metrics for social proof, then "Get Started" + "Documentation" CTAs. Reads as
  a tool first, docs second. SASE should consider similar metric-driven trust signals once they exist.
- **OpenHands** (formerly OpenDevin) — agent framework with a stronger product-marketing front door than most OSS
  agent projects. Useful as a "what to look like if you want to be taken seriously by the AI-research crowd"
  reference.
- **Continue.dev** — IDE-extension positioning, strong design system, MDX-based site. Good reference for "how
  serious do open-source dev tools look in 2026."
- **Sweep**, **smol-ai/developer**, **Devika**, **Cursor**, **Warp**, **Zed** — all have a clear hero
  message, a real screenshot or demo, a short "what it actually does" block, and a path to docs/install. SASE's
  current homepage skips most of those steps.

The pattern across all of them: the homepage is a deliberate product page, the docs are linked but separate, and
the design is restrained enough to look like an engineering tool. SASE is well-placed to land in that aesthetic
because the existing infographic family already leans engineering rather than marketing.

### What to copy, what to avoid

Copy:

- A hero with a real artifact (TUI screenshot, terminal recording, or one canonical architecture diagram) above
  the fold.
- A short "in 30 seconds, here is what it actually does" paragraph below the hero.
- Three to five concept blocks, each with a one-line definition and a link to a deeper page.
- Visible install/start CTA. The blog series is the secondary CTA, not the primary one.
- A consistent footer with GitHub, Blog, RSS, Discussions, and license.

Avoid:

- Fake metrics. Don't show "10,000+ developers" until that is true.
- Stock AI imagery (glowing brain, neural-net mesh, hands-typing-on-keyboard).
- Marketing-y verbs ("supercharge", "revolutionize"). The audience is hostile to those.
- Hiding the actual product behind a "request a demo" or "join the waitlist" pattern. SASE is open source; the
  homepage should respect that.

## Performance And Accessibility Targets

Concrete targets for the redesign so "beautiful" doesn't translate into "heavy":

- Lighthouse mobile scores: Performance ≥ 90, Accessibility ≥ 95, Best Practices ≥ 95, SEO ≥ 95. Material defaults
  hit most of this; Mermaid and any custom JS push Performance down if not lazy-loaded.
- Cumulative Layout Shift < 0.1: pre-size all images (`width`/`height` on `<img>` tags or Markdown `attr_list`).
- Largest Contentful Paint < 2.5s on 4G mobile: inline above-the-fold CSS via Material's defaults; defer Mermaid
  and analytics JS.
- Total page weight target: hero/index pages < 250 KB, content pages < 150 KB excluding deliberately heavy assets.
- WCAG 2.2 AA color contrast for both palettes. Material's default Indigo/Slate sometimes drifts below 4.5:1 on
  body text in dark mode; verify with the browser's contrast checker after CSS changes.
- Respect `prefers-reduced-motion` in any custom transitions/animations.
- All non-decorative images need real `alt` text (the existing `images/sase_overview.jpg` reference has none).
- Navigation should be operable via keyboard alone — Material handles this by default, but theme overrides have
  historically broken focus rings; verify after any `overrides/` changes.

## CI Checks For The Docs Site

The build is already `strict: true`, which catches broken internal links and unknown nav entries. Worth adding:

- **Link check** with [`lychee`](https://github.com/lycheeverse/lychee) on built HTML or source Markdown. Catches
  external rot — particularly important for a docs/blog site that links to a moving research literature.
- **`mkdocs-htmlproofer-plugin`** — an alternative that runs as part of `mkdocs build`. Slower but in-process.
  <https://github.com/manuzhang/mkdocs-htmlproofer-plugin>
- **Lighthouse CI** on the Cloudflare Pages preview URL for every PR that touches `docs/`, `mkdocs.yml`, or
  `overrides/`. Block merges that drop key metrics by more than a small threshold.
  <https://github.com/GoogleChrome/lighthouse-ci>
- **`pa11y-ci`** or **axe-core** for accessibility regressions on the same preview URL. Even an allow-list of
  the 3-5 most-trafficked pages is enough.
- **Markdown linting** — `markdownlint` or `mdformat --check` on `docs/`. The repo already runs `ruff` and `mypy`
  on Python; a parallel docs lint is reasonable once the docs corpus expands.
- **Mermaid render check** — `mermaid-cli` (`mmdc`) can validate diagram source ahead of build, catching
  syntax errors that would otherwise render as a Mermaid "syntax error" panel in production.

These should be opt-in CI jobs scoped to docs paths, not added to the main `just check` flow, so day-to-day Python
work isn't slowed down.

## Implementation Stages

### Stage 1: Make the live site feel intentional

Goal: polish without framework risk.

Changes:

- Rewrite `docs/index.md` into a real homepage using Markdown plus card grids.
- Add `docs/stylesheets/extra.css` and `extra_css`.
- Add explicit `nav:` grouping informed by Diátaxis (tutorials / how-to / reference / explanation).
- Add `extra.social`, copyright/footer text, and `theme.features: [content.action.edit, content.action.view]`
  with a matching `edit_uri`.
- Enable `navigation.tabs`, `navigation.instant`, `navigation.tracking`, `toc.follow`, `content.code.copy`,
  `content.code.annotate`, `content.tabs.link` in `theme.features`.
- Configure a deliberate `palette` (light + dark with toggles, `prefers-color-scheme` media queries).
- Wire Mermaid via `pymdownx.superfences.custom_fences` and convert one or two infographics to inline diagrams.
- Add `mkdocs-rss-plugin` if the launch series is imminent.
- Add a `/series/agentic-software-engineering/` page.
- Wire Cloudflare Web Analytics.
- Add `robots.txt` and a default OpenGraph image at `docs/images/sase-og.png`.

This is likely enough for the first public blog post.

### Stage 2: Give the blog series a launch-quality package

Goal: make posts shareable and coherent.

Changes:

- Replace the launch stub with the full Part 1.
- Add `.authors.yml` with author profiles and per-post `description`/`image` front matter.
- Add `categories_allowed` and a small tag taxonomy via the Material `tags` plugin.
- Add series navigation links in every post.
- Add the Material `social` plugin (or hand-designed per-post OG images) and verify previews on LinkedIn/Twitter
  Cards/Discord/DEV.
- Add a "latest / next / complete series" module on the homepage.
- Enable Giscus comments on `/blog/**` only (not on docs).
- Cross-post with canonical links as already recommended in the platform research.

### Stage 3: Decide if MkDocs has become the constraint

Stay on MkDocs if:

- Most pages are docs, guides, and blog posts.
- Customization remains CSS/template-light.
- The content model is Markdown-first.

Consider Astro Starlight if:

- SASE needs a custom product homepage plus docs in one coherent static framework.
- You want Astro components while keeping Markdown/MDX content.

Consider Docusaurus if:

- Versioned docs, React components, or MDX-heavy examples become central.

Consider Nextra if:

- The site becomes a Next.js/MDX developer portal with richer programmable page behavior.

## Concrete Next Design Brief

If the next task is implementation, a good target prompt would be:

> Redesign `sase.sh` within the existing MkDocs Material stack. Keep published docs URLs stable. Add a polished
> homepage, explicit navigation grouping, a launch-series page, custom CSS, social/RSS basics, and verify with
> `mkdocs build --strict`. Use the existing SASE docs, blog research, and infographic assets for content and visual
> direction.

Acceptance criteria:

- The homepage explains SASE before using internal acronyms heavily.
- Navigation has 5-7 readable top-level groups, not a flat list.
- `/blog/` remains canonical for posts.
- A launch-series page exists and is linked from the homepage and blog.
- The design works in light and dark mode.
- The site builds strictly and deploys through the current Cloudflare Pages path.

## Source Links

Live and project:

- Live SASE site: <https://sase.sh/>

Material for MkDocs:

- Customization: <https://squidfunk.github.io/mkdocs-material/customization/>
- Grids/cards: <https://squidfunk.github.io/mkdocs-material/reference/grids/>
- Navigation: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-navigation/>
- Built-in blog plugin: <https://squidfunk.github.io/mkdocs-material/plugins/blog/>
- Blog setup / RSS: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-a-blog/>
- Social cards: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-social-cards/>
- Diagrams (Mermaid): <https://squidfunk.github.io/mkdocs-material/reference/diagrams/>
- Content tabs: <https://squidfunk.github.io/mkdocs-material/reference/content-tabs/>
- Code blocks: <https://squidfunk.github.io/mkdocs-material/reference/code-blocks/>
- Tags plugin: <https://squidfunk.github.io/mkdocs-material/plugins/tags/>
- Optimize plugin: <https://squidfunk.github.io/mkdocs-material/plugins/optimize/>
- Comments / Giscus: <https://squidfunk.github.io/mkdocs-material/setup/adding-a-comment-system/>
- Site analytics: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-site-analytics/>

PyMdown / MkDocs ecosystem:

- PyMdown Extensions: <https://facelessuser.github.io/pymdown-extensions/>
- mkdocs-rss-plugin: <https://guts.github.io/mkdocs-rss-plugin/>
- mkdocs-glightbox: <https://blueswen.github.io/mkdocs-glightbox/>
- mkdocs-redirects: <https://github.com/mkdocs/mkdocs-redirects>
- mkdocs-awesome-nav: <https://github.com/lukasgeiter/mkdocs-awesome-nav>
- mkdocs-git-revision-date-localized: <https://timvink.github.io/mkdocs-git-revision-date-localized-plugin/>
- mkdocs-minify-plugin: <https://github.com/byrnereese/mkdocs-minify-plugin>
- mkdocs-htmlproofer-plugin: <https://github.com/manuzhang/mkdocs-htmlproofer-plugin>

Information architecture:

- Diátaxis: <https://diataxis.fr/>

Diagrams and recordings:

- Mermaid: <https://mermaid.js.org/>
- D2: <https://d2lang.com/>
- Excalidraw: <https://excalidraw.com/>
- asciinema: <https://asciinema.org/>
- VHS by Charm: <https://github.com/charmbracelet/vhs>

Cloudflare Pages:

- Web Analytics: <https://developers.cloudflare.com/web-analytics/>
- Pages Functions: <https://developers.cloudflare.com/pages/functions/>

Search:

- Pagefind: <https://pagefind.app/>
- Algolia DocSearch: <https://docsearch.algolia.com/>

Alternative generators:

- Astro Starlight: <https://starlight.astro.build/>
- Starlight pages / custom pages: <https://starlight.astro.build/guides/pages/>
- Docusaurus docs: <https://docusaurus.io/docs/docs-introduction>
- Docusaurus blog: <https://docusaurus.io/docs/blog>
- Docusaurus styling: <https://docusaurus.io/docs/styling-layout>
- Nextra: <https://nextra.site/>
- Nextra docs theme: <https://nextra.site/docs/docs-theme/start>
- Nextra static exports: <https://nextra.site/docs/guide/static-exports>
- VitePress: <https://vitepress.dev/>
- VitePress default home: <https://vitepress.dev/reference/default-theme-home-page>
- Hugo: <https://gohugo.io/>
- Hextra (Hugo theme): <https://imfing.github.io/hextra/>

CI checks:

- lychee link checker: <https://github.com/lycheeverse/lychee>
- Lighthouse CI: <https://github.com/GoogleChrome/lighthouse-ci>

Reference Material sites:

- FastAPI: <https://fastapi.tiangolo.com/>
- Pydantic: <https://docs.pydantic.dev/latest/>
- Typer: <https://typer.tiangolo.com/>
- HTTPX: <https://www.python-httpx.org/>
- Datasette: <https://docs.datasette.io/>
- Material for MkDocs (self): <https://squidfunk.github.io/mkdocs-material/>

Peer/competitor sites:

- Aider: <https://aider.chat/>
- OpenHands: <https://docs.all-hands.dev/>
- Continue: <https://continue.dev/>

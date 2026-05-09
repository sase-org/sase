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

## Implementation Stages

### Stage 1: Make the live site feel intentional

Goal: polish without framework risk.

Changes:

- Rewrite `docs/index.md` into a real homepage using Markdown plus card grids.
- Add `docs/stylesheets/extra.css` and `extra_css`.
- Add explicit `nav:` grouping.
- Add `extra.social`, copyright/footer text, and a repo edit/view link config if desired.
- Add RSS dependency/config if the launch series is imminent.
- Add a `/series/agentic-software-engineering/` page.

This is likely enough for the first public blog post.

### Stage 2: Give the blog series a launch-quality package

Goal: make posts shareable and coherent.

Changes:

- Replace the launch stub with the full Part 1.
- Add series navigation links in every post.
- Add a default social card and per-post preview metadata.
- Add a "latest / next / complete series" module on the homepage.
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

- Live SASE site: <https://sase.sh/>
- Material for MkDocs customization: <https://squidfunk.github.io/mkdocs-material/customization/>
- Material grids/cards: <https://squidfunk.github.io/mkdocs-material/reference/grids/>
- Material navigation: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-navigation/>
- Material built-in blog plugin: <https://squidfunk.github.io/mkdocs-material/plugins/blog/>
- Material blog setup/RSS: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-a-blog/>
- Material social cards: <https://squidfunk.github.io/mkdocs-material/setup/setting-up-social-cards/>
- Astro Starlight: <https://starlight.astro.build/>
- Starlight pages/custom pages: <https://starlight.astro.build/guides/pages/>
- Docusaurus docs: <https://docusaurus.io/docs/docs-introduction>
- Docusaurus blog: <https://docusaurus.io/docs/blog>
- Docusaurus styling: <https://docusaurus.io/docs/styling-layout>
- Nextra: <https://nextra.site/>
- Nextra docs theme: <https://nextra.site/docs/docs-theme/start>
- Nextra static exports: <https://nextra.site/docs/guide/static-exports>

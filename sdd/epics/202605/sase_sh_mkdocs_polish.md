---
create_time: 2026-05-09 02:56:07
status: wip
prompt: sdd/prompts/202605/sase_sh_mkdocs_polish.md
bead_id: sase-2g
tier: epic
---
# SASE.sh MkDocs Polish Plan

## Goal

Implement the highest-value recommendations from `sdd/research/202605/sase_sh_site_design_research.md` while staying on
MkDocs Material. The result should make `https://sase.sh/` feel like an intentional public project site instead of a
default documentation index, without moving published docs URLs.

This plan intentionally splits the work into phases that can be handed to distinct agent instances. Each phase should
produce a coherent, reviewable patch and leave the repo in a buildable state.

## Current State

- `mkdocs.yml` already uses MkDocs Material, strict builds, `site_url: https://sase.sh/`, directory URLs, search, and
  the Material blog plugin with evergreen post URLs.
- `docs/index.md` is a compact docs index, not a designed public homepage.
- There is no explicit `nav:` tree, so the site presents a flat docs list.
- There is no source-level `docs/stylesheets/` or MkDocs `overrides/` customization yet.
- `docs/blog/posts/why-coding-agents-need-orchestration.md` is a launch stub.
- `docs/_headers` and `docs/_redirects` are already copied into the Cloudflare Pages artifact.
- `requirements-docs.txt` and the `docs` pyproject extra currently include only `mkdocs-material`.
- `Justfile` has `just docs-check`, which installs the docs extra and runs `mkdocs build --strict`.
- Live checks on 2026-05-09 showed `https://sase.sh/` and `https://sase.sh/blog/` serving through Cloudflare, canonical
  tags present, and `sitemap.xml` generated. `https://www.sase.sh/blog/` did not resolve, so `www` redirect/DNS should
  be treated as a deployment follow-up rather than assumed working.

## Constraints

- Stay on MkDocs Material for this pass.
- Keep existing top-level docs URLs stable; do not move everything under `/docs/`.
- Keep implementation Markdown/CSS/template-light. Avoid introducing a JS frontend framework.
- Prefer real SASE product surfaces and existing diagrams over generic AI imagery.
- Run `just install` before repo checks in this workspace, then run `just docs-check` and `just check` before final
  handoff for any phase that changes files.
- Verify Cloudflare compatibility with the same artifact shape Pages expects: build command produces `site/`, and
  `_headers`/`_redirects` are present in the built output.

## Phase 1: Site Foundation And Deployment Guardrails

### Owner

One agent instance focused on configuration and deploy reliability.

### Scope

- Update docs dependencies so local, CI, and Cloudflare Pages can build the same site:
  - Add `mkdocs-rss-plugin` to the `docs` pyproject extra and `requirements-docs.txt` if RSS is enabled.
  - Avoid enabling Material social cards in this phase unless all image-processing dependencies are pinned and the
    Cloudflare build path is proven. A manual/default OpenGraph image can come later.
- Add an explicit `nav:` tree in `mkdocs.yml` with 5-7 reader-oriented groups while preserving current URL targets:
  - Home
  - Blog
  - Start
  - Concepts
  - Operations
  - Integrations
  - Reference
- Add basic MkDocs Material site metadata:
  - `theme.palette` for deliberate light/dark modes.
  - `theme.icon` and `extra.social` for GitHub.
  - `copyright`.
  - `extra_css` pointing at the future stylesheet path.
- Add `docs/robots.txt` with the production sitemap URL.
- Add or update CI so docs builds are validated outside the Cloudflare Pages dashboard. Prefer a narrow GitHub Actions
  job or a `just docs-check` invocation in an existing job if it does not make the already-large CI suite slower in a
  surprising way.
- If the repo wants Cloudflare Pages to pin Python 3.12, add a small `.python-version` only if that matches existing
  project policy. Otherwise document that Pages should set `PYTHON_VERSION=3.12` in project settings.

### Acceptance Criteria

- `mkdocs.yml` remains strict and keeps `site_url: https://sase.sh/`.
- Existing docs pages keep their current URL paths.
- RSS is either enabled and build-verified or explicitly deferred with a comment/reason in the plan handoff.
- `site/_headers`, `site/_redirects`, and `site/robots.txt` exist after `just docs-check`.
- Verification commands pass:
  - `just install`
  - `just docs-check`
  - `just check`

## Phase 2: Public Homepage And Visual System

### Owner

One agent instance focused on front-door content and CSS.

### Scope

- Rewrite `docs/index.md` into a public homepage that answers, above the fold:
  - What is SASE?
  - Who is it for?
  - What problem does it solve beyond a single coding-agent CLI?
  - What should the reader click next?
- Use Markdown plus Material-supported `attr_list`/`md_in_html` card grids before reaching for template overrides.
- Add `docs/stylesheets/extra.css` with a restrained technical visual system:
  - Homepage hero layout with responsive constraints.
  - Card grids for role-based starts and core primitives.
  - Tuned light/dark colors that do not read as a one-note purple/blue gradient theme.
  - Better image treatment for existing diagrams/screenshots.
  - Mobile-safe typography and spacing.
- Use existing assets first:
  - `docs/images/sase_overview.jpg`
  - `docs/images/sase-component-communication.png`
  - `docs/images/sase_tui_tabs_infographic.png`
  - relevant workflow/core infographics where they clarify the message.
- Add clear CTAs:
  - Read the launch essay
  - Start with ACE
  - View on GitHub
  - Explore the series
- Do not replace the homepage with marketing fluff. Keep the copy specific to SASE primitives: ChangeSpecs, Beads,
  XPrompts, ACE, AXE, provider/workspace abstractions.

### Acceptance Criteria

- Homepage reads as a public project front door, not a generated docs table of contents.
- The first viewport includes the project name, a concrete value proposition, and at least two useful actions.
- Layout is responsive without overlapping text or unstable cards.
- Light and dark modes are both deliberately styled.
- Verification commands pass:
  - `just docs-check`
  - `just check`

## Phase 3: Blog Series Package And Reader Paths

### Owner

One agent instance focused on content structure, blog/series navigation, and SEO basics.

### Scope

- Add `docs/series/agentic-software-engineering.md` as the launch-series hub.
- Link the series hub from:
  - Homepage
  - Blog index
  - Launch post stub
  - `mkdocs.yml` navigation
- Improve `docs/blog/index.md` so it frames the blog as the canonical SASE publishing surface and points to the series.
- Improve the launch stub enough that it is honest and useful while still clearly marked as a stub, unless the full
  article is available in the repo or prompt context.
- Add RSS plugin configuration if Phase 1 added the dependency and did not enable it.
- Add frontmatter/metadata consistency for blog posts:
  - Date
  - Slug
  - Categories
  - Optional description/excerpt if supported cleanly by Material.
- Add previous/next/series links in the launch stub so future posts have a pattern to copy.

### Acceptance Criteria

- `/series/agentic-software-engineering/` builds and is reachable from homepage/blog/nav.
- `/blog/` remains canonical for posts.
- Blog and series copy direct readers toward repo, docs, and install/start paths.
- RSS either works in the built site or is explicitly deferred with a reason.
- Verification commands pass:
  - `just docs-check`
  - `just check`

## Phase 4: Cloudflare Deployment Verification And Polish Pass

### Owner

One agent instance focused on release-readiness, built artifact inspection, and production checks.

### Scope

- Run the full local verification path from a clean-enough workspace:
  - `just install`
  - `just docs-check`
  - `just check`
- Inspect the built `site/` artifact:
  - `site/index.html` contains canonical `https://sase.sh/`.
  - `site/blog/index.html` exists.
  - `site/series/agentic-software-engineering/index.html` exists.
  - `site/sitemap.xml` includes homepage, blog, and series URLs.
  - `site/robots.txt` points to `https://sase.sh/sitemap.xml`.
  - `site/_headers` and `site/_redirects` exist.
- Confirm Cloudflare Pages build compatibility:
  - Build command remains compatible with Pages: `python -m pip install -e ".[docs]" && python -m mkdocs build --strict`
  - Build output directory remains `site`.
  - No required build step assumes `uv` is preinstalled on Cloudflare Pages.
- If Cloudflare credentials are available in the agent environment, deploy a preview or production build with the
  existing project workflow and record the URL. If credentials are not available, do not fabricate a deploy; instead,
  verify the live production site after the branch is merged/deployed.
- Production/live checks after deploy:
  - `curl -I https://sase.sh/`
  - `curl -I https://sase.sh/blog/`
  - `curl -I https://sase.sh/series/agentic-software-engineering/`
  - `curl -s https://sase.sh/ | rg 'canonical|og:|twitter:'`
  - `curl -s https://sase.sh/sitemap.xml | rg 'series/agentic-software-engineering|blog'`
  - `curl -I https://www.sase.sh/blog/`
- If `www.sase.sh` still fails DNS resolution, document it as an external Cloudflare DNS/Bulk Redirect task, because the
  repo cannot fix an absent DNS record alone.

### Acceptance Criteria

- Local strict MkDocs build passes.
- Full repo check passes.
- Built artifact contains all Cloudflare Pages control files and expected generated pages.
- Live production checks pass after deployment, except for any explicitly documented environment-level blocker such as
  missing Cloudflare credentials or missing `www` DNS.
- Final handoff states exactly what was verified locally, what was verified against Cloudflare, and what remains outside
  repo control.

## Recommended Execution Order

Run phases sequentially. Phase 1 should land before Phase 2 because it establishes the nav, metadata, dependency, and CI
groundwork that the design/content phases depend on. Phase 2 and Phase 3 can be done by separate agents after Phase 1,
but Phase 3 should rebase on the homepage links before finalizing. Phase 4 should run last and should not add new
features unless it finds a deployment blocker.

## Cross-Phase Coordination Rules

- Agents should read this plan, `sdd/research/202605/sase_sh_site_design_research.md`, `mkdocs.yml`, `docs/index.md`,
  `docs/blog/index.md`, and the launch post before editing.
- Agents should not move existing docs pages or rename existing docs files unless a redirect is added and
  build-verified.
- Agents should keep CSS scoped and documented by class names rather than overriding broad Material internals whenever
  possible.
- Agents should prefer small, deterministic generated artifacts. Do not commit large videos or files over Cloudflare
  Pages's 25 MiB asset limit.
- Agents should preserve unrelated worktree changes. If an agent sees changes it did not make, it should inspect enough
  to avoid overwriting them and continue only on its phase-owned files.

## Phase Ownership Summary

- Phase 1 owns `mkdocs.yml`, docs dependency files, `docs/robots.txt`, and optional docs CI wiring.
- Phase 2 owns `docs/index.md`, `docs/stylesheets/extra.css`, and any small homepage-specific image references.
- Phase 3 owns `docs/blog/index.md`, `docs/blog/posts/why-coding-agents-need-orchestration.md`, `docs/series/`, and
  series/blog nav additions.
- Phase 4 owns verification, deployment notes, and only minimal fixes required to make the deployed site match the built
  artifact.

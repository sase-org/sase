---
create_time: 2026-06-06 16:24:02
status: done
prompt: sdd/prompts/202606/hide_unpublished_blog_posts.md
---
# Hide Unpublished Blog Posts From the Public Site

## Goal

Publish only the first SASE blog-series post, `[00] Why Coding Agents Need Orchestration`, while keeping the remaining
nine posts in the repository as unpublished drafts for later rollout. The public website, RSS feed, search index, blog
home, navigation, and series hub should not expose `[01]` through `[09]`.

## Current State

- The MkDocs Material blog plugin owns `docs/blog/posts/*.md`.
- `mkdocs.yml` currently lists all ten posts in the Blog navigation.
- `docs/blog/index.md` and `docs/series/agentic-software-engineering.md` explicitly link all ten posts.
- The nine unpublished posts have normal `date` metadata in May 2026. As of 2026-06-06, future-date filtering would not
  hide them.
- The local installed `mkdocs-material` blog plugin supports per-post `draft: true`. During `mkdocs build`, draft posts
  are excluded from generated blog pages. During `mkdocs serve`, drafts are included by default via `draft_on_serve`,
  which is useful for local preview but does not affect the deployed website.
- The docs deploy workflow builds a prebuilt `site/` artifact with `just docs-check`, `just docs-pdf-check`, and
  `just docs-deploy-artifact-check`, then deploys that artifact through Wrangler.

## Proposed Approach

Use explicit blog-post draft metadata as the canonical unpublished marker, then remove all public links to those draft
posts.

This is preferable to deleting or moving the files because it preserves source history, stable slugs, future publishing
order, and local preview behavior. It is preferable to relying on future dates because the current dates are already in
the past and the eventual release schedule is not yet known.

## Implementation Plan

1. Mark the unpublished posts as drafts.
   - Add `draft: true` to frontmatter for:
     - `docs/blog/posts/hello-sase-your-first-15-minutes.md`
     - `docs/blog/posts/xprompts-in-depth.md`
     - `docs/blog/posts/axe-background-daemon.md`
     - `docs/blog/posts/beads-and-sdd.md`
     - `docs/blog/posts/commit-workflows-plugins.md`
     - `docs/blog/posts/changespecs-in-practice.md`
     - `docs/blog/posts/telegram-mobile-agents.md`
     - `docs/blog/posts/prompt-widget-and-nvim.md`
     - `docs/blog/posts/whats-next-memory-mobile-web.md`
   - Leave `[00]` without `draft: true`.
   - Keep all slugs, titles, dates, and post bodies intact unless a public link cleanup requires a small wording change.

2. Remove unpublished posts from the public navigation.
   - In `mkdocs.yml`, keep `Blog Home`, `SASE Blog Series`, and `[00] Why Coding Agents Need Orchestration`.
   - Remove the `[01]` through `[09]` nav entries.
   - Leave the blog plugin's global `draft` setting at its production default, so `mkdocs build` excludes drafts.

3. Rewrite public blog landing copy.
   - Update `docs/blog/index.md` so "Start Here" presents only `[00]`.
   - Replace the ten-post public list with short launch copy that says more series posts are forthcoming.
   - Do not include Markdown links to `[01]` through `[09]`, because strict mode should not need to resolve hidden draft
     pages from public pages.

4. Rewrite the public series hub.
   - Update `docs/series/agentic-software-engineering.md` to describe the series as beginning with `[00]` and continuing
     later.
   - Keep only `[00]` as a published linked table/list entry.
   - Optionally list the remaining topics as unlinked "forthcoming" titles if useful for reader expectations, but avoid
     links to draft post pages.
   - Adjust publishing notes to explain that stable slugs are retained for unpublished drafts but only published entries
     are linked from the public site.

5. Remove public next-links into the unpublished run.
   - Update `[00]`'s closing "Next" link to avoid linking to `[01]` while it is draft.
   - Use a neutral fallback such as the blog home, series hub, or current product docs.
   - Do not spend time rewriting navigation inside `[01]` through `[09]`; draft posts are excluded from the public
     build, and keeping their internal series links helps later release work.

6. Strengthen deploy checks for the publishing boundary.
   - Update `just docs-deploy-artifact-check` so CI verifies:
     - `site/blog/posts/why-coding-agents-need-orchestration/index.html` exists.
     - None of the nine draft post output directories exist.
     - Generated `site/` files do not contain public hrefs for the nine draft slugs.
     - RSS/search outputs do not contain the nine draft slugs.
   - Keep the existing checks for blog home, series hub, `_headers`, and PDF artifact.

7. Validate with the docs pipeline.
   - Run `just docs-check`.
   - Run `just docs-pdf-check` if the changes affect nav/PDF-visible docs, which they do through the series hub and blog
     nav.
   - Run `just docs-deploy-artifact-check`.
   - Run targeted generated-site checks:
     - Exactly one generated blog-post page exists under `site/blog/posts`.
     - No generated HTML, RSS, search JSON, or sitemap contains the nine draft slugs.
     - The public blog landing page and series hub contain no links to draft post URLs.
   - Because this workspace already has dependencies installed from the prior work, `just install` is likely unnecessary
     unless a command reports environment drift.

## Acceptance Criteria

- The public build contains only one blog-post page: `/blog/posts/why-coding-agents-need-orchestration/`.
- `/blog/posts/hello-sase-your-first-15-minutes/` through `/blog/posts/whats-next-memory-mobile-web/` are not generated.
- The public nav, blog home, series hub, RSS feed, search index, and sitemap do not expose draft post URLs.
- The nine unpublished post source files remain in `docs/blog/posts/` with stable slugs and `draft: true`.
- `just docs-check`, `just docs-pdf-check`, and `just docs-deploy-artifact-check` pass, or any unrelated failure is
  clearly documented.

---
create_time: 2026-05-11 19:13:07
status: done
prompt: sdd/prompts/202605/number_blog_posts.md
---
# Number Each Blog Post Across sase.sh

## Goal

Make every surface that lists or links to a SASE blog post show a stable, visible "Post N:" number prefix. The blog has
a fixed-and-small post count (two today, expected to stay small), so numbering reinforces reading order and makes the
short list feel deliberate rather than auto-generated.

## Background — Where Titles Come From Today

The site is built with **MkDocs + Material**. Blog post titles propagate from a few places:

| Surface                                                   | Source of title                                  | Numbered today?          |
| --------------------------------------------------------- | ------------------------------------------------ | ------------------------ |
| Top-level Blog nav dropdown                               | `nav:` in `mkdocs.yml` (literal label)           | ✅ "Post 1:" / "Post 2:" |
| `docs/blog/index.md` prose list                           | Hand-written markdown                            | ✅ "Post 1." / "Post 2." |
| `docs/series/agentic-software-engineering.md` table       | Hand-written markdown w/ separate "Order" column | ✅ "1" / "2" in column   |
| Per-post **H1** heading on the post page                  | First `# ...` in the post's markdown             | ❌                       |
| Auto-generated blog landing list (Material `blog` plugin) | Post H1                                          | ❌                       |
| Blog post drawer/sidebar entry when viewing a post        | Post H1                                          | ❌                       |
| Browser tab title for the post page                       | Post H1                                          | ❌                       |
| RSS `<title>`                                             | Post H1                                          | ❌                       |

So numbering exists where we hand-author labels, and is missing wherever the title is derived from the post's H1.

## Posts In Play

`docs/blog/posts/`:

1. `why-coding-agents-need-orchestration.md` — H1 today: `# Why Coding Agents Need Orchestration` (date 2026-05-08).
2. `hello-sase-your-first-15-minutes.md` — H1 today: `# Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents`
   (date 2026-05-10).

Series order = numeric order = these two, in this order.

## Proposed Change

### 1. Pick one canonical format: `Post N: Title`

The top-level nav already uses `Post 1: …` and `Post 2: …`, and the blog index prose uses `Post 1.` / `Post 2.`. Pick
`Post N: Title` (colon form) as the single canonical phrasing for every surface so the user reads the same string
everywhere.

### 2. Update each post's H1 to embed the number

This is the only change that makes auto-generated surfaces (drawer, blog index page, RSS, browser tab) pick up the
number — because they all derive from the H1. The H1 _is_ the title.

- `docs/blog/posts/why-coding-agents-need-orchestration.md`: `# Why Coding Agents Need Orchestration` →
  `# Post 1: Why Coding Agents Need Orchestration`
- `docs/blog/posts/hello-sase-your-first-15-minutes.md`:
  `# Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents` →
  `# Post 2: Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents` (Trim "Your First 15 Minutes Orchestrating
  Coding Agents" stays intact; the existing colon in "Hello, SASE:" is reflowed to an em-dash so we don't end up with
  two colons in the heading.)

**Why edit H1 directly instead of a frontmatter `title:` override.** Material's blog plugin reads the post title from
the H1 by default; a frontmatter `title:` is honored only when present, and even then can desync from the on-page
heading. Editing the H1 keeps a single source of truth and makes the heading match what readers see in nav, drawer, and
RSS — which is the entire point of the request.

### 3. Sync hand-authored surfaces to the same `Post N: Title` form

- `mkdocs.yml` nav: already in form `"Post 1: Why Coding Agents Need Orchestration"` and
  `"Post 2: Hello, SASE — Your First 15 Minutes"`. Bring Post 2's nav label up to the full post-2 title to match the new
  H1: `"Post 2: Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents"`. (Optional, but eliminates a small
  divergence; if length becomes an issue the existing short form is acceptable.)
- `docs/blog/index.md` prose list: change `**Post 1.**` / `**Post 2.**` markers to inline part of the link text instead,
  so the visible labels read `[Post 1: Why Coding Agents Need Orchestration](...)` and
  `[Post 2: Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents](...)`. Drop the now-redundant `**Post N.**`
  bold prefix.
- `docs/series/agentic-software-engineering.md` table: drop the standalone `Order` column and fold the number into the
  link text (`[Post 1: ...]` / `[Post 2: ...]`). Two columns are enough: post + status.
- In-post cross-links: existing references already use `Post 1: Why Coding Agents Need Orchestration` style in
  `hello-sase-your-first-15-minutes.md` body — leave them. The "Previous" / "Next" footer links in each post should be
  updated to the same form for consistency (`Next: Post 2: …`, `Previous: Post 1: …`).
- `docs/index.md` hero buttons: link text reads "Start in 15 minutes" / "Read the launch essay" — these are
  intentionally short CTAs, not post titles. Leave them.

### 4. No slug, no URL, no frontmatter date changes

- Filenames stay the same: `why-coding-agents-need-orchestration.md`, `hello-sase-your-first-15-minutes.md`.
- `slug:` in frontmatter stays the same → URLs stay the same → no redirects needed.
- `description:` (used by RSS) stays the same.
- No template overrides, no CSS.

## Out of Scope

- Adding new posts or renaming existing ones.
- Reordering posts (Post 1 / Post 2 is series order and stays).
- Adding numeric prefixes to URLs/slugs (would break inbound links and feed history).
- Override CSS to render the number in a separate visual style — plain text is enough.
- Touching `docs/index.md` button copy.

## Verification

1. `mkdocs build` (which `just check` exercises via the docs gate) — must complete clean with `strict: true`.
2. Inspect generated `site/blog/index.html` and a post page in the browser. Confirm:
   - Blog landing post list shows `Post 1: …` and `Post 2: …`.
   - On a post page, the drawer entries for both posts show the numbered form.
   - The post's own H1 shows `Post 1: …` (or 2).
   - Browser tab title for each post page includes the number.
3. Inspect generated RSS (`site/feed_rss_created.xml`) and confirm each `<item><title>` carries `Post 1: …` /
   `Post 2: …`. Acceptable behavior — existing subscribers (zero so far) see an updated title; URLs are unchanged.
4. `grep -R "Why Coding Agents Need Orchestration\|Hello, SASE"` across `docs/` for any straggling unnumbered link text
   that should match the new convention.
5. `just check` passes.

## Risk

Low. Files touched are all docs; URLs and slugs are unchanged; the canonical form `Post N: Title` is already the form
the user has seen in the nav and approved. Worst case is a heading-copy revert if `Post N:` reads awkwardly inline — a
single-file undo per post.

## Reversibility

Each change is a small in-place text edit. To revert: drop the `Post N: ` prefix from each H1 and from the
series/index/nav labels. No data migration, no URL changes.

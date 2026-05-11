---
create_time: 2026-05-11 16:10:36
status: done
prompt: sdd/prompts/202605/blog_series_two_posts.md
---
# Plan: Reframe sase.sh around a single blog series with two posts

## Context

sase.sh currently presents the **Agentic Software Engineering** series as the public launch arc on
`docs/series/agentic-software-engineering.md`. The page is structured as a 5-post roadmap: one published essay
(`Why Coding Agents Need Orchestration`) plus four planned essays (ChangeSpecs, Beads, XPrompts, ACE+Axe) that each
point at the existing product guide as a placeholder.

The companion hands-on article `Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents` is positioned as a
"Start Here" pre-read rather than as a numbered series post.

The new direction is:

- sase.sh hosts **one** blog series — the Agentic Software Engineering series. There is no second series on the horizon,
  so the site should stop hedging.
- The series has **two** posts today, and only those two:
  - **Post 1.** `Why Coding Agents Need Orchestration` — the launch essay (already at
    `docs/blog/posts/why-coding-agents-need-orchestration.md`, dated 2026-05-08).
  - **Post 2.** `Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents` — the hands-on follow-up (already at
    `docs/blog/posts/hello-sase-your-first-15-minutes.md`, dated 2026-05-10).
- The series page should reflect that lineup: no roadmap of planned essays, no "Planned; current guide: …" placeholder
  rows. Future posts can be added when they actually exist.
- The mkdocs sidebar should expose the two posts directly so a reader scanning the nav can see the series contents
  without first opening the series hub.

Both posts already exist on disk and already cross-link the series page; this plan reshapes the framing around them, it
does not author new prose.

## Goals

1. The series page reads as a complete, two-post series — not a roadmap with placeholders.
2. The blog index, homepage, and per-post Series Navigation sections agree on the canonical post order (Post 1 = launch
   essay, Post 2 = 15 minutes).
3. The left sidebar shows the two posts under the series so navigation matches the new framing.
4. PDF/handbook artifacts continue to build (no broken chapter map or stale TOC entry).

## Non-Goals

- Writing or planning additional series posts. The "ChangeSpecs / Beads / XPrompts / ACE+Axe" essays in the current
  roadmap are dropped from the series page; if/when they get written, they'll be added back.
- Renaming the series, the slugs, the post titles, or the existing URLs. All existing `/blog/<slug>/` links must keep
  working.
- Touching post bodies beyond their Series Navigation / next-post pointers.
- Changing the blog plugin behavior (auto-archive, RSS, categories).

## Reading order vs. publication order

The two posts can be read either way. The launch essay is **Post 1** (matches publish date 2026-05-08 and makes the
conceptual case first). The 15-minutes hands-on is **Post 2** (publish date 2026-05-10 and makes the abstract argument
concrete by running the system). The blog index's existing "Read these two in order" copy currently leads with the
hands-on for the "show, don't tell" pitch — we keep that suggestion, but make clear that the numbered series order is
launch-essay-first. Two compatible framings: numbered series order vs. a hands-on-first reading suggestion.

## Files To Update

### `docs/series/agentic-software-engineering.md` — primary rewrite

- Replace the five-row "Series Track" table with a two-entry list:

  | Order | Post                                                           | Status               |
  | ----- | -------------------------------------------------------------- | -------------------- |
  | 1     | Why Coding Agents Need Orchestration                           | Published 2026-05-08 |
  | 2     | Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents | Published 2026-05-10 |

- Remove the "Planned; current guide: …" rows for ChangeSpecs, Beads, XPrompts, ACE+Axe. The series page stops doubling
  as a product-guide pointer page; the existing "Reader Paths" bullet list at the bottom already covers that role for
  readers who want to jump into the product docs, and we keep that section.
- Rewrite the lede / "Start Here" copy so the page reads as a hub for an existing two-post series, not as a launch
  roadmap. The 15-minutes post is named as Post 2, not as a pre-read.
- Keep the "Publishing Notes" section's intent (canonical URLs, frontmatter discipline) but trim any text that promised
  a future series cadence.

### `docs/blog/index.md`

- Keep the "Start Here" pair, but adjust the phrasing so the two posts are explicitly Post 1 and Post 2 of the only
  series, not a generic "two on-ramp posts." Recommended reading order (hands-on first) can remain as an editorial
  suggestion below the numbered list.
- Update the sentence about the series hub: it now "lists the two published posts" rather than "tracks the launch arc
  and links the current product guides for posts still in planning."

### `docs/blog/posts/why-coding-agents-need-orchestration.md`

- Update the `## Series Navigation` block:
  - `Previous: none.`
  - `Next: Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents` (with a working relative link).
- Keep frontmatter, body, and the other "Continue reading" bullets unchanged.

### `docs/blog/posts/hello-sase-your-first-15-minutes.md`

- Update the `## Series Navigation` block so the post is identified as Post 2:
  - `Previous: Why Coding Agents Need Orchestration` (with relative link).
  - `Next: none (latest post).`
- Where the body currently calls itself "a hands-on companion," soften that phrasing so it doesn't contradict its new
  role as the second numbered post in the series. The companion framing can survive as a description of _how_ to read
  it, just not as its sole identity.

### `docs/index.md` (homepage)

- The hero CTAs and the "Next clicks" cards already point at the two posts and the series. Audit the copy on the
  "Explore the series" card and the hero buttons so nothing implies a longer roadmap. Likely one or two short tweaks; no
  structural changes.

### `mkdocs.yml` — sidebar

- Change the `Blog` nav group from:

  ```yaml
  - Blog:
      - Blog Home: blog/index.md
      - Agentic Software Engineering Series: series/agentic-software-engineering.md
  ```

  to a structure that surfaces the two posts directly, e.g.:

  ```yaml
  - Blog:
      - Blog Home: blog/index.md
      - Agentic Software Engineering Series: series/agentic-software-engineering.md
      - "Post 1: Why Coding Agents Need Orchestration": blog/posts/why-coding-agents-need-orchestration.md
      - "Post 2: Hello, SASE — Your First 15 Minutes": blog/posts/hello-sase-your-first-15-minutes.md
  ```

  The blog plugin still owns the generated archive, but listing the two posts explicitly is what gives the sidebar a
  one-glance answer to "what's in the series?". Title prefixes ("Post 1:" / "Post 2:") match the order on the series
  page. If mkdocs `strict: true` complains about double-listing posts that the blog plugin already owns, fall back to
  listing the posts only under the series page nav children (without prefix titles) or omit them and rely on the series
  hub — whichever keeps the build green.

### PDF / handbook artifacts

- `docs/javascripts/pdf-numbering.js`: the `/series/agentic-software-engineering/` chapter mapping stays valid; no
  change needed.
- `docs/templates/pdf/front.html.j2`: the contents `<ol>` already lists `Agentic Software Engineering Series` as chapter
  3 — keep as-is. Do **not** add the individual post titles; the handbook TOC is chapter-level and the blog chapter
  already covers the post archive.

## Build & Verification

- `just install` then `just check` (lint + tests). The docs build runs as part of the standard checks; any broken
  intra-doc link from removing roadmap rows will fail there.
- Quick local docs build (mkdocs) to spot strict-mode link errors introduced by the series rewrite or by adding posts to
  the nav. If `strict: true` rejects listing blog posts in the nav, fall back to the series-hub-only structure described
  above.
- Manually verify in the rendered site:
  - `/series/agentic-software-engineering/` shows two posts, no "Planned" rows.
  - `/blog/` Start Here list still works and matches the new numbering.
  - Both post pages have correct Previous/Next in their Series Navigation.
  - Sidebar exposes the two posts (if the nav variant works under strict mode).

## Risks & Trade-offs

- **Losing the "roadmap" signal.** Today's series page advertises future essays. Removing those rows trades a
  forward-looking signal for an honest "this is what exists" presentation. Acceptable per the user's framing that the
  site should reflect the one current series, not speculate.
- **Sidebar duplication.** Listing posts in nav under a group whose archive is plugin-generated risks visual duplication
  or strict-mode breakage. Mitigation: the plan accepts the series-hub-only fallback if the explicit listing is
  rejected.
- **Post-page identity drift.** Hello SASE has been pitched as a companion; reframing it as Post 2 is a small editorial
  shift. Keep the "companion" framing as a reading suggestion so the body remains coherent.

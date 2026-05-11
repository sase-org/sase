---
create_time: 2026-05-11 16:19:33
status: wip
prompt: sdd/prompts/202605/review_blog_series_polish.md
---
# Plan: Review and polish the two-post Agentic Software Engineering series update

## Context

The previous change reframed the SASE blog around one public Agentic Software Engineering series with two posts:

- Post 1: `Why Coding Agents Need Orchestration`
- Post 2: `Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents`

The implementation updated the series hub, blog index, post-level Series Navigation blocks, homepage card copy, MkDocs
navigation, and marked the original SDD tale done. A strict MkDocs build currently succeeds.

## Review Findings

The previous change is directionally correct and builds cleanly, but a few small issues remain:

1. The MkDocs Blog nav lists the two posts as flat siblings of the series hub. That exposes the posts, but it does not
   visually group them under the series, which was one of the original goals.
2. Material's blog plugin renders the post titles from post metadata, so the `Post 1:` and `Post 2:` prefixes in
   `mkdocs.yml` do not survive into the rendered sidebar. The sidebar still exposes the posts, but grouping becomes more
   important because numbering is not visible there.
3. The blog index uses an ordered list and then repeats `Post 1` / `Post 2` inside each list item. The meaning is clear,
   but the rendered copy is a little redundant.
4. The post-level navigation blocks use `Previous: none` and `Next: none (latest post)`. That is accurate, but it reads
   more like implementation notation than public documentation.

## Goals

- Keep the previous agent's framing intact: one current series, two published posts, no planned-post roadmap.
- Make the sidebar association clearer by grouping the series hub and both posts under a single Blog subsection.
- Smooth the user-facing copy in the blog index and Series Navigation blocks without changing post slugs, frontmatter,
  publication dates, or the main article bodies.
- Re-run docs checks, and run the standard repository check after file changes as required by local instructions.

## Non-Goals

- Do not author additional series posts.
- Do not revive the removed ChangeSpecs / Beads / XPrompts / ACE+Axe roadmap rows.
- Do not rename post titles, slugs, or canonical URLs.
- Do not modify memory files.
- Do not change blog plugin behavior, RSS behavior, or PDF chapter numbering unless verification exposes a concrete
  breakage.

## Implementation Steps

1. Update `mkdocs.yml` so the Blog nav has a nested Agentic Software Engineering subsection containing:
   - `Series Hub`
   - Post 1
   - Post 2
2. Polish `docs/blog/index.md` so each ordered item names the post once and explains its role without duplicating the
   numbering.
3. Polish the `## Series Navigation` blocks in both posts:
   - Post 1 should say there is no previous post in the series and link to Post 2 as next.
   - Post 2 should link back to Post 1 and say it is currently the latest post in the series.
4. Optionally tighten one or two sentences on `docs/series/agentic-software-engineering.md` if the grouped nav exposes
   awkward repetition, but avoid rewriting the page again.

## Verification

1. Run `just docs-check` after the docs/nav edits.
2. Run `just docs-pdf-check` if the nav restructure affects the handbook build or if `docs-check` emits new PDF-relevant
   warnings.
3. Run `just check` before final response because this repo's local instructions require it after non-bead file changes.
4. Inspect `git diff` to confirm the changes are limited to the plan artifact plus tightly scoped docs/nav polish.

## Risk

The blog plugin may still override explicit post labels in the rendered sidebar. The nested Blog subsection mitigates
that by making the post relationship visible through hierarchy instead of relying on title prefixes.

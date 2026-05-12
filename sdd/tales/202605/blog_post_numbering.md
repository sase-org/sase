---
create_time: 2026-05-12 01:21:47
status: done
prompt: sdd/prompts/202605/blog_post_numbering.md
---
# Blog Post Numbering Plan

## Context

The Telegram screenshot shows the mobile MkDocs Material blog drawer listing post titles without numeric prefixes, even
though the series is intended to be read as posts numbered from 0. The repository currently has mixed sources of truth:

- `docs/blog/posts/*.md` H1 headings already include `Post N:` prefixes.
- `docs/blog/index.md` and `docs/series/agentic-software-engineering.md` describe eleven posts, numbered 0 through 10.
- `mkdocs.yml` explicitly numbers most blog nav labels, but it only lists ten posts, omits `prompt-widget-and-nvim.md`,
  and still labels `whats-next-memory-mobile-web.md` as Post 9.
- The screenshot's simplified labels look like generated page/blog titles rather than the explicit `mkdocs.yml` labels,
  so relying only on nav labels is too fragile.

## Goal

Make the blog post numbering consistent and durable across the mobile drawer, generated blog/plugin surfaces, RSS/page
metadata, and hand-maintained series pages. Post numbering should start at 0 and run through the current eleven-post
series:

0. Origin Story
1. Why Coding Agents Need Orchestration
2. Hello, SASE
3. XPrompts in Depth
4. AXE
5. Beads and SDD
6. Commit Workflows
7. ChangeSpecs in Practice
8. Telegram Mobile Agents
9. Prompt Widget and sase-nvim
10. What's Next

## Implementation Approach

1. Update `mkdocs.yml` Blog navigation so it lists all eleven posts in order and corrects the final entries:
   - Add `Post 9: Where You Type — The Prompt Input Widget and sase-nvim`.
   - Change `whats-next-memory-mobile-web.md` to `Post 10: What's Next — Shared Memory, Mobile, and the Web Surface`.

2. Add explicit `title:` frontmatter to each file under `docs/blog/posts/`, matching the full numbered H1. This makes
   the numbered title the page/blog metadata title instead of allowing the blog plugin or theme to derive unnumbered
   labels from slugs.

3. Keep the visible H1 headings as-is. They are already the canonical readable titles and should continue to match the
   metadata.

4. Check nearby manual link labels only where they are clearly inconsistent with the corrected numbering, especially
   previous/next references around Posts 8, 9, and 10.

## Verification

1. Run `just install` if the workspace has not been prepared.
2. Run a docs build or the repo check path required by project memory:
   - Prefer `just check` after changes, per `memory/short/build_and_run.md`.
   - If that is too broad or blocked by environment issues, at minimum run an MkDocs build into a temporary directory
     and inspect generated navigation HTML for `Post 0:` through `Post 10:`.
3. Confirm generated output contains numbered labels for the mobile primary nav entries, especially the Telegram post
   page shown in the screenshot.

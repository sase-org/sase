---
create_time: 2026-05-11 19:39:04
status: wip
prompt: sdd/prompts/202605/blog_series_review.md
---
# Plan: Review and Polish the Agentic Software Engineering Blog Series

## Goal

Review the previous agent's implementation of the approved `sdd/tales/202605/new_blog_posts.md` plan, correct concrete
gaps, and keep the blog series surfaces internally consistent. This is a polish pass, not a rewrite of the six new
posts.

## Current State

The prior implementation added Posts 3-8, updated Post 2's next link, extended the blog index, extended the series hub,
and added the new posts to `mkdocs.yml`. The working tree started clean, and the source plan is marked `done`.

## Findings to Address

1. **Invalid XPrompt example in Post 3.** The multi-agent XPrompt example currently shows `input: target: word` between
   segment separators. The canonical `docs/xprompt.md` example uses YAML frontmatter at the top:

   ```markdown
   ---
   input:
     target: word
   ---
   ```

   After the frontmatter pair is consumed, later `---` lines become segment separators. The blog example should match
   the source docs so readers can paste it directly.

2. **Stale two-post language.** Post 2 still says the series hub contains "both published posts", and the series hub
   says "After the two posts" in Reader Paths. Those were correct before Posts 3-8 landed but are now misleading.

3. **Future posts labeled as already published.** As of 2026-05-11, Posts 3-8 are dated 2026-05-12 through 2026-05-22.
   The series hub labels them "Published" even though they are scheduled future posts. Use date-neutral wording such as
   "Publishes YYYY-MM-DD" for all rows, or a split between "Published" for past posts and "Publishes" for future posts.
   A uniform "Publishes" status is simpler and remains accurate before and after the scheduled date.

4. **Nav title mismatch for Post 3.** `mkdocs.yml` uses `Post 3: XPrompts in Depth`, while the H1, blog index, and
   series hub use the full title `Post 3: XPrompts in Depth — From One File to Full Workflows`. The nav should match the
   full numbered title, as the approved plan requested.

5. **Minor prose polish in Post 8.** "the things that horizon-line doesn't quite reach yet" is awkward in the lede.
   Tighten it without changing the post's scope.

## Implementation Steps

1. Patch `docs/blog/posts/xprompts-in-depth.md` to use the canonical frontmatter-plus-segments example from
   `docs/xprompt.md`.
2. Patch stale series references in `docs/blog/posts/hello-sase-your-first-15-minutes.md` and
   `docs/series/agentic-software-engineering.md`.
3. Patch the series hub status column to avoid claiming future posts are already published.
4. Patch `mkdocs.yml` so Post 3's nav title matches the full post title.
5. Patch the Post 8 lede for clarity.
6. Run formatting and validation:

   ```bash
   just install
   just fmt
   just check
   ```

   `just install` is required in SASE workspaces before validation because workspace virtual environments may be stale.

## Out of Scope

- Rewriting the six new posts wholesale.
- Changing publication dates, slugs, or category strategy from the approved plan.
- Editing memory files.
- Committing changes unless explicitly requested.

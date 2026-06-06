---
create_time: 2026-06-06 15:59:49
status: done
prompt: sdd/prompts/202606/remove_origin_story_reindex_blog.md
---
# Remove Origin Story Blog Post And Reindex Series

## Context

The SASE docs site is built with MkDocs Material. The public blog is source-controlled under `docs/blog/`, with explicit
blog navigation in `mkdocs.yml` and post metadata in each Markdown file. There are currently eleven numbered posts,
`[00]` through `[10]`. The request is to remove the first post, `origin-story`, entirely and decrement every remaining
post prefix so the series becomes `[00]` through `[09]`.

## Desired Result

The published site should contain ten blog posts:

| New Prefix | Post Slug                              |
| ---------- | -------------------------------------- |
| `[00]`     | `why-coding-agents-need-orchestration` |
| `[01]`     | `hello-sase-your-first-15-minutes`     |
| `[02]`     | `xprompts-in-depth`                    |
| `[03]`     | `axe-background-daemon`                |
| `[04]`     | `beads-and-sdd`                        |
| `[05]`     | `commit-workflows-plugins`             |
| `[06]`     | `changespecs-in-practice`              |
| `[07]`     | `telegram-mobile-agents`               |
| `[08]`     | `prompt-widget-and-nvim`               |
| `[09]`     | `whats-next-memory-mobile-web`         |

The origin story page should no longer be reachable as part of the built docs site, appear in the blog archive, appear
in navigation, or be linked from the series surfaces.

## Implementation Plan

1. Remove `docs/blog/posts/origin-story.md` from the docs source.

2. Update explicit MkDocs navigation in `mkdocs.yml`:
   - Delete the origin story nav item.
   - Decrement the visible `[NN]` prefixes for each remaining blog nav label.
   - Keep slugs and file paths unchanged for the remaining posts so existing URLs for technical posts remain stable.

3. Update the blog landing page at `docs/blog/index.md`:
   - Change the series count from eleven to ten.
   - Remove the origin story list entry.
   - Decrement the displayed prefixes in the remaining list entries.
   - Rewrite the ordering guidance so `[00]` and `[01]` are the why/how pair, `[02]` through `[08]` are subsystem posts,
     and `[09]` is the forward-looking post.

4. Update the series hub at `docs/series/agentic-software-engineering.md`:
   - Change eleven-post language to ten-post language.
   - Remove the origin story table row.
   - Decrement every remaining displayed prefix.
   - Adjust the prose that describes the series arc so it no longer references the origin story.

5. Update each remaining post consistently:
   - Decrement the prefix in frontmatter `title`.
   - Decrement the prefix in the first `#` heading.
   - Decrement the prefix in `links:` labels that point to neighboring posts.
   - Decrement inline numbered references and “This is [NN]” series-navigation lines.
   - Update previous/next links so the new `[00]` post has `Previous: none`, and all other posts point to the newly
     numbered neighbors.
   - Remove the old origin-story previous link from `why-coding-agents-need-orchestration.md`.
   - Update any “all eleven posts” wording inside posts to “all ten posts”.

6. Search for stale references:
   - `origin-story`
   - `Origin Story`
   - `\[10\]`
   - blog-series `[NN]` prefixes in `docs/blog`, `docs/series`, and `mkdocs.yml`

   Any remaining `[NN]` references should match the new numbering map above or be unrelated examples outside the blog
   series.

7. Validate the docs build:
   - Run `just install` first if the workspace has not already been prepared.
   - Run `just check`, per repo instructions after file changes.
   - If `just check` is too broad or fails for unrelated non-doc reasons, run `just docs-check` to specifically verify
     MkDocs strict mode, link resolution, navigation, blog archive generation, and RSS matching.

## Risks And Decisions

- I will keep remaining post slugs unchanged. The request is to decrement title prefixes, not to rename post URLs.
- I will not add a redirect for `origin-story`; “remove entirely” means the page should be absent from the docs source
  and not preserved through navigation or redirects.
- Dates and publication statuses will stay as-is. Renumbering changes series order labels, not publication metadata.
- The MkDocs blog archive is generated from files under `docs/blog/posts/`, so deleting the origin-story markdown file
  should remove it from generated blog listings and RSS.

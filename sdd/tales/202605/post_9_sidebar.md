---
create_time: 2026-05-11 21:10:49
status: wip
prompt: sdd/prompts/202605/post_9_sidebar.md
---
# Plan: Restore Post 9 In The sase.sh Sidebar

## Problem

`sase.sh` is a MkDocs Material site. The blog/series content now has eleven posts: Post 0 through Post 10. The
hand-authored blog index and series hub list:

- Post 9: `docs/blog/posts/prompt-widget-and-nvim.md`
- Post 10: `docs/blog/posts/whats-next-memory-mobile-web.md`

The primary sidebar is driven by `mkdocs.yml` `nav`. That nav currently skips `prompt-widget-and-nvim.md` and labels
`whats-next-memory-mobile-web.md` as Post 9. As a result, the sidebar cannot show the real Post 9 entry, even though the
post file, blog index, and series hub all know it exists.

There is a second thing to verify: Post 9 and Post 10 have future frontmatter dates (`2026-05-22` and `2026-05-23`). The
generated blog archive may hide future-dated posts depending on the Material blog plugin's behavior, but that should not
prevent explicitly listed `nav` entries from appearing in the sidebar once `mkdocs.yml` is corrected.

## Scope

Fix the canonical docs navigation. Do not change post slugs or URLs. Do not rewrite blog content unless validation shows
an adjacent stale reference caused by the nav mistake.

## Implementation

1. Update the `Blog` section in `mkdocs.yml`:
   - Add `"Post 9: Where You Type — The Prompt Input Widget and sase-nvim": blog/posts/prompt-widget-and-nvim.md` after
     Post 8.
   - Change the current `whats-next-memory-mobile-web.md` nav label from Post 9 to
     `"Post 10: What's Next — Shared Memory, Mobile, and the Web Surface"`.

2. Build the docs to a throwaway or standard site directory using the repo's docs tooling and inspect generated HTML:
   - Confirm the sidebar contains Post 9 pointing at `/blog/posts/prompt-widget-and-nvim/`.
   - Confirm Post 10 points at `/blog/posts/whats-next-memory-mobile-web/`.
   - Note whether the auto-generated blog archive omits future-dated posts; if it does, document that separately rather
     than conflating it with the sidebar bug.

3. Run required checks after source changes:
   - `just docs-check` for strict MkDocs validation.
   - `just check` per repo memory, because this repo requires it after file changes.

## Expected Outcome

The left sidebar on `sase.sh` lists all blog posts in order, including the real Post 9. The "What's Next" essay appears
as Post 10 everywhere, matching the post H1, blog index, and series hub.

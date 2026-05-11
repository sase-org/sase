---
create_time: 2026-05-11 19:00:20
status: done
prompt: sdd/prompts/202605/remove_blog_archive_categories.md
---
# Remove "Archive" and "Categories" from sase.sh Blog Sidebar

## Goal

Remove the "Archive" and "Categories" entries from the Blog section of the sase.sh sidebar. On mobile (and desktop) the
Blog drawer currently shows the three blog posts followed by two auto-generated entries — "Archive" and "Categories" —
that the user wants removed.

## Background

The sase.sh website is built with **MkDocs** + the **Material for MkDocs** theme. The blog plugin (Material's built-in
`blog` plugin) auto-generates two virtual sections in the Blog navigation:

- **Archive** — a date-based index of posts.
- **Categories** — a per-category index of posts.

Both default to enabled and are controlled by simple boolean flags in the plugin config. The site has only three posts
today, so neither index adds meaningful navigation value, and the user wants them removed to declutter the Blog drawer.

## Current State

`mkdocs.yml` (lines 91–94):

```yaml
plugins:
  - search
  - blog:
      post_url_format: "posts/{slug}"
  - rss: ...
```

The `rss` plugin below has its own `categories: [categories]` field — that is unrelated (it selects which front-matter
field RSS uses to populate `<category>` tags) and must not be touched.

## Proposed Change

Update the `blog` plugin block in `mkdocs.yml` to disable both auto-generated sections:

```yaml
- blog:
    post_url_format: "posts/{slug}"
    archive: false
    categories: false
```

That's the only file change required. No template overrides, no CSS, no nav reshuffling.

## Verification

Pre-change checks already done:

- `mkdocs.yml` `nav:` does not pin any `blog/archive/` or `blog/category/` pages.
- `grep` across the repo finds no internal links to `/blog/archive/` or `/blog/category/...`.

Post-change verification:

1. Run `mkdocs build` (or `mkdocs serve`) locally and confirm:
   - Build completes with no warnings about missing pages.
   - The generated `site/blog/` directory no longer contains `archive/` or `category/` subdirectories.
   - Loading the blog drawer shows only the three posts (no Archive, no Categories rows).
2. Smoke-check that the RSS feed still builds (the rss plugin is independent but reads from blog posts, so worth
   confirming it isn't accidentally affected).

## Out of Scope

- No changes to blog post front-matter (existing `categories:` keys in posts will simply be ignored once the categories
  index is disabled — they don't need to be removed).
- No changes to the desktop sidebar layout, theme, or CSS.
- No changes to the RSS plugin.
- No content changes to existing posts.

## Risk

Very low. The change is config-only, reversible by flipping the two booleans back to `true`, and there are no inbound
links to the removed pages.

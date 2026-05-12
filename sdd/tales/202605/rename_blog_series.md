---
create_time: 2026-05-12 10:10:15
status: done
prompt: sdd/prompts/202605/rename_blog_series.md
---
# Plan: Rename the sase.sh blog series hub

## Goal

Rename the public `sase.sh` series hub from **Agentic Software Engineering Series** to **SASE Blog Series** and update
all current site references that present the old title to readers.

## Context

The `sase.sh` site is built from MkDocs Material. The current series hub lives at
`docs/series/agentic-software-engineering.md`, and the sidebar label is configured in `mkdocs.yml`. Individual blog
posts also include local nav frontmatter that points at the hub using the old label, plus closing links that call it the
Agentic Software Engineering series.

Historical SDD tales and research notes also mention the old title, but those are project records rather than rendered
`sase.sh` site content. I will not update those unless explicitly asked.

## Proposed Scope

1. Keep the existing hub URL stable at `/series/agentic-software-engineering/`.
   - This is a rename, not a URL migration.
   - Keeping the file path avoids breaking existing inbound links, sitemap entries, and internal references.

2. Update public navigation labels.
   - Change the Blog nav entry in `mkdocs.yml` from `Agentic Software Engineering Series` to `SASE Blog Series`.
   - Change each blog post's frontmatter nav breadcrumb entry from `Agentic Software Engineering Series` to
     `SASE Blog Series`.

3. Update visible page copy.
   - Change the hub H1 to `SASE Blog Series`.
   - Refresh nearby hub copy so it reads naturally with the new name while preserving the explanation of agentic
     software engineering as the subject of the posts.
   - Change `docs/blog/index.md` to introduce the `SASE Blog Series`.
   - Change post footer/body links such as `Agentic Software Engineering series` and
     `Agentic Software Engineering series hub` to `SASE Blog Series`.
   - Update the PDF front-matter contents label.

4. Verify references.
   - Search rendered-site sources for the exact old public title, title-case label, and lower-case link phrase.
   - Leave unrelated uses of `Structured Agentic Software Engineering` and category labels like
     `Agentic Software Engineering` intact, because they refer to the project or category rather than the renamed hub.

5. Run validation.
   - Run `just install` first if needed for this ephemeral workspace.
   - Run `just check` after file changes, per repo instructions.

## Expected Result

The sidebar, series hub, blog index, blog post breadcrumbs, post cross-links, and handbook PDF contents all present the
series as **SASE Blog Series**, while existing URLs continue to work.

---
create_time: 2026-05-12 13:55:12
status: done
prompt: sdd/prompts/202605/blog_post_bracket_numbering.md
---
# Implement Blog Post Bracket Numbering

## Goal

Adopt option B from `.sase/home/.sase/plans/202605/blog_post_numbering_format.md`: replace the visible SASE blog series
prefix `Post N:` with a zero-padded bracket index, `[00]` through `[10]`.

The change is editorial/presentation-only. Post order, publication dates, slugs, filenames, URLs, and the 0-indexed
series model stay unchanged.

## Chosen Format

Use these labels:

- `[00] Origin Story — Where SASE Came From`
- `[01] Why Coding Agents Need Orchestration`
- `[02] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents`
- `[03] XPrompts in Depth — From One File to Full Workflows`
- `[04] AXE — The Background Daemon That Keeps Agent Work Moving`
- `[05] Beads and SDD — Planning Multi-Agent Work That Actually Lands`
- `[06] Commit Workflows — The Pluggable Path From Diff to PR`
- `[07] ChangeSpecs in Practice — Review State Outside the Chat`
- `[08] Driving SASE From Your Phone — Telegram as the Mobile Control Surface`
- `[09] Where You Type — The Prompt Input Widget and sase-nvim`
- `[10] What's Next — Shared Memory, Mobile, and the Web Surface`

This keeps the identifier short, width-stable, familiar to programmers, and safe in Markdown, YAML frontmatter, MkDocs
navigation labels, generated HTML, RSS titles, and link previews.

## Scope

Update live site content only:

- `docs/blog/posts/*.md`
- `docs/blog/index.md`
- `docs/series/agentic-software-engineering.md`
- `mkdocs.yml`

Do not update archival planning/history records under `sdd/tales/` or `sdd/prompts/`.

## Implementation Plan

1. Build a deterministic mapping from old labels to new labels:
   - `Post 0: ...` -> `[00] ...`
   - `Post 1: ...` -> `[01] ...`
   - continue through `Post 10: ...` -> `[10] ...`

2. Update each blog post file:
   - Frontmatter `title:` should use the bracket label.
   - H1 should use the bracket label.
   - Frontmatter `links:` labels should use bracket labels.
   - Related-post links and Series Navigation previous/next labels should use bracket labels.
   - Short prose references like `Post 3` should become `[03]` where they are referring to a specific series entry.
   - Sentences like `This is Post 3 of...` should become `This is [03] in...` to avoid the old naming convention.

3. Update the blog landing page:
   - The ordered list link text should use `[00]` through `[10]`.
   - The summary paragraph should use the new shorthand: `[00]`, `[01]`, `[02]`, `[03]-[09]`, and `[10]`.

4. Update the series hub:
   - The intro should describe the same reading order using bracket labels.
   - The table link text should use `[00]` through `[10]`.

5. Update `mkdocs.yml`:
   - Keep the existing quoted YAML nav keys.
   - Replace each Blog nav label with the corresponding bracket label.

6. Spot-check for stale live-doc labels:
   - Run `rg` across `docs/` and `mkdocs.yml` for `Post [0-9]` and `Post 10`.
   - Run `rg` for old title fragments such as `Post 9: Where You Type` and `Post 10: What's Next`.
   - Ignore stale matches in archival `sdd/` paths.

## Verification

1. Run `just install` before project checks, per workspace memory.
2. Run `just check` after edits, per project memory.
3. Build the site if `just check` does not clearly exercise MkDocs:
   - `mkdocs build -d /tmp/sase-site`
4. Verify generated output:
   - `rg "\\[(00|01|02|03|04|05|06|07|08|09|10)\\]" /tmp/sase-site`
   - `rg "Post (0|1|2|3|4|5|6|7|8|9|10)(:|\\b)" /tmp/sase-site` should return no live generated-page labels.

## Out Of Scope

- Renaming files, slugs, or URLs.
- Changing post order or publication dates.
- Editing archival `sdd/tales/` or `sdd/prompts/` records.
- Rewriting non-blog documentation except for links generated from the live series surfaces above.

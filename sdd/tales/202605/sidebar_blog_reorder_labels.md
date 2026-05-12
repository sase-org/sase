---
create_time: 2026-05-11 21:43:03
status: wip
prompt: sdd/prompts/202605/sidebar_blog_reorder_labels.md
---
# Plan: Move Blog Sidebar Section And Rename Docs Groups

## Problem

The `sase.sh` site is built from MkDocs Material. Its left sidebar and section labels are controlled by the top-level
`nav` list in `mkdocs.yml`. The current navigation puts `Blog` near the top, before the core documentation sections, and
uses the section labels `Start`, `Concepts`, and `Operations`.

The requested product shape is:

- The documentation-first sections should appear before `Blog`.
- `Blog` should move to the bottom of the sidebar, after the current docs/reference sections.
- `Start` should be renamed to `The Basics`.
- `Concepts` should be renamed to `Beyond the Basics`.
- `Operations` should be renamed to `The Nitty Gritty`.

## Scope

This is a navigation structure change only. Keep all page paths, slugs, blog post labels, and content unchanged. Because
`mkdocs-pdf.yml` inherits from `mkdocs.yml`, the PDF build should receive the same navigation ordering automatically
unless validation shows otherwise.

Do not modify memory files or unrelated docs content.

## Implementation

1. Update `mkdocs.yml` `nav`:
   - Keep `Home` first.
   - Move the entire existing `Blog` section to the bottom of the top-level navigation, after `Reference`.
   - Rename only the three requested top-level section labels:
     - `Start` -> `The Basics`
     - `Concepts` -> `Beyond the Basics`
     - `Operations` -> `The Nitty Gritty`
   - Preserve all child nav entries exactly as they are.

2. Validate the rendered docs navigation:
   - Run the repo's docs check if available.
   - Inspect the generated or checked MkDocs output enough to confirm the top-level sidebar order is: `Home`,
     `The Basics`, `Beyond the Basics`, `The Nitty Gritty`, `Integrations`, `Reference`, `Blog`.

3. Run required repository checks:
   - Per repo memory, run `just install` first if the workspace may not be current.
   - Run `just check` after source changes.
   - If a narrower docs command exists, run it as well or explain why `just check` covers it.

## Expected Outcome

The `sase.sh` sidebar presents the core docs first with clearer progression-oriented section names, and the full Blog
section appears at the bottom without changing any URLs or page content.

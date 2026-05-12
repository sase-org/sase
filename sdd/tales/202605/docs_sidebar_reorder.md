---
create_time: 2026-05-12 09:34:13
status: done
prompt: sdd/prompts/202605/docs_sidebar_reorder.md
---
# Plan: Reorder and Rename SASE Docs Sidebar Sections

## Goal

Update the public `sase.sh` documentation sidebar so the main learning sections read more clearly and the blog appears
after the documentation/reference material:

- Move the top-level `Blog` section from near the top of the sidebar to the bottom.
- Rename `Start` to `The Basics`.
- Rename `Concepts` to `Beyond the Basics`.
- Rename `Operations` to `The Nitty Gritty`.

## Current State

The sidebar order and labels are controlled by `mkdocs.yml` under the top-level `nav` key. The current order is:

1. `Home`
2. `Blog`
3. `Start`
4. `Concepts`
5. `Operations`
6. `Integrations`
7. `Reference`

The docs use MkDocs Material with `navigation.sections` and `navigation.indexes`, plus custom sidebar section styling in
`docs/stylesheets/extra.css`. That CSS styles all top-level section labels generically and does not depend on the
specific section names, so this change should not require CSS changes.

## Implementation Scope

Change only `mkdocs.yml` unless verification shows another generated or derived file must be updated. The docs content,
blog post paths, plugin configuration, CSS, and templates should remain unchanged.

## Steps

1. Edit `mkdocs.yml`:
   - Keep `Home` first.
   - Move the full `Blog` nav block to the end of the top-level `nav` list.
   - Rename `Start` to `The Basics` without changing its child pages.
   - Rename `Concepts` to `Beyond the Basics` without changing its child pages.
   - Rename `Operations` to `The Nitty Gritty` without changing its child pages.
   - Preserve all existing indentation, page titles, and page paths.

2. Verify the nav configuration:
   - Inspect the edited `nav` block to confirm there is a single `Blog` section and it is last.
   - Confirm the old top-level labels no longer appear in `mkdocs.yml`.

3. Build/check:
   - Because project memory says to run `just install` before checks in this workspace, run `just install` if needed.
   - Run `just check` after the file change, as required by project memory.
   - If `just check` is too broad or blocked by environment issues, at minimum run the strict docs build command used by
     the project documentation, then report the blocker and the narrower verification result.

## Risks

- YAML indentation mistakes could break the MkDocs build. A strict docs build or `just check` should catch this.
- Moving `Blog` changes sidebar order site-wide, but it should not affect URLs because all page paths remain unchanged.
- Renaming sections changes visible navigation text only; deep links and page titles should remain stable.

## Acceptance Criteria

- `mkdocs.yml` top-level nav order is: `Home`, `The Basics`, `Beyond the Basics`, `The Nitty Gritty`, `Integrations`,
  `Reference`, `Blog`.
- All existing child pages under those sections remain present and point to the same files.
- The docs/site check passes, or any environment-specific failure is clearly reported with the command output summary.

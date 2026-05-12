---
create_time: 2026-05-12 11:20:26
status: done
prompt: sdd/prompts/202605/homepage_hero_buttons.md
---
# Plan: Reduce Homepage Hero Buttons

## Context

The home page is a MkDocs Material page defined in `docs/index.md`. The top hero section contains the overview diagram
and, immediately above it, a `.sase-actions` button row.

The local source currently has these six hero buttons:

- `Start in 15 minutes`
- `Read the launch essay`
- `Start with ACE`
- `Explore the series`
- `Download PDF`
- `View on GitHub`

The requested end state is that the top hero button row keeps only:

- `Download PDF`
- `View on GitHub`

The lower "Next clicks" cards later on the page are a separate navigation section and should not be removed as part of
this change unless the implementation reveals they are sharing the same top hero button markup, which they currently are
not.

One detail to preserve: the live page text currently differs from local source, because the live crawl does not show
`Start in 15 minutes` or `Download PDF`. The repository source is the deploy target, so the change should be made
against the local `docs/index.md` hero actions and verified with a local MkDocs build.

## Implementation

1. Edit only the hero action list in `docs/index.md`.
   - Remove the four non-requested top hero buttons:
     - `Start in 15 minutes`
     - `Read the launch essay`
     - `Start with ACE`
     - `Explore the series`
   - Keep the two requested hero buttons:
     - `Download PDF` with `href="/downloads/sase-handbook.pdf"`
     - `View on GitHub` with `href="https://github.com/sase-org/sase"`

2. Preserve the existing home page structure.
   - Leave the overview diagram, hero copy, and subsequent sections intact.
   - Leave lower-page links/cards intact, including the "Next clicks" cards for docs navigation.
   - Avoid CSS changes unless the reduced action row exposes a responsive layout issue.

3. Verify the docs build.
   - Run `just docs-check` for the MkDocs strict build.
   - Because this repo's memory requires `just check` after file changes, run `just install` first if needed, then run
     `just check` before finishing. If `just check` is blocked by an environment/dependency issue, report the blocker
     with the exact command result.

## Acceptance Criteria

- The rendered home page hero has only `Download PDF` and `View on GitHub` as top buttons above the overview diagram.
- No other homepage content is removed.
- `mkdocs build --strict` via `just docs-check` succeeds.
- Repo-required verification via `just check` is run or any blocker is clearly documented.

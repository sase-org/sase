---
create_time: 2026-05-12 13:04:00
status: done
prompt: sdd/prompts/202605/blog_series_button.md
---
# Add Homepage Blog Series Button

## Goal

Add a new blue homepage button labeled `SASE Blog Series` alongside the existing hero action buttons above the SASE
overview diagram. The button should route visitors to the existing SASE blog series hub.

## Context

- The public site is MkDocs Material, configured in `mkdocs.yml` with `site_url: https://sase.sh/`.
- The homepage content is `docs/index.md`.
- The existing hero buttons live in the `.sase-actions` block near the top of `docs/index.md`, immediately before the
  overview image figure.
- The blog series hub already exists at `docs/series/agentic-software-engineering.md`.
- With `use_directory_urls: true`, the site URL for that page is `/series/agentic-software-engineering/`.

## Implementation Plan

1. Update only `docs/index.md` in the hero `.sase-actions` block.
2. Add a third `<a class="md-button">` entry labeled `SASE Blog Series`.
3. Point the new button at `series/agentic-software-engineering/`, matching the homepage's existing relative internal
   link style.
4. Keep the same `md-button` class so the new link inherits the existing blue Material button styling and responsive
   behavior from `docs/stylesheets/extra.css`.
5. Avoid unrelated copy, layout, CSS, navigation, or memory-file changes.

## Verification Plan

1. Confirm the changed homepage contains the new link with the requested label and target.
2. Run the repo-required verification after changes: `just install` if needed, then `just check`.
3. If `just check` is too broad or blocked by environment state, run a focused docs build with `mkdocs build --strict`
   and report the limitation clearly.

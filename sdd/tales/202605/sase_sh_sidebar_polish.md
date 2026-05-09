---
create_time: 2026-05-09 18:47:39
status: wip
prompt: sdd/prompts/202605/sase_sh_sidebar_polish.md
---
# SASE Plan: Polish the sase.sh Sidebar

## Goal

Make the `sase.sh` documentation sidebar feel intentional, polished, and easier to scan. The sidebar should present the
existing reader-oriented navigation as beautiful collapsible sections without moving published documentation URLs or
introducing a custom frontend stack.

## Current State

- `mkdocs.yml` already uses MkDocs Material, strict builds, `site_url: https://sase.sh/`, an explicit navigation tree,
  light/dark palettes, and `extra_css: stylesheets/extra.css`.
- `docs/stylesheets/extra.css` currently focuses on the public homepage visual system. It does not style the Material
  sidebar beyond the default theme.
- There is no `overrides/` directory and no custom JavaScript for navigation behavior.
- Built `site/index.html` shows Material already emits checkbox-backed nested navigation for the top-level groups
  (`Blog`, `Start`, `Concepts`, `Operations`, `Integrations`, `Reference`). That means collapsible behavior can likely
  be achieved by configuring Material correctly and styling the existing structure rather than replacing it.
- The existing navigation taxonomy is good enough for this pass. The work should improve presentation and ergonomics,
  not rename pages or reorganize URLs.

## Design Direction

The sidebar should read like a compact product documentation control surface: quiet, structured, and precise. Avoid
marketing-style decoration, heavy gradients, one-note color washes, or large card-like chrome. Use the current SASE
visual variables as a base, but add sidebar-specific surfaces so navigation has depth, rhythm, and clear active states.

Key visual choices:

- A subtly separated sidebar rail with a soft surface, restrained border, and improved scroll behavior.
- Top-level groups styled as compact section headers with explicit disclosure affordances.
- Active page states that are visible without relying only on color: a left accent rule, stronger text weight, and a
  clean background treatment.
- Nested page links with clearer indentation, improved line height, and enough hit area for trackpad and touch use.
- Light and dark mode parity using the existing SASE palette.
- Mobile drawer compatibility: the same visual language should work when the sidebar becomes the hamburger drawer.

## Implementation Plan

1. Inspect Material's current generated sidebar markup after a strict build so selectors target stable classes such as
   `.md-sidebar--primary`, `.md-nav__item--section`, `.md-nav__toggle`, `.md-nav__link`, and `.md-nav__icon`.
2. Update `mkdocs.yml` navigation features if needed so top-level groups are collapsible by default. Keep
   `navigation.sections`, avoid `navigation.expand`, and only add a Material-supported feature if it improves the
   behavior without custom code.
3. Extend `docs/stylesheets/extra.css` with a dedicated sidebar section:
   - Define sidebar-specific CSS variables derived from the current SASE tokens.
   - Style the primary sidebar container, scrollable nav rail, top title, section rows, nested links, hover states, and
     active/current page states.
   - Rotate or otherwise emphasize Material's existing disclosure icon for collapsed versus expanded groups.
   - Keep border radii at or below the existing 8px design guideline.
   - Add responsive rules so the desktop sidebar and mobile drawer both remain usable.
4. Prefer CSS-only behavior. If Material configuration cannot make the section state behave well, add the smallest
   possible `docs/javascripts/sidebar.js` to initialize default collapsed state and persist user choices, then register
   it through `extra_javascript`. Only do this after verifying CSS/configuration is insufficient.
5. Build the docs and inspect the generated HTML/CSS output. Use a local `mkdocs serve` or static build preview if
   practical to verify desktop and mobile behavior.
6. Run repository-required checks after file changes:
   - `just install` first if the workspace is not already installed.
   - `just docs-check`.
   - `just check`.

## Acceptance Criteria

- Top-level sidebar groups are collapsible and expandable on desktop and in the mobile drawer.
- The active page is visually obvious in both light and dark modes.
- Sidebar typography, spacing, hover states, and nested indentation look deliberate rather than default Material.
- No published docs URLs are moved or renamed.
- The change is scoped to docs presentation files unless a tiny navigation script proves necessary.
- `just docs-check` and `just check` pass, or any failure is reported with the exact blocker.

## Non-Goals

- Do not redesign the homepage or rewrite docs content.
- Do not replace MkDocs Material's navigation system with a custom sidebar component.
- Do not add a JavaScript framework.
- Do not change the top-level information architecture unless verification shows a small label/order adjustment is
  needed for collapsible ergonomics.

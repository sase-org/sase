---
create_time: 2026-05-09 19:34:48
status: done
prompt: sdd/prompts/202605/sidebar_section_emphasis.md
---
# Sidebar Section Emphasis on sase.sh (Desktop Web)

## Problem

On the desktop web view of [sase.sh](https://sase.sh/), the left sidebar groups (`Home`, `Blog`, `Start`, `Concepts`,
`Operations`, `Integrations`, `Reference`) blend into the list of child pages. The section headers and the page links
share a similar size, weight, and muted ink color, so the sidebar reads as one long flat list rather than the structured
table-of-contents the `nav:` block in `mkdocs.yml` is meant to convey.

Mobile already reads well because Material renders the primary nav as an overlay drawer with its own typographic
hierarchy — that view is **out of scope**.

## Goal

Make the section headers (the labels rendered for top-level entries because `navigation.sections` is enabled) clearly
stand out from their child page links on desktop, while staying consistent with the existing SASE design system (Inter
sans, teal accent, all-caps eyebrow treatment).

## Context: How Material Renders These on Desktop

With `features: [navigation.sections, navigation.indexes]` set in `mkdocs.yml` and no tabs feature, Material for MkDocs
renders the primary sidebar like this on desktop:

```
<nav class="md-nav md-nav--primary">
  <label class="md-nav__title">SASE</label>          ← site title (top of sidebar)
  <ul class="md-nav__list">
    <li class="md-nav__item md-nav__item--section">  ← one per top-level group
      <span class="md-nav__link">Start</span>         ← the section label we want to style
      <nav class="md-nav"> ... child links ... </nav>
    </li>
    ...
  </ul>
</nav>
```

So the styling target is `.md-nav--primary .md-nav__item--section > .md-nav__link`. The right-hand TOC
(`.md-nav--secondary`) and the per-page nested groups must not be affected. The mobile drawer also uses
`.md-nav--primary`, but Material wraps it in `[data-md-toggle="drawer"]` overlay context — we'll gate the new styles
behind a desktop-only `@media screen and (min-width: 76.25em)` query (the breakpoint where Material reveals the
persistent left sidebar) so the drawer is untouched.

## Design Direction

Re-use the established SASE "eyebrow" pattern (already used on the home page `.sase-kicker` / `.sase-section__eyebrow`
and on table headers): all-caps, bold, letter-spaced, full-contrast ink, with a short accent rule. Apply that treatment
to section labels in the sidebar so they read as group titles, not link rows.

Concrete treatment for each section label on desktop:

1. **Typography**: `text-transform: uppercase`, `letter-spacing: 0.1em`, `font-weight: 700`, slightly larger than child
   links (~`0.7rem` vs the current `0.72rem` link size — the uppercase + tracking does most of the visual work, so we
   don't need to bump the size much).
2. **Color**: switch from `--sase-ink-muted` to `--sase-ink` (full contrast) so the label reads as a heading, not
   another link.
3. **Separator**: a thin top border (`1px solid var(--sase-rule)`) with comfortable top padding, so each group is
   visually a band. Suppress the border on the first section (`:first-child`) so we don't draw a rule directly under the
   site title.
4. **Vertical rhythm**: increase top margin between groups (`var(--sp-5)` ≈ `1.5rem`) and tighten the gap between the
   label and its child list so the label "owns" the children below it.
5. **Non-clickable cue**: Material renders the label as a non-link `<span>` (it has no `index.md`) or as a clickable
   `<a>` (it does, via `navigation.indexes`). Keep the color stable on hover/focus for the non-link case; for the link
   case, use the same accent-strong hover already defined for `.md-nav__link` so it still feels interactive.
6. **Active section emphasis**: when a child page in the section is the current page, color the section label with
   `--sase-accent-strong` so the user sees both their location _within_ the section and _which section_. Detected via
   `.md-nav__item--section:has(.md-nav__link--active) > .md-nav__link` (graceful CSS fallback for browsers without
   `:has()` — they'll still get the new typography, just without the section-active highlight).
7. **Child links unchanged**: keep their current `--sase-ink-muted` color and normal-case rendering, so they read
   clearly as items _within_ the group.

This mirrors the "kicker rule" already used elsewhere on the site without introducing a new visual primitive. The
all-caps + accent-rule eyebrow is already part of the SASE vocabulary, so the sidebar will feel native rather than
bolted on.

### Optional: small accent bar before each section

To strengthen the eyebrow analogy, prefix each section label with the same `1.5rem × 1px` accent bar that
`.sase-kicker::before` and `.sase-section__eyebrow::before` already use. This is the change with the strongest visual
payoff but also the highest "design opinion" factor — I'll include it in the implementation but make it trivial to
remove if it feels heavy in practice.

## Scope of Changes

Files touched:

- `docs/stylesheets/extra.css` — only file. Add a new section ("Sidebar section emphasis (desktop)") near the existing
  "Sidebar navigation" block (~line 201) so all nav rules live together. Override the unscoped `.md-nav__title` /
  `.md-nav__link` rules with a desktop-only media query.

No changes to:

- `mkdocs.yml` — the `navigation.sections` feature is already what produces the section grouping; we're just restyling
  the rendered labels.
- Markdown content under `docs/`.
- The right-hand TOC (`.md-nav--secondary`).
- The mobile drawer (gated by `min-width: 76.25em`).

## Acceptance Criteria

1. On desktop (`≥ 1220px`), each top-level group label in the left sidebar renders as an uppercase, full-contrast
   heading clearly distinct from its child page links.
2. A thin separator visually bands each section, with the first section unbordered.
3. The current section's label is highlighted with the accent color (where `:has()` is supported).
4. Child page links inside each section are visually unchanged in size/color, including the existing `--active`
   treatment.
5. The right-hand TOC styling is unchanged.
6. The mobile drawer (browser width below the desktop breakpoint) is unchanged from what currently ships.
7. Light and dark (`slate`) palettes both look intentional — verified by toggling the theme switcher on the home page
   and one deep page (e.g. `Operations → Telemetry`).
8. `just lint` and `just check` pass (CSS isn't linted, but the build via `mkdocs build` under `strict: true` should
   still succeed with no new warnings).

## Verification Plan

1. Run `mkdocs serve` (or `just docs-serve` if available) and load the site at three widths: `≥ 1400px`, `~1100px`
   (still desktop-ish, just below tablet break), and `~600px` (mobile drawer).
2. Walk through each of the seven top-level groups on desktop, confirming label prominence and the active-section
   highlight as you click into child pages.
3. Toggle dark mode and re-confirm contrast.
4. Cross-check the right-hand TOC and admonition styles to confirm no regressions (since we're touching `.md-nav__title`
   cousins).
5. Mobile drawer: open the hamburger, confirm it looks the same as before.

## Risks / Notes

- **`:has()` support**: Used only for the active-section accent. All target browsers (Chrome 105+, Safari 15.4+, Firefox
  121+) support it; older browsers fall back to the same typography minus the accent color, which is still an
  improvement over today.
- **Specificity collisions**: The current `.md-nav__title` and `.md-nav__link` rules are unscoped. The new rules will be
  more specific (`.md-nav--primary .md-nav__item--section > .md-nav__link`) so they win without `!important`.
- **`navigation.indexes` interaction**: Some sections may have a clickable index page (currently none in `mkdocs.yml`
  do, since each top-level group lists explicit children), but if one is added later the section label would become an
  `<a>`. The proposed hover/focus rule covers both cases, so adding an index page later is safe.
- **Out of scope on purpose**: Not restyling the site title (`.md-nav__title` for "SASE" at the top of the sidebar), not
  changing the TOC, not touching child link colors, not altering the mobile drawer — these were called out as already
  good or out of scope.

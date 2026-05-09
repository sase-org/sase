---
create_time: 2026-05-09 19:03:47
status: done
prompt: sdd/prompts/202605/sase_sh_visual_redesign.md
---
# SASE Plan: sase.sh Cosmetic Redesign

## Goal

Make `sase.sh` look beautiful, intentional, and editorial — on desktop and mobile — without touching any content, URLs,
navigation taxonomy, or build pipeline. The site should feel like a considered product-and-essays surface (think small,
opinionated dev-tool sites: Linear-ish restraint, Vercel-ish clarity, with our own warm-teal-on-paper personality), not
a default MkDocs Material clone with a bolted-on hero.

The work is **purely presentational**: typography, color, spacing, image treatment, motion, and layout polish. No
content changes, no JS framework, no theme replacement, no URL moves.

## Current State (relevant facts)

- MkDocs Material with `palette` already set: light `default` / dark `slate`, primary black, accent teal.
  `extra_css: stylesheets/extra.css`. `strict: true`. `use_directory_urls: true`.
- The custom homepage lives in `docs/index.md` and is styled by per-section classes (`sase-hero`, `sase-section`,
  `sase-card`, `sase-split`, `sase-image-grid`, `sase-actions`). All current home styling is in
  `docs/stylesheets/extra.css` (~330 LOC). Hero uses two soft diagonal gradients on a paper background.
- Homepage CTAs use the default `md-button` / `md-button--primary` styles.
- Doc pages (e.g. `ace.md`, `axe.md`, `beads.md`, `xprompt.md`) and the blog index/post are rendered with stock Material
  chrome — no custom styling beyond what cascades from `extra.css`. Code blocks, admonitions, tables, headings, and
  inline code are stock.
- Blog uses the Material `blog` plugin; posts have a date, categories, and a `<!-- more -->` excerpt cut. The series
  page uses a markdown table.
- `pdf.css` is scoped to the print/PDF build (`mkdocs-pdf.yml`) — must not be regressed.
- A prior pass (`sase_sh_sidebar_polish`) tuned the sidebar. Don't undo that work; only make the surrounding chrome
  cohere with the new visual system.

## Design Direction

**One sentence:** quiet paper-and-ink feel in light mode, deep verdant graphite in dark mode, with a single warm teal
accent doing all the lifting — generous whitespace, confident typography, and small, deliberate motion.

### Visual identity

- **Typography stack.** Move the typeface system from Material defaults to a curated pair: Inter (or `system-ui`
  fallback) for UI/body, and a serif display face (Fraunces, with Georgia fallback) reserved for the homepage `h1`, blog
  post `h1`, and section titles. Mono stays JetBrains Mono / `ui-monospace`. All fonts loaded via `extra_css`
  `@font-face` with `font-display: swap`, or self-hosted `assets/fonts/` if practical. Tighter tracking on display
  sizes; looser line-height (1.65) on body copy; max body measure ~68ch.
- **Color tokens.** Refine the existing `--sase-*` token set into a layered system:
  - Surfaces: `--sase-bg`, `--sase-surface`, `--sase-surface-raised`, `--sase-surface-sunken`.
  - Text: `--sase-ink`, `--sase-ink-muted`, `--sase-ink-subtle`.
  - Borders: `--sase-rule`, `--sase-rule-strong`.
  - Accent: `--sase-accent`, `--sase-accent-strong`, `--sase-accent-soft`, `--sase-accent-ink` (text-on-accent).
  - Warm secondary kept for hero highlight only.
  - Both light and dark schemes get explicit, hand-tuned values (don't auto-derive); ensure WCAG AA on body and AAA on
    headings where possible.
- **Spacing scale.** Introduce a small modular scale (`--sp-1`..`--sp-12`) and use it consistently across hero,
  sections, cards, and doc content. Larger vertical rhythm between sections (≥ 5rem on desktop, scaling down on mobile).
- **Radii & elevation.** Two radii only: `--radius-sm` (6px) for inline chrome, `--radius-md` (12px) for cards/hero.
  Elevation as one soft long shadow + a tight contact shadow, both via tokens.
- **Motion.** A single shared transition token (`--ease`, `--dur`). Use only on hover/focus for buttons, cards, and
  links. Respect `prefers-reduced-motion`.

### Homepage

- **Hero.** Replace the current dual-gradient block with a quieter composition: a paper surface with one subtle
  vignette, a faint teal-to-warm wash anchored bottom-right behind the visual, and a thin top hairline rule.
  Display-serif `h1` with optical sizing; kicker shrinks and gets a leading bullet rule. Lede paragraph in the body
  sans, slightly larger (1.05–1.1rem), max 38ch.
- **Action buttons.** Replace stock `md-button` look with two button variants: primary (filled accent, ink-on-accent
  text, tight letter-spacing), secondary (transparent, 1px rule, accent text on hover). Buttons use the new radius and
  motion tokens.
- **Hero visual.** Frame the overview image with a soft inner border, ambient shadow, and a subtle gradient mat behind
  it so it reads as an artifact, not a screenshot dump. On mobile, the visual stacks below copy with reduced height and
  the same framing.
- **Sections.** Section eyebrow becomes uppercase tracked label preceded by a 1.5rem rule. `h2` is display-serif. Cards
  get a refined treatment: hairline border, soft surface, a small accent corner mark on hover, and a chevron-arrow on
  the trailing link that nudges on hover. Card grid spacing increases; cards align to a consistent baseline.
- **Split section** ("The coordination model" + primitive list). Sharper two-column rhythm on desktop; primitive list
  becomes a definition-style list with a left accent rule and monospace primitive names.
- **Image grid.** Figures get matching aspect frames, restrained captions in small caps, and a subtle hover lift.

### Doc pages (chrome + content)

- **Top header.** Tighten the Material header: thinner bottom rule, refined logo/title alignment, smaller search input
  that expands on focus, refined version/repo affordance.
- **Body typography.** Set custom rules for `.md-typeset`: heading scale (display-serif on `h1`/`h2`, sans on `h3`+),
  tighter heading letter-spacing, `prose`-style body line-height and measure, prettier blockquotes (no left bar; small
  inline quote glyph + indent), refined list bullets (custom `::marker` color), and custom anchor-link icon styling.
- **Inline code & code blocks.** Inline code: warm-tinted background, monospace, slightly smaller. Fenced code: rounded
  `--radius-md` container, subtle top bar showing language pill on the left and a copy button on the right (Material
  already adds the copy button — just style it). Two themes: light (paper) / dark (graphite), tuned to the SASE palette
  rather than stock Material syntax colors.
- **Admonitions.** Replace stock chunky look with a quieter card: thin left rule in the variant color, small icon,
  lighter background tint, no heavy bottom border. Variants: note, tip, warning, danger, example.
- **Tables.** Borderless feel: no outer box, subtle row dividers, header in small-caps tracked, alternating row tint
  that's almost imperceptible, comfortable row padding, horizontal scroll wrapper on mobile with a fade edge.
- **Anchor / TOC.** Right-rail TOC gets refined typography, a lefthand active-rule, and improved scroll-spy contrast in
  both themes.
- **In-content CTAs.** The "next clicks" pattern from the homepage is reusable as `sase-card-grid` — make sure it works
  inside doc pages too if reused.

### Blog & series

- **Blog index.** Style the auto-generated post list as editorial entries: large display-serif post title, date in small
  caps with a hairline separator, category chips, excerpt in body sans with the existing `<!-- more -->` cut, and a
  "Read essay →" link.
- **Blog post.** Centered narrow measure (~68ch), display-serif `h1` with a small kicker ("ESSAY") and date stamp.
  Drop-cap optional on the first paragraph (off by default to avoid surprising the editor). Section headings get the
  same tracked-eyebrow rhythm as the homepage. Footer of post: author/date strip, share/repo links, and a "Continue the
  series" card row.
- **Series page.** Style the current markdown table as a roadmap: numbered circular badges, status chip per row
  (Published / Planned), hover affordance on each entry.

### Footer

- Replace the default Material footer block with a custom footer rendered via CSS targeting
  `.md-footer-meta`/`.md-footer__inner`: left = SASE wordmark + copyright; center = quick links (already present in
  nav); right = GitHub icon + "Built with MkDocs" credit. Subtle top rule, generous padding, dark-mode parity.

### Mobile

- Hero stacks: copy first, then visual; reduced padding; `h1` scales to 1.9rem display serif; CTA buttons go full-width
  1-up but keep their refined chrome.
- Section spacing compresses but visual rhythm preserved (eyebrow + h2 + content).
- Card grids collapse to single column with comfortable card padding and tap targets ≥ 44px.
- Doc-page header: search collapses to icon, breadcrumbs hidden, sidebar drawer inherits the polished sidebar from the
  prior pass — verify cohesion only.
- Tables become horizontal-scroll with a fade-out gradient on the right edge to hint at more content.

### Micro-interactions (CSS only)

- Buttons: 120ms ease on background, transform: translateY(-1px) on hover, slight shadow bloom.
- Cards: 160ms ease on border color, surface, and shadow; trailing-link arrow nudges 2px on hover.
- Anchor links: underline draws in from the left on hover (background-image gradient trick).
- Hero visual: very subtle parallax-feel via `transform: translateZ(0)` shadow only — no JS.
- All transitions gated by `@media (prefers-reduced-motion: reduce)` to be no-ops.

## Implementation Plan

The work is concentrated in `docs/stylesheets/extra.css`, with a few small additions:

1. **Tokenize.** Refactor the top of `extra.css` into a clearly-organized token block (typography, color, spacing,
   radius, elevation, motion) for both `:root` and `[data-md-color-scheme="slate"]`. Migrate existing `--sase-*` names
   where compatible to minimize churn; keep aliases if any other CSS depends on them. Verify `pdf.css` still builds
   cleanly (it has its own scope).
2. **Fonts.** Add `@font-face` declarations for Inter (sans), Fraunces (display serif), and JetBrains Mono (mono) —
   either via Google Fonts CSS import in `extra_css` or self-hosted under `docs/assets/fonts/`. Wire `--font-sans`,
   `--font-serif`, `--font-mono` and apply to Material via `:root { --md-text-font: ...; --md-code-font: ...; }`.
3. **Homepage refinements.** Rewrite hero, section, card, split, primitive-list, image-grid, and actions blocks against
   the new token system. No markup changes to `index.md` should be required; if a tiny structural addition (e.g. a
   wrapper for the hero background) is necessary, it's allowed since markup tweaks aren't content changes — but prefer
   pure CSS.
4. **Doc page chrome.** Add a new section in `extra.css` targeting Material classes (`.md-typeset`,
   `.md-typeset h1..h6`, `.md-typeset code`, `.md-typeset pre`, `.md-typeset .admonition`, `.md-typeset table`,
   `.md-header`, `.md-tabs`, `.md-nav--secondary`, `.md-footer`). Keep the sidebar selectors from the prior pass intact;
   only adjust where necessary for token cohesion.
5. **Blog & series.** Add styles for `.md-post`, `.md-post__header`, `.md-post-action`, `.md-source-file`, blog index
   list items, and a small `.sase-series-table` style hook (target the existing markdown table with `:has()` + class
   context, or add a wrapper via `attr_list` on the table — pure CSS preferred).
6. **Footer.** Style `.md-footer`, `.md-footer-meta`, `.md-footer__inner` against the new tokens; ensure existing social
   icons inherit accent color on hover.
7. **Responsive pass.** Refine the existing `@media` breakpoints (82em, 76em, 60em, 34em) into a coherent system; add
   intermediate adjustments where the new typography scale needs them. Verify nothing horizontally overflows on
   320px-wide viewports.
8. **Accessibility & motion.** Add `prefers-reduced-motion` overrides; verify focus-visible rings exist on all
   interactive elements (buttons, cards-as-links if any, sidebar items); contrast-check both palettes.
9. **Verify build.** Run `just docs-check` (or whatever the docs target is — discover via `justfile`) and `just check`.
   Visually verify with `mkdocs serve` on:
   - homepage (light + dark, desktop + mobile)
   - one long doc page (e.g. `configuration.md`) including code blocks, admonitions, tables
   - blog index and the launch essay
   - series page
   - mobile drawer cohesion with the prior sidebar polish
10. **Self-review.** Diff `extra.css`; ensure no stray `!important`, no selector-specificity arms races, no JS added, no
    content/markup edits beyond optional minimal wrappers.

## Acceptance Criteria

- `sase.sh` looks deliberately designed on desktop **and** mobile, in **both** light and dark themes.
- Homepage hero, sections, cards, image grid, and CTAs feel cohesive, not bolted together.
- Doc pages have refined typography, code blocks, admonitions, tables, and footer.
- Blog index and post pages read editorially (display serif, refined date/category strip, comfortable measure).
- The previously-polished sidebar still works and visually coheres with the new chrome.
- No content, URL, nav-taxonomy, or build-pipeline changes; PDF build (`mkdocs-pdf.yml`, `pdf.css`) is unaffected.
- `just docs-check` (or equivalent) and `just check` pass.
- No JS framework, no Material theme replacement, no `!important`-heavy hacks.
- All interactive elements have visible `:focus-visible` styles; motion respects `prefers-reduced-motion`; body/heading
  text passes WCAG AA in both themes.

## Non-Goals

- Do not edit any `.md` content (copy, headings, links, frontmatter) — only minimal structural wrappers if absolutely
  required for a CSS hook.
- Do not change the navigation taxonomy, page URLs, or `mkdocs.yml` `nav` section.
- Do not introduce a JS framework, custom theme, or build step.
- Do not regress the prior `sase_sh_sidebar_polish` pass.
- Do not change the PDF/print pipeline.
- Do not redesign images or generate new artwork.

## Open Questions / Decisions Owned by Designer (me)

- **Serif display face**: Fraunces (variable, optical-size, warm modern) is the recommendation; Newsreader is the
  fallback if licensing/loading is an issue. Default to Fraunces unless the user objects.
- **Font hosting**: Google Fonts CDN for v1 (faster to ship, fewer files); migrate to self-hosted under
  `docs/assets/fonts/` as a follow-up if there are privacy/perf concerns.
- **Drop-cap on blog posts**: off by default, leave the CSS in place behind a class hook that any future post can opt
  into via `attr_list`.
- **Markup wrappers**: prefer pure CSS; if a single hero-background `<div>` is needed in `index.md` to avoid
  pseudo-element hacks, that's a one-line structural addition, not a content change.

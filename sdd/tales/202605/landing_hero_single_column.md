---
create_time: 2026-05-09 10:42:38
status: done
prompt: sdd/prompts/202605/landing_hero_single_column.md
---
# Landing Hero Single Column Plan

## Goal

Fix the `sase.sh` landing hero so the panel containing the SASE headline, intro copy, action buttons, and overview
diagram renders as one vertical composition instead of splitting into separate text and diagram columns.

The user's current symptom is that the live hero still behaves like a two-column layout: text on one side, the diagram
on the other. In the checked-in source, the current headline is already `Structured Agentic Software Engineering`, but
the same layout issue remains because the hero grid still allows multiple columns.

## Evidence

- `docs/index.md` defines the homepage hero as:
  - `.sase-hero`
  - `.sase-hero__copy`
  - `.sase-hero__visual`
- `docs/stylesheets/extra.css` currently sets:
  - `.sase-hero { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr)); }`
- That `auto-fit` grid is the direct cause of the two-column layout. Whenever the available panel width can fit two
  22rem tracks plus the gap, CSS creates two columns.
- The existing media queries reduce spacing and typography, but they do not remove the `auto-fit` behavior. The hero can
  still become two columns at desktop and at any intermediate content width wide enough to fit both tracks.
- The prior landing-hero polish plan already shortened the H1 and addressed word fragmentation. This request is
  narrower: force the hero panel itself into a single-column layout.

## Product Direction

Keep the existing MkDocs Material site and the current content. The hero should remain a compact, serious engineering
tool front door:

- Project signal and value proposition first.
- Action buttons immediately after the copy.
- Existing `docs/images/sase_overview.jpg` diagram still visible in the first hero panel, but below the text.
- No new framework, template override, generated image, nav change, or deployment change.

## Implementation Plan

1. Change the hero grid to a fixed single-column layout.
   - Replace the `repeat(auto-fit, minmax(...))` rule with `grid-template-columns: minmax(0, 1fr)`.
   - Keep `display: grid` because it still provides clean vertical layout and gap control.
   - Set `justify-items` or child widths intentionally so the copy and diagram do not stretch awkwardly.

2. Rebalance the copy width for a single-column hero.
   - Keep `.sase-hero__copy` readable with a max width around the existing 40rem.
   - Consider centering the copy only if it fits the existing visual language; otherwise keep it left-aligned and simply
     bound the line length.
   - Do not change the current H1 unless implementation testing shows it is necessary.

3. Rebalance the diagram as a supporting element below the text.
   - Give `.sase-hero__visual` a bounded width, likely wider than the copy but capped, so the diagram remains legible
     without becoming a full-width slab on very large screens.
   - Keep `object-fit: contain`, the existing border, and aspect ratio so the diagram stays inspectable.
   - Remove or reduce any hero `min-height` pressure that was only useful for the old side-by-side composition.

4. Simplify responsive overrides that only existed to rescue the two-column layout.
   - Keep useful padding and type-size adjustments.
   - Avoid contradictory breakpoint rules that make the single-column layout hard to reason about.
   - Ensure mobile rules still make buttons full-width and the hero fits within the viewport.

5. Verify both source and rendered behavior.
   - Run `just install` first if the workspace virtualenv is stale, per repo memory.
   - Run `just docs-check` to confirm the MkDocs site builds strictly.
   - Because this repo requires `just check` after file edits, run `just check` before finishing unless blocked by the
     environment.
   - If feasible, serve the docs locally with `python -m mkdocs serve -a 127.0.0.1:<port>` and inspect `/` at desktop,
     tablet, and mobile widths. The acceptance check is that `.sase-hero` has one grid column and the diagram appears
     below the copy at all tested widths.

## Expected Files

- `docs/stylesheets/extra.css`
  - Primary change: hero grid and supporting width/spacing rules.
- `docs/index.md`
  - No expected change unless verification shows a small copy adjustment is necessary.

## Risks

- A full-width diagram could become too visually dominant on wide desktop. Mitigate with a `max-width` on the figure or
  image.
- Centering the entire hero could make the page feel more like a marketing splash than a docs/product entry point. Keep
  text left-aligned unless visual inspection strongly favors centered alignment.
- Removing too much spacing could make the hero feel cramped on desktop. Preserve the existing panel treatment and use
  responsive padding rather than a broad redesign.

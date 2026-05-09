---
create_time: 2026-05-09 04:03:44
status: done
prompt: sdd/prompts/202605/landing_hero_text.md
---
# Landing Hero Text Polish Plan

## Goal

Fix the `sase.sh` landing-page hero so the headline and lead copy look intentional across desktop, tablet, and mobile
widths. The immediate issue shown in the Telegram screenshot is severe word fragmentation in the hero headline:
`Software engineering workflows for coding agents` is wrapping into short vertical chunks because the text column is too
narrow for the current large type treatment.

## Evidence

- The screenshot at `/home/bryan/.sase/telegram/images/20260509_080052_AgACAgEAAxkB.jpg` shows the homepage hero inside
  MkDocs Material with the left navigation/sidebar visible and the hero visual still occupying space to the right.
- `docs/index.md` renders a custom homepage hero with:
  - `.sase-hero__copy`
  - `.sase-home h1`
  - `.sase-lede`
  - `.sase-hero__visual`
- `docs/stylesheets/extra.css` sets the hero to two columns:
  - `grid-template-columns: minmax(0, 0.95fr) minmax(18rem, 1.05fr)`
  - `gap: 2rem`
  - `padding: 2.8rem`
  - H1 `max-width: 13ch`, `font-size: 3rem`, `line-height: 1`
- The mobile breakpoint collapses the hero at `max-width: 60em`, but the screenshot appears to hit an intermediate
  layout where MkDocs sidebars reduce the available article width while the hero still uses the desktop two-column
  composition.

## Product Direction

Keep the page within the existing MkDocs Material stack and preserve the current content model. This is a polish pass,
not a new landing page. The homepage should still feel like a serious engineering-tool front door with:

- SASE as the project signal.
- A concrete value proposition above the fold.
- Clear actions to the launch essay, ACE guide, series, and GitHub.
- Existing SASE visual assets as supporting material.

The fix should improve hierarchy and responsiveness without introducing a frontend framework, template override, or
broad Material theme rewrite.

## Implementation Plan

1. Tighten the hero copy itself.
   - Consider changing the H1 from `Software engineering workflows for coding agents` to a shorter, more brand-forward
     line such as `Structured Agentic Software Engineering`.
   - Move the current functional phrasing into the lead or a short subhead where wrapping is less damaging.
   - Keep the copy specific to orchestration, durable work, review, resumption, and provider portability.

2. Make the hero layout resilient before it becomes cramped.
   - Increase the collapse breakpoint for `.sase-hero` so it switches to a single-column layout before sidebars and the
     visual column force the copy into an unusable width.
   - Replace the current fragile column split with a layout that guarantees a readable text column, for example
     `minmax(min(100%, 24rem), 0.95fr)` for copy and a flexible visual column, or a simpler single-column layout at
     medium widths.
   - Reduce hero padding/gap at medium widths so the page does not waste the limited content width.

3. Make headline typography responsive by design, not by viewport accident.
   - Remove or relax the `13ch` H1 cap if it contributes to cramped wrapping.
   - Use a stable, bounded font size for the hero H1 at desktop and medium widths.
   - Ensure long words are not forced into letter-by-letter wrapping. Prefer normal word wrapping with enough column
     width over CSS emergency wrapping.

4. Rebalance the visual asset.
   - Keep `docs/images/sase_overview.jpg`, but allow it to drop below the copy earlier.
   - Consider reducing the visual's minimum width or using `object-fit: contain` instead of `cover` if the image is
     meant to communicate details rather than act as atmospheric media.
   - Preserve the current image as a first-viewport signal, but do not let it dominate at widths where copy readability
     is more important.

5. Verify across realistic MkDocs viewports.
   - Build or serve the docs locally.
   - Inspect desktop, tablet/sidebar, and mobile widths matching the screenshot conditions.
   - Confirm the H1 wraps into readable lines, buttons do not overflow, and the hero image remains visible without
     squeezing the text.
   - Check both light and dark modes if feasible.

## Expected Files

- `docs/index.md`
  - Possible small copy adjustment to the hero H1 and lead text.
- `docs/stylesheets/extra.css`
  - Hero grid, breakpoint, spacing, headline width, and image treatment changes.

No docs URL moves, nav changes, generated assets, or deployment configuration changes are needed for this request.

## Verification

Run the repo's docs and full checks after implementation:

```bash
just install
just docs-check
just check
```

If a local docs server is useful for visual inspection, run:

```bash
python -m mkdocs serve -a 127.0.0.1:8000
```

Then inspect `/` at desktop, tablet, and mobile widths. The acceptance bar is that the hero headline never breaks words
into fragments like `Softw / are / engin / eerin / g`, and the first viewport still communicates what SASE is and what
to click next.

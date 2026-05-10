---
create_time: 2026-05-09 20:08:01
status: done
prompt: sdd/prompts/202605/revert_sase_sh_styling.md
---
# Revert recent sase.sh styling while preserving desktop sidebar section emphasis

## Context

The recent `sase.sh` site styling work is concentrated in `docs/stylesheets/extra.css`, with one related PDF config
change in `mkdocs-pdf.yml`.

Relevant commits:

- `9840ae67 feat: cosmetic redesign for sase.sh`
  - Replaced the prior homepage-only CSS with a large site-wide visual system: Google font imports, new token names,
    Material chrome styling, global typography, code/admonition/table/footer/button/blog styles, animation/focus rules,
    and revised homepage styling.
  - Added `extra_css: []` to `mkdocs-pdf.yml`, apparently to keep the redesigned site CSS out of PDF builds.
- `1f34e792 feat: emphasize sidebar section labels on desktop docs`
  - Added a small, isolated desktop-only sidebar section treatment under `@media screen and (min-width: 76.25em)`.
  - This is the part the user wants to preserve for web. It currently depends on redesign-only tokens such as `--sp-5`,
    `--sp-3`, `--sp-2`, `--sase-rule`, `--sase-ink`, and `--font-sans`.

The safe target state is: restore the pre-`9840ae67` stylesheet behavior, then re-add the desktop sidebar section
emphasis with variables and spacing compatible with the older stylesheet. Keep the mobile sidebar untouched by retaining
the desktop-only media query.

## Implementation Plan

1. Restore the baseline CSS
   - Replace `docs/stylesheets/extra.css` with the version from `9840ae67^`.
   - This removes the broad redesign surface: font imports, global Material chrome, global body typography, code block
     restyling, table/admonition/footer/button/blog changes, hover animations, focus overrides, and the new token
     system.
   - This also restores the previous homepage styling that existed before the cosmetic redesign.

2. Reintroduce only the desired sidebar section emphasis
   - Add a small `Sidebar section emphasis (desktop)` block after the slate token definitions.
   - Preserve the behavior from `1f34e792`: section separators, uppercase section labels, a short accent rule before the
     label, distinct hover behavior for clickable vs non-clickable section labels, and active-section highlighting.
   - Adapt the block to pre-redesign tokens:
     - `var(--sase-border)` instead of `var(--sase-rule)`
     - `var(--sase-text)` instead of `var(--sase-ink)`
     - inherited Material/system font stack instead of `var(--font-sans)`
     - literal spacing values instead of `--sp-*`
   - Keep the query at `min-width: 76.25em` so mobile sidebar behavior remains unchanged.

3. Revert the PDF-only override if it was only compensating for the redesign
   - Remove `extra_css: []` from `mkdocs-pdf.yml`.
   - Rationale: once `extra.css` is back to the prior lightweight homepage/sidebar CSS, the PDF-specific suppression
     introduced with the redesign is no longer needed. If verification shows PDF build behavior depends on this
     override, revisit before finalizing.

4. Verify
   - Review the final diff to ensure only the broad redesign is gone and the adapted desktop sidebar section block is
     retained.
   - Run `just install` if needed for this workspace, then run `just check` per repo instructions.
   - If practical, run an MkDocs build command available in the repo environment to catch CSS/config syntax issues.
   - Report any verification command that cannot be run cleanly.

## Expected Files Changed

- `docs/stylesheets/extra.css`
- `mkdocs-pdf.yml`

## Non-goals

- Do not change `docs/index.md` or site navigation structure.
- Do not touch the SDD tale/prompt files from the earlier styling commits unless the user explicitly asks for historical
  artifact cleanup.
- Do not redesign the mobile sidebar; preserve existing Material/mobile behavior.

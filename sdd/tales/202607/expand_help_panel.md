---
create_time: 2026-07-07 13:46:29
status: done
prompt: sdd/prompts/202607/expand_help_panel.md
---
# Expand the Help Panel to Use Nearly the Full TUI

## Context

The merged Help panel now owns both keymap reference content and the per-tab guide. It currently uses a modal-sized
container rather than a near-fullscreen container:

- `HelpModal > Container` is `width: 90%`, `max-width: 150`, and `height: 85%`.
- The Help content is already contained in a `ContentSwitcher` with scrollable Keymaps and Guide views.
- The Keymaps tab renders fixed-width Rich boxes in two columns; the Guide tab uses reusable onboarding widgets that
  wrap to available width.
- Current visual coverage lives in `tests/ace/tui/visual/test_ace_png_snapshots_help_panel.py`.

The main source of unnecessary scrolling is the small outer geometry. At a 120x40 TUI, the Help panel gives up useful
columns and rows even though the content is informational and benefits from being read in-place.

## Goals

- Make the Help panel feel nearly fullscreen while still reading as a modal overlay.
- Reduce vertical scrolling in the Guide tab by adding rows and reducing avoidable line wrapping.
- Give the Keymaps tab enough horizontal space at normal terminal widths so its two fixed-width columns remain clean.
- Preserve existing Help behavior: `?` opens Keymaps, `[` / `]` switches Help tabs, app-tab switching refreshes the
  mounted Help content, and `Ctrl+D/U` scrolls the active view.
- Keep the change Help-specific; do not affect Config Center, other modals, keymap behavior, or onboarding widget
  content.

## Non-Goals

- Do not redesign the Help content hierarchy or rewrite onboarding widgets.
- Do not add new refresh paths, background work, disk reads, or subprocess work to modal handlers.
- Do not move any behavior into `sase-core`; this is presentation-only Textual layout work.
- Do not change the retired `,?` transition behavior.

## Proposed Design

Use the same near-fullscreen convention already present in other dense TUI surfaces, but apply it only to `HelpModal`:

- Change the Help container to roughly `98%` width and `96%` height.
- Remove the fixed `max-width: 150` cap so wide terminals actually reduce guide wrapping.
- Reduce Help container horizontal padding from `2` to `1` columns so the two fixed-width keymap columns can fit at
  common 120-column widths.
- Keep the existing centered overlay, tab-colored border, surface background, content switcher, stable scrollbars, and
  footer hints.
- Remove the explicit leading blank line from `_build_title()` and rely on container padding for top breathing room.
  This recovers one content row without changing the two-line title structure.
- Keep the footer visible. It is useful modal chrome, and hiding or making it conditional would complicate interaction
  for little gain.

Expected effect at 120x40:

- Outer Help width grows from about 108 columns to about 117 columns.
- Outer Help height grows from about 34 rows to about 38 rows.
- The scrollable content area gains several rows, and guide cards wrap less often.

## Implementation Steps

1. Update `src/sase/ace/tui/styles.tcss` only in the Help Modal Styling block:
   - Set `HelpModal > Container` to the near-fullscreen dimensions.
   - Remove the fixed width cap.
   - Tighten Help-only padding/margins as described above.

2. Update `src/sase/ace/tui/modals/help_modal/modal.py`:
   - Remove the leading newline from `_build_title()`.
   - Avoid changing bindings, refresh behavior, guide construction, or app-tab pass-through actions.

3. Update visual coverage:
   - Regenerate the Help panel PNG snapshots because the intentional geometry change will move borders and content.
   - Consider adding or renaming the Keymaps snapshot to cover a normal 120x40 viewport if the expanded panel now fits
     the two columns cleanly there; otherwise keep the existing 150x40 Keymaps snapshot and document that 120 columns is
     still a narrow edge case for two-column keymap boxes.
   - Keep Guide snapshots for PRs, Agents, and AXE at 120x40 because that is the most important scroll-reduction case.

4. Inspect the regenerated Help snapshots manually:
   - Verify the panel is almost fullscreen but still visibly modal.
   - Verify borders do not collide with the underlying app chrome.
   - Verify the title, tab strip, content, scrollbar, and footer do not overlap.
   - Verify Keymaps text does not wrap or clip poorly.

5. Run validation:
   - `just install`
   - Focused Help visual update, using the repo's snapshot update flag only for intentional Help PNG changes.
   - Focused Help tests.
   - `just test-visual`
   - `just check`

## Risks and Mitigations

- Risk: a 98% modal may feel too close to the screen edge on small terminals. Mitigation: keep the border, centered
  modal styling, and minimal padding so it remains readable and visibly distinct.

- Risk: removing `max-width: 150` could make the Help panel extremely wide on very large terminals. Mitigation: this
  matches the user goal of using nearly the whole TUI, and the content already centers or stretches within the available
  width. If visual inspection on a wide snapshot looks poor, add a high percentage cap rather than restoring the old
  fixed cap.

- Risk: Keymaps content is fixed-width and can still be tight at 120 columns. Mitigation: use horizontal padding `1`,
  verify the 120-column snapshot, and keep the 150-column snapshot if needed.

- Risk: visual snapshot churn may hide unrelated rendering regressions. Mitigation: update only Help panel goldens and
  run the full visual suite afterward.

## Acceptance Criteria

- Help panel uses almost the entire TUI at normal desktop terminal sizes.
- Guide tab shows materially more content before scrolling at 120x40.
- Keymaps and Guide tabs remain switchable by keyboard and mouse.
- App-tab switching while Help is open still refreshes title, accent border, keymaps, guide state, and footer.
- Help visual snapshots pass after intentional updates.
- `just check` passes after implementation.

---
create_time: 2026-06-27 10:20:37
status: done
prompt: sdd/prompts/202606/admin_center_title_5color_gradient.md
---
# Plan: 5-Color Aurora Gradient for the "SASE Admin Center" Title

## Goal

Make the "SASE Admin Center" modal header title (and its underline rule) more beautiful by extending its per-character
color gradient from 3 stops to 5 stops. Keep the existing aurora identity, preserve the panel-border tie-in, and ship a
smoother, richer color sweep.

## Product Context

The Admin Center modal (`sase ace`) opens with a centered, gradient-colored "SASE Admin Center" banner above a matching
heavy-rule underline. Today the gradient sweeps three cool stops — aqua → sky → violet — and the first stop also serves
as the modal's panel border color, so the leftmost title character and the frame agree. The title is a deliberate visual
tie-in to the colorful tab palette directly beneath it.

The request: add two more colors for a total of five, leading on the design so the result looks beautiful.

## Design Decision (chosen palette)

Keep all three existing stops and insert two new luminous stops into the two widest hue gaps, producing an even,
monotonic aurora sweep entirely in the cool half of the color wheel (aqua → cyan → sky → indigo → violet):

| #   | Hex       | Color               | Status                     |
| --- | --------- | ------------------- | -------------------------- |
| 1   | `#2BE7C7` | Aqua                | existing (= panel border)  |
| 2   | `#36CFEC` | Cyan                | NEW — fills aqua→sky gap   |
| 3   | `#4FB6FF` | Sky                 | existing                   |
| 4   | `#7E8BFF` | Periwinkle / indigo | NEW — fills sky→violet gap |
| 5   | `#B98CFF` | Violet              | existing                   |

Rationale:

- **Faithful to the ask.** All three original colors are retained; exactly two new colors are added (total of five).
- **Smooth and even.** Hues climb monotonically and roughly evenly (≈169° → 190° → 205° → 234° → 263°). The two inserts
  land in the two largest gaps of the original 3-stop ramp, so no single jump dominates.
- **Vivid, never muddy.** Every stop keeps a high blue channel, so the existing linear-RGB interpolation never passes
  through a desaturated gray midpoint; each character stays luminous on the dark surface.
- **Endpoints unchanged.** Stops 1 and 5 are identical to today, so the first and last characters render exactly as
  before. The leftmost character still matches the panel border (`#2BE7C7`) precisely — this is an enrichment of the
  middle of the sweep, not a jarring recolor.
- **Border tie-in preserved.** Because stop 1 is unchanged, the panel border needs no change and the documented "first
  stop == border" invariant holds.

## Technical Design

The gradient machinery is already N-stop generic, so this is primarily a data change plus snapshot regeneration.

### 1. Extend the gradient tuple (source change)

In `src/sase/ace/tui/modals/config_center_modal.py`:

- Update `_TITLE_GRADIENT` (currently `("#2BE7C7", "#4FB6FF", "#B98CFF")`) to the 5-stop tuple:
  `("#2BE7C7", "#36CFEC", "#4FB6FF", "#7E8BFF", "#B98CFF")`.
- Update the descriptive comment block above it so the prose matches the new five-color aurora sweep (aqua → cyan → sky
  → indigo → violet) while still noting that the first stop doubles as the panel border color.

No change is required to `_gradient_color()` or `_gradient_text()`: they already interpolate across an arbitrary-length
stop tuple via `len(stops) - 1` and `stops[index + 1]`. No CSS change is required (`styles.tcss` border stays
`#2BE7C7`).

### 2. Tests

- The existing unit test in `tests/ace/tui/test_config_center_tabs.py` only asserts the title text and underline length;
  it does not pin gradient colors or stop count, so it continues to pass unchanged. No new unit assertion is needed (the
  palette is presentation data, validated by the visual snapshots).
- Regenerate the affected PNG visual snapshots. The "SASE Admin Center" header appears in the Admin Center modal, so the
  `config_center_*` goldens under `tests/ace/tui/visual/snapshots/png/` (≈26 files) will pick up the new middle colors.
  Use the documented update flag rather than hand-editing PNGs:

  ```bash
  just test-visual --sase-update-visual-snapshots
  ```

  Then inspect the regenerated goldens (and/or the `.pytest_cache/sase-visual/` diff artifacts) to confirm the title now
  shows the intended five-band aurora sweep and nothing else changed, before staging them.

### 3. Validation

- Run `just check` (after `just install`, per the ephemeral-workspace rule) so lint, types, and the full test suite —
  including the regenerated visual snapshots — pass.
- Visually confirm the rendered title: cyan should appear between the aqua start and the sky-blue middle, and a
  periwinkle/indigo band between the sky-blue middle and the violet end, with the endpoints unchanged.

## Files Touched

- `src/sase/ace/tui/modals/config_center_modal.py` — extend `_TITLE_GRADIENT` to 5 stops; refresh its comment.
- `tests/ace/tui/visual/snapshots/png/config_center_*.png` — regenerated goldens (mechanical, via the update flag).

## Out of Scope / Non-Goals

- No change to the panel border color, the underline character, the tab palette, or any layout/CSS.
- No change to the gradient interpolation algorithm or the title/underline text.
- No new runtime configuration or theming knob — the palette stays a code-level constant, consistent with the current
  design.

## Risks & Notes

- Visual snapshot churn is expected and intended (≈26 `config_center_*` goldens). The change is otherwise low-risk: a
  5-element tuple swap plus a comment, with unchanged endpoints and border.

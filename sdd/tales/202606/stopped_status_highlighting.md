---
create_time: 2026-06-14 18:36:18
status: done
prompt: sdd/prompts/202606/stopped_status_highlighting.md
---
# Plan: Distinct, Beautiful Syntax Highlighting for the `STOPPED` Agent Status

## Problem

`STOPPED` is a recently-added terminal, non-error agent display status (a `%repeat` slot a predecessor's `STOP` output
skipped). It currently gets a distinct color in **exactly one** place — the Agents-tab list row — as flat neutral grey
`bold #9E9E9E`. Every other surface that can render an agent's status falls through to a generic default, so the same
status looks inconsistent (and visually mute/accidental) depending on where you see it. Since a `STOPPED` agent is
dismissable, savable into a group, jumpable, and zoomable, it actually appears in all of these surfaces.

We want `STOPPED` to have **one recognizable, beautiful, intentional visual identity that reads as "skipped / halted —
not success, not failure" everywhere it appears.**

## Audit: where an agent's `STOPPED` status can render

| #   | Surface                                                                  | File                                                             | Today's treatment for `STOPPED`                   |
| --- | ------------------------------------------------------------------------ | ---------------------------------------------------------------- | ------------------------------------------------- |
| 1   | Agents-tab list row                                                      | `src/sase/ace/tui/widgets/_agent_list_render_agent.py`           | `bold #9E9E9E` (only handled spot)                |
| 2   | Dismissed-agent revive modal (status label **and** leading status glyph) | `src/sase/ace/tui/modals/revive_agent_rendering.py`              | status → `"dim"`; glyph → `○` dim (falls through) |
| 3   | Saved agent-group revival modal (row + preview status counts)            | `src/sase/ace/tui/modals/saved_agent_group_revival_rendering.py` | `bold #AAAAAA` generic fallback                   |
| 4   | Jump-all cross-tab modal                                                 | `src/sase/ace/tui/modals/jump_all_modal.py`                      | `""` (unstyled, default fg)                       |
| 5   | Zoom panel modal status line                                             | `src/sase/ace/tui/modals/zoom_panel_modal.py`                    | `"bold"` (no color); icon `●`                     |

**Explicitly out of scope (different concept named "STOPPED"):** `keybinding_footer.py` and `_axe_dashboard_status.py`
use "STOPPED" for the **AXE daemon** running/stopped state, not an agent status. The query highlighter
(`query/highlighting.py`) styles `status:STOPPED` generically as a `property_value` and needs no per-status branch.
There are no nvim/vim syntax files in this repo, and `display_helpers.get_status_color` is ChangeSpec-only — none apply.

## Design

### Visual identity

- **Color:** `#8787AF` — a desaturated **slate blue-grey** (xterm-256 color 103). Rationale:
  - Reads as cool / dormant / "powered-down" — clearly neither success-green nor failure-red.
  - Stays on the codebase's xterm-256 status palette. The current `#9E9E9E` is a Material-grey outlier (not an xterm-256
    hue); `#8787AF` harmonizes with its siblings.
  - Distinct from the bright purples already in use (WAITING amethyst `#AF87FF`, LEGEND lavender `#D7AFFF`) by being far
    more desaturated and grey-dominant.
  - More intentional and "designed" than flat neutral grey, while still obviously muted.
  - _Conservative alternative if slate is unwanted at review:_ neutral `#878787` (xterm 102).
- **Glyph:** `⊘` (U+2298, CIRCLED DIVISION SLASH), rendered as a `⊘ ` prefix. Rationale: the codebase **already** uses
  exactly this glyph to mean "skipped" (`prompt_panel/_helpers.py` maps `"skipped" → ("⊘", "dim")`). Reusing it gives
  `STOPPED` an instantly-readable, semantically-correct identity and ties the new status to the established "skipped"
  vocabulary. It also mirrors the existing precedent of embedding a status glyph inline (`FAILED ↻ (RETRIED)`).
- **Weight:** `bold` in the dense list/label contexts to sit beside its terminal siblings; the modal preview contexts
  keep their lower-weight idiom but still use the slate color + glyph.

Net result, e.g. in the Agents list: `(⊘ STOPPED)` in slate blue-grey.

### Single source of truth

Add canonical constants next to the existing `STOPPED` predicates in `src/sase/ace/tui/models/agent_status.py`:

- `STOPPED_STATUS = "STOPPED"`
- `STOPPED_COLOR = "#8787AF"`
- `STOPPED_GLYPH = "⊘"` (`⊘`)

Every surface imports these instead of hardcoding, so the identity can never drift again. This is a light touch — it
centralizes only `STOPPED`'s identity and does **not** refactor the other per-surface status palettes.

## Implementation

1. **Canonical constants** — add `STOPPED_STATUS`/`STOPPED_COLOR`/`STOPPED_GLYPH` to `agent_status.py`.

2. **Agents-tab row** (`_agent_list_render_agent.py`) — replace the `#9E9E9E` branch with the canonical color and a `⊘ `
   glyph prefix (`⊘ STOPPED`).

3. **Revive modal** (`revive_agent_rendering.py`) — add `STOPPED` to `_STATUS_COLORS`, and add a `STOPPED` arm to the
   leading-glyph block so it shows `⊘` in slate (alongside DONE `✔` / FAILED `✘`) instead of the generic `○`.

4. **Saved-group modal** (`saved_agent_group_revival_rendering.py`) — add `STOPPED` to `_STATUS_COLORS` so row
   status-count chips and preview lines render in the canonical slate.

5. **Jump-all modal** (`jump_all_modal.py`) — add `STOPPED` to `_AGENT_STATUS_STYLES`.

6. **Zoom panel** (`zoom_panel_modal.py`) — add a `STOPPED` entry to the `_status_text` style map and use the `⊘` icon
   for it (instead of the inactive-default `●`).

No Rust / `sase-core` changes: this is presentation-only TUI styling, which the repo boundary keeps in Python. (The Rust
cleanup planner already learned `STOPPED` in the prior change.)

## Testing & verification

- **Unit/rendering tests:** assert each surface emits the canonical `STOPPED` style/glyph — extend
  `tests/ace/tui/models/test_agent_status_stopped.py` for the new constants, and add focused asserts for
  `revive_agent_rendering.get_status_style("STOPPED")` + leading glyph, the saved-group `_status_style("STOPPED")`, the
  jump-all agent-status mapping, and `zoom_panel._status_text("STOPPED")`.
- **Visual snapshot:** add a **new, dedicated** PNG snapshot (new fixture + golden, e.g. `agents_stopped_status_120x40`)
  that renders a `STOPPED` row next to DONE / FAILED / PLAN DONE so the new color + glyph are locked in and visually
  reviewable. Using a new snapshot (rather than mutating the existing `agents()` fixture) avoids perturbing the
  `agent_count == 3` assertions and existing goldens. Generate the golden with `--sase-update-visual-snapshots` for the
  new snapshot only.
- Run `just install` then `just check` (full lint + type + tests + visual suite) before finalizing.

## Risks / notes

- Slate-blue vs. amethyst proximity: mitigated by desaturation + the `⊘` glyph; the new dedicated snapshot makes the
  distinction reviewable at a glance.
- Keep the two daemon-`STOPPED` sites untouched to avoid conflating the two concepts.

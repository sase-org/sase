---
create_time: 2026-05-11 10:36:57
status: draft
prompt: sdd/prompts/202605/side_panel_selection_visibility.md
---

# Make the highlighted side-panel row clearly selected (without sacrificing readability)

## Problem

The previous pass dialed back the selection treatment too far. The highlight is now:

```tcss
background: $boost;
text-style: bold;
border-left: thick $accent;
padding: 0 1 0 0;
```

`$boost` is a very subtle Textual neutral (white-with-low-alpha overlay), so on the existing panel background the
selected row is only marginally different from its neighbors. The `thick $accent` left bar is the only strong cue and
it's only 1 column wide — at a glance it's easy to lose track of which row is selected, especially on the Agents and Axe
tabs where many similar rows stack.

The user wants the selection to be **immediately obvious** without going back to the saturated-blue background that
flattened the per-token foreground colors (status indicator color, mark green, hint yellow, CL-number blue, name teal).

## Goal

Make the highlighted row jump out on first glance while preserving the readability of every per-token color on that row.
The treatment should feel intentional and polished — not "louder for the sake of louder."

## Design exploration

The selected-row treatment has three "channels" we can pull on independently, each of which trades off readability vs.
visibility differently:

| Channel      | Visibility lift | Readability cost                                                          |
| ------------ | --------------- | ------------------------------------------------------------------------- |
| Background   | High            | High if saturated (fights fg colors); low if translucent/tinted           |
| Edge accent  | Medium          | Zero (lives outside text columns)                                         |
| Text style   | Low-medium      | Zero for `bold`, small for `underline` (can clash with fg color tokens)   |
| Prefix glyph | High            | Zero if added in CSS-only "padding char" form, but row helpers are scope- |
|              |                 | locked from the prior plan                                                |

CSS-only options that respect the existing scope boundary:

### Option A — Translucent accent tint + solid left bar (RECOMMENDED)

```tcss
background: $accent 25%;
text-style: bold;
border-left: thick $accent;
padding: 0 1 0 0;
```

- A 25% accent tint paints the whole row with a clear blue cast, but at 25% the foreground RGB still dominates — teal
  names, red/orange/yellow status suffixes, green checkmark, yellow hints all stay legible.
- The solid `thick $accent` left bar at full saturation anchors the selection visually so even users on monitors that
  flatten subtle tints (cheap LCDs, projectors) see it.
- Bold continues to add typographic weight.
- Net effect: the selected row reads as "selected" from across the room, and the per-token information channel is
  preserved.

### Option B — Double-edge frame

```tcss
background: $boost;
text-style: bold;
border-left: thick $accent;
border-right: thick $accent;
padding: 0 0;
```

- Brackets the row with accent bars on both sides — extremely unambiguous.
- Tradeoffs: the right bar fights the `scrollbar-gutter: stable` reserved column on lists that ever scroll (looks
  slightly off when the scrollbar is absent), and we lose both side-padding columns, so text sits flush against the
  bars. On narrow panes this can feel cramped.

### Option C — Brighter bar + underline emphasis

```tcss
background: $accent 15%;
text-style: bold underline;
border-left: outer $accent;
padding: 0 1 0 0;
```

- `outer` border draws a glow-like edge instead of a solid bar; `underline` adds a horizontal accent under every glyph.
- Underline can visually merge with the colored status-suffix and hint tokens, slightly muddying them. Rejected
  primarily on readability grounds.

### Why Option A wins

- It's the only option that adds a **second strong visual channel** (translucent fill across the row) without taxing the
  per-token foreground colors. Option B's second channel is the right bar, which interacts awkwardly with the scrollbar
  gutter. Option C's second channel is underline, which interferes with the colored suffix tokens.
- It composes naturally with the existing solid left bar — the bar at full saturation rides on top of the row tint,
  giving the row both a "fill" cue and an "edge" cue.
- All three side-panel widgets share the rule, so the consistency story stays clean.

## Scope

- **In scope**: the three `.option-list--option-highlighted` blocks in `styles.tcss` (lines 133, 992, 1356).
- **In scope**: regenerating any visual snapshot PNG whose pixels shift as a result.
- **Out of scope**: row-rendering helpers, the detail panel, the right-side widgets, any keymap or behavior change.

## Files involved

| File                                  | Role                                                                   |
| ------------------------------------- | ---------------------------------------------------------------------- |
| `src/sase/ace/tui/styles.tcss`        | Three highlight rules (lines 133-138, 992-997, 1356-1361)              |
| `tests/ace/tui/visual/snapshots/png/` | Regenerated goldens for the four snapshots that show a highlighted row |

Snapshots expected to regenerate (no test code changes):

- `changespec_initial_120x40.png`
- `changespec_selected_row_120x40.png`
- `agents_list_120x40.png`
- `agents_selected_row_120x40.png`
- `axe_selected_row_120x40.png`

`query_edit_modal_120x40.png` is unaffected (modal, not a side-panel list).

## Step-by-step

1. `just install` in the current workspace.
2. Edit `src/sase/ace/tui/styles.tcss`: in each of the three highlight blocks, replace `background: $boost;` with
   `background: $accent 25%;`. Leave `text-style: bold;`, `border-left: thick $accent;`, and `padding: 0 1 0 0;` as-is.
3. Run `pytest --sase-update-visual-snapshots tests/ace/tui/visual/test_ace_png_snapshots.py -m visual` to regenerate
   the affected PNG goldens.
4. Open the five regenerated PNGs and confirm: (a) the selected row is unambiguously selected, (b) all per-token colors
   on the selected row are still readable.
5. Re-run the visual suite without `--update` to confirm stability.
6. `just check`.
7. Report changed files, the visual delta, and any goldens that shifted.

## Open decisions

- **Tint strength**: 25% is the proposed starting point. If on inspection the tint feels too strong (text colors start
  to "cool down"), step down to 20%. If too subtle on the user's monitor, step up to 30%. This is an inspection-time
  adjustment, not a re-plan.
- **Bar weight**: `thick` (default) stays. `outer` was considered but its glow effect is too soft for the goal.

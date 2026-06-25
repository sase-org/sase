---
create_time: 2026-06-25 19:07:58
status: done
---
# Plan: Command Palette — Live Entry Count + Position Indicator

## Goal

When the `sase ace` command palette (`:`) is open, the user currently has no idea how big the command list is or where
their cursor sits within it. Add two coordinated, always-live readouts:

1. **How many entries** the palette currently holds (and, when filtering, how many of the grand total match).
2. **Which entry we are on** — a position indicator (the `[5/72]` ask), redesigned to look beautiful and to read at a
   glance.

I'm leading the design here. The guiding principle is a clean split of the two facts across the two chrome rows the
palette already has, reusing color/idiom conventions already established elsewhere in the TUI so the result feels native
rather than bolted-on.

## Information architecture (the design decision)

The palette already has a centered **title row** and a centered **footer hint row**. Rather than cram both numbers into
one `[5/72]` blob, split them so each row answers one question:

- **Title row → "how many?"** Mirror the existing `ProjectSelectModal` live-count idiom
  (`✦ Select Project or PR · N matches`, styled `dim #87D7FF`). The palette title gains a live count that reflects
  filtering.
- **Footer row → "where am I?"** Turn the footer into a two-zone status bar: keyboard hints on the left (kept), and a
  right-aligned **position indicator** — the redesigned `[5/72]`.

Both update live on every keystroke and every cursor move. This separation means the denominators never fight each
other: the title's denominator is the grand total of commands; the footer's denominator is the number of rows currently
shown.

### Visual mockups

Unfiltered (72 commands available, cursor on row 5):

```
            ✦ Command Palette   [Agents]   ·   72 commands

  ┌ Type a command... ─────────────────────────────────────────────┐
  │ ▏                                                               │
  └─────────────────────────────────────────────────────────────────┘
   Search command text, or use key:<key> for keymaps …

  ┌─────────────────────────────────────────────────────────────────┐
  │ %n        New agent                         [agents]            │
  │ …                                                                │
  └─────────────────────────────────────────────────────────────────┘

   ↵ run · esc close · ↑↓ move                     ━━●━━━━━━━  5/72
```

Filtered to `git` (12 of the 72 match, cursor on the 1st):

```
            ✦ Command Palette   [Agents]   ·   12 of 72 commands
   …
   ↵ run · esc close · ↑↓ move                     ●━━━━━━━━━  1/12
```

### The redesigned indicator — why it's "better" than `[5/72]`

Three deliberate upgrades over a plain bracketed number:

1. **A subtle position gauge** (`━━●━━━━━━━`): a ~9-cell slider whose knob (`●`) tracks the cursor's fractional position
   in the list. This adds _spatial_ meaning a bare `[5/72]` lacks — you can feel "near the top / middle / bottom"
   without parsing digits. It is distinct from the OptionList scrollbar (which tracks scroll, and vanishes for short
   lists); the gauge is always present and always reflects the highlighted row.
2. **Color hierarchy instead of brackets**: the current position renders **bold in the tab's accent color** (reusing the
   exact `_TAB_BADGE` accent — `#00D7AF` PRs / `#87D7FF` Agents / `#FFD700` AXE), the `/` and total render muted/dim.
   This ties the indicator to the palette's per-tab identity and draws the eye to the number that changes.
3. **Right-aligned in a real status bar**, the idiomatic fuzzy-finder location (fzf / telescope), balanced against the
   left-aligned hints.

Numbers are **1-based** for display (`5/72`, not `4/72`).

## Files to change

### 1. `src/sase/ace/tui/modals/command_palette_modal.py`

- **Pure render helpers** (module-level, easily unit-tested in isolation):
  - `_build_count_text(shown: int, total: int) -> Text` — `"72 commands"` when `shown == total`, `"12 of 72 commands"`
    when filtered, correct singular ("1 command"). Styled `dim #87D7FF` to match `ProjectSelectModal`.
  - `_render_gauge(position: int, total: int, width: int) -> tuple[str, int]` (or returns the cell string + knob index)
    — pure math mapping `(position, total)` to a knob cell.
  - `_build_position_text(position: int, total: int, accent: str) -> Text` — assembles gauge + styled `pos/total`.
- **`_build_title()`**: accept/derive the shown + grand-total counts and append the count segment after the existing tab
  badge (same `· …` separator style as `ProjectSelectModal`).
- **New `_refresh_status()`** method that recomputes position + counts from `self._filtered_specs`, `self._all_specs`,
  and `option_list.highlighted`, then updates the title, the count, and the footer position Statics. Single source of
  truth for all three readouts.
- **Call sites for `_refresh_status()`**:
  - end of `on_mount()` (initial render),
  - end of `_apply_filter()` (after the list is rebuilt and highlight reset),
  - a new `on_option_list_option_highlighted(event)` handler (cursor moves) — this is the canonical Textual hook already
    used by `prompt_history_modal`, `task_queue_modal`, and `tag_input_modal`.
- **`compose()`**: replace the single footer `Static` with a `Horizontal` status bar containing two Statics:
  `#command-palette-hints` (existing hint text, polished to `↵ run · esc close · ↑↓ move`) and
  `#command-palette-position` (right-aligned indicator). The title Static keeps its id; its count segment is updated in
  place.
- **Edge cases** (all handled in `_refresh_status` / helpers):
  - 0 matches → title `0 of 72 commands`; position zone shows a muted `0/0` with an empty gauge (the list area already
    shows the "No matching commands" empty state).
  - `highlighted is None` while specs exist → default position to 1 (matches the existing enter-fallback in
    `_submit_highlighted`).
  - single item → `1/1`, knob pinned to the start of the gauge.
  - long key labels etc. are unaffected (separate column logic).

### 2. `src/sase/ace/tui/styles.tcss` (`Command Palette Modal Styling` block ~L3835)

- Replace the single `#command-palette-footer` rule with a status-bar layout: the footer container is
  `layout: horizontal; height: 1; margin-top: 1`, `#command-palette-hints` is `width: 1fr` left,
  `#command-palette-position` is `width: auto; text-align: right` muted. Keep colors driven by the Rich `Text` styles
  for the accented number; CSS supplies the muted baseline + alignment.

### 3. Tests

- **Unit (`tests/test_command_palette_modal.py`)** — extend with:
  - `_render_gauge` math: top/middle/bottom knob placement, `total == 1`, `total == 0`, `position` clamped in range,
    knob index within `[0, width)`.
  - `_build_count_text`: singular/plural, unfiltered (`N commands`) vs filtered (`M of N commands`).
  - `_build_position_text`: contains the `pos/total` substring and uses the accent style.
  - Async modal tests (mirror existing `test_modal_*` patterns): position updates after a down-arrow / `ctrl+n`; count
    switches to the `M of N` form after typing a filter; empty filter shows `0/0` and the empty state. Assert on the
    rendered Static text/`renderable`.
- **Visual PNG snapshot (new file `tests/ace/tui/visual/test_ace_png_snapshots_command_palette.py`)** — there is
  currently **no** visual snapshot for the palette. Add one that opens `CommandPaletteModal` with a deterministic spec
  list (construct `CommandSpec`s directly, no live registry) and locks in the beautiful layout: title with count, footer
  status bar with gauge + accented position. Mirror the structure of `test_ace_png_snapshots_project_select.py`.
  Generate the golden with `--sase-update-visual-snapshots` and commit it under `tests/ace/tui/visual/snapshots/png/`.

## Backend boundary

This is presentation-only Textual state: computing a 1-based position/total and rendering Rich `Text` + CSS. By the
`rust_core_backend_boundary` litmus, no other frontend needs this behavior to match the TUI — it stays entirely in
Python. No `sase-core` / `sase_core_rs` changes.

## Verification

- `just install` then `just check` (lint + mypy + fast tests).
- `just test-visual` to validate the new PNG golden.
- Confirm no existing test asserts the old footer literal (`"Enter run · Esc close · ↑/↓ move"`) — current grep shows
  only the source defines it, so the wording change is safe.
- Sanity-check the help popup: this adds no new keybinding or option (purely a passive display enhancement), so the `?`
  help content should not need changes — verify the palette isn't described in a way that becomes stale, and leave it
  untouched if not.

## Out of scope

- No new keybindings, config options, or behavior changes to filtering/navigation/selection.
- No change to which commands appear or their ordering.
- Not making the gauge interactive (e.g. click-to-jump) — it is a passive readout.

## Design rationale & alternatives (for reviewer)

- **Why split across title + footer** rather than one `[5/72]`: it lets the count denominator be the true grand total
  while the position denominator is the shown count, with zero ambiguity, and reuses two idioms already in the codebase
  (`ProjectSelectModal` count, `zoom_panel_modal` `pos/total`).
- **The gauge is the one stylistic call worth flagging.** I recommend keeping it — it's the strongest "better than
  `[5/72]`" element and reads beautifully. If you'd prefer maximum minimalism, the fallback is the same accented `5/72`
  with the gauge omitted; the `_render_gauge` helper just wouldn't be called. Everything else in the plan is unchanged
  either way.

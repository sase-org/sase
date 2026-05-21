---
create_time: 2026-05-21 11:20:05
status: done
prompt: sdd/prompts/202605/footer_overflow.md
---
# TUI Footer Overflow Redesign

## Problem

The keybinding footer (`src/sase/ace/tui/widgets/keybinding_footer.py`) currently renders bindings as a single Rich
`Text` blob separated by two spaces and lets Textual's default wrapping do the work. When the terminal is narrow or the
binding list is long (e.g. LEADER mode with ~15+ entries), the result is ugly:

- Wrap points fall in arbitrary places — labels sometimes break away from their key, and the visual rhythm of
  `key⎵label  key⎵label` is impossible to scan once a line wraps. `r  runners (3)` and `M  mail` blur into one another.
- The mode prefix (`LEADER`, `FOLD`, `BANG`, `COPY`, `JUMP`) is plain bold gold inline text that flows together with the
  bindings, so on overflow the prefix word can end up indistinguishable from a binding label.
- The CSS clamps `max-height: 5`. Anything past five wrapped lines is silently clipped — that is, _today the footer
  already truncates_ in LEADER mode on narrow widths, despite the user-visible goal that all keymaps remain visible.
- The status indicator (`STARTING`, `RUNNING`, etc.) sits on the right of the flex row. When bindings wrap, the
  relationship between status and the first line of bindings is still fine, but the layout has no visual frame to anchor
  status against multi-line content — it just floats next to the top row.

## Goals

1. **Show every binding.** Never drop, truncate, or clip a keymap, regardless of terminal width.
2. **Atomic key+label pairs.** A `key label` pair must never split across a wrap boundary.
3. **Make multi-line look intentional.** When overflow happens, the layout should look like a deliberate grid, not a
   paragraph of wrapped text.
4. **Preserve glanceability.** Single-line case (the common one on wide terminals) should remain calm and uncluttered —
   no new chrome that taxes wide-terminal users for the sake of narrow ones.
5. **Keep mode prefixes loud.** `LEADER`, `FOLD`, etc. should read as a clearly delineated mode badge, not as another
   binding.

## Design

### Core idea: atomic chips on a soft-aligned grid

Each binding becomes a **chip** — a non-breaking `key⎵label` unit. Chips are laid out with a thin separator between
them; when the row runs out of room, chips flow to the next line, never split. When the footer is in multi-line mode,
chips are padded to a common column width so wrapped lines align into a visual grid.

#### Single-line mode (fits on one row)

Visual: essentially today's look, with two refinements.

```
 LEADER   a accept · d diff · w reword · M mail · r rebase                  STARTING
```

- `LEADER ` rendered as a **pill badge**: `bold black on #FFD700` with one space of padding on each side (`LEADER`).
  Today's `bold #FFD700` text-only prefix is too easy to read as another binding label; the filled background pulls it
  out of the binding flow.
- Chip separator changes from `  ` (two spaces) to `·` (space + middle dot
  - space) styled `dim`. Middle dot is a well-established CLI separator and makes binding boundaries visually obvious
    without adding noise. (Plain spaces look fine in isolation but read as ambient padding once a row wraps.)
- Chip content unchanged: key in `bold #00D7AF`, label in `dim`.
- Status indicator stays as-is in the right column.

#### Multi-line mode (overflow)

When the chip row would exceed the available content width, switch to grid layout: each chip is padded to
`max(chip_width)` + 2 spaces, chips flow left-to-right into a fixed number of columns, wrapping into N rows. The mode
badge anchors the **top-left** of the grid.

```
 LEADER
 . repeat            a agent (home)      A run agent (CL)    g group panels        STARTING
 G full history      n next stopped      N next unread done  R mark all read
 p prompt history    P edit history      ^P history (+canc)  k kill & edit
 r retry (edit)      C capture repro     X repro checks      q task queue
 i activity          o temporary model   m mark idle
```

- Mode badge sits on its own line at the top-left, leaving the right column free for the status indicator on the same
  line. Visually anchors the whole block.
- Chips are padded to common width so each column is straight. Reading down any column is as easy as reading across.
- The number of columns is derived from `floor(content_width / cell_width)`, with a minimum of 1. Rows =
  `ceil(n_chips / cols)`.
- Status indicator stays anchored to the top-right of the footer, opposite the mode badge. (No status indicator? Mode
  badge alone on its row.)
- If there is no mode (e.g. the plain CL or Agents tab footer overflows), the grid starts at the top-left from the first
  chip; no badge line is rendered.

#### Switching between modes

Detection lives inside the footer: after building the chip list, measure the single-line render width against the cached
`self.size.width` (Textual provides this on the widget). If `single_line_width <= available_width`, render inline;
otherwise render grid. The decision is recomputed on every `_update_display` and on `on_resize` (a new hook the widget
gains).

### Styling refinements

- Footer gains a thin top border: `border-top: hkey $panel-lighten-2;` — separates footer from the main scroll area
  without adding mass. This is a small but high-impact change; today the footer blends into the bottom of the list.
- `max-height` lifted from `5` to `none`. The footer grows as needed. `min-height: 1` (was 3) so single-line case can
  shrink to one row when there are zero bindings (e.g. empty state with no project filter). Avoids the current dead
  2-line padding on the empty-state footer.
- `padding: 0 1` unchanged.

### Implementation surface

Files to touch:

1. **`src/sase/ace/tui/widgets/_keybinding_bindings.py`**
   - Replace `_format_bindings` with two formatters:
     - `_format_bindings_inline(bindings) -> Text` — chips joined with `·`.
     - `_format_bindings_grid(bindings, *, columns: int) -> Text` — chips padded to common width, joined with column
       padding, broken into rows with `\n`.
   - Add `_chip_text(key, label) -> Text` — single chip with `no_wrap=True` so Rich never splits a chip even if we fall
     back to its wrapping.
   - Add `_chip_plain_width(key, label) -> int` — for column-width math.

2. **`src/sase/ace/tui/widgets/keybinding_footer.py`**
   - Add `_render_mode_badge(label: str) -> Text` — returns `bold black on #FFD700` text `{label}`. Replaces inline
     `prefix.append("FOOBAR ", style="bold #FFD700")` at the 5 call sites (FOLD, JUMP, LEADER, BANG, COPY, custom).
   - Refactor `_update_display` to accept `(bindings: list[tuple[str,str]], mode_label: str | None)` instead of
     pre-built `Text`. The widget owns the layout decision; callers stop building `Text` themselves. Every
     `update_*_bindings` method changes shape: build the bindings list, build the optional mode label, hand both to
     `_update_display`. Simpler and deletes the repeated `prefix = Text(); prefix.append(...); prefix.append_text(text)`
     boilerplate at 5 sites.
   - Layout-decision helper `_layout(bindings, mode_label) -> Text`:
     - Compute single-line width including the badge.
     - If `<= self.size.width - status_width - 2`, return inline form.
     - Else compute columns from `cell_width = max(chip plain widths) + 2`,
       `columns = max(1, (available - 1) // cell_width)`, and return grid form with the badge on its own line.
   - `on_resize` handler: recompute the last-rendered display when width changes. (Cheap — same signature-cache trick
     already in place will skip repaints when nothing actually changes.)

3. **`src/sase/ace/tui/styles.tcss`**
   - `#keybinding-footer`: drop `min-height: 3` → `min-height: 1`, drop `max-height: 5`, add
     `border-top: hkey $panel-lighten-2;`.
   - `#keybinding-content` and `#keybinding-status` unchanged.

4. **Tests**
   - Extend `tests/test_keybinding_footer_core.py` and the agent/workflow variants with parametric cases asserting:
     - Chip ordering preserved (existing sort logic survives).
     - Inline form contains `·` between chips.
     - Grid form is produced when synthetic width is too narrow.
     - No chip is ever split across a `\n`.
     - Mode badge text is present exactly once and styled with the gold background span.
   - Update existing tests that match on `"  "` between bindings — change to `" · "`.
   - Visual snapshots: add two new PNG snapshots to `tests/ace/tui/visual/snapshots/png/`:
     - `footer_leader_overflow_120x40.png` — LEADER mode at standard width, confirms grid layout.
     - `footer_leader_overflow_80x30.png` — same content at narrow width, more columns drop.
   - Re-run any existing snapshots that include the footer; they will need refresh because the separator changed and the
     top border is new. These are intentional visual changes.

### Edge cases

- **Empty bindings.** Inline form with just the status indicator (or badge + status if a mode is active with no
  bindings).
- **Single very long label.** One chip wider than the terminal: fall back to inline render and let Rich wrap that single
  chip on a space inside the label. We do not try to truncate.
- **Status indicator absent.** `_get_status_text` always returns something during normal operation (startup stopwatch or
  AXE state), so practically this is a non-issue, but the grid math should treat status width as 0 when the status
  widget is empty.
- **Width unknown at first render.** `self.size.width` may be 0 before mount. Default to inline mode when width is
  unknown; resize handler will upgrade to grid once Textual reports the real size.
- **`bgcmd` badges in status column.** Status column can grow up to ~20 chars (`STARTING 12.3s [*3] [✓5]`). Subtract its
  actual rendered width from the budget when deciding inline-vs-grid.

### Non-goals

- No new keybindings, no help-modal changes (those rules in `AGENTS.md` about `?` popup don't apply — we're not changing
  options).
- No restructuring of the binding-list computation (`_compute_*_bindings` methods stay byte-identical).
- No theming/skinning system — colors stay as direct hex literals consistent with the rest of the file.

## Risks and tradeoffs

- **Visual change to every footer render.** Snapshot churn is unavoidable. The middle-dot separator and the top border
  affect every PNG that includes the footer (most of them). Calling this out so it's an expected side-effect, not a
  regression to chase.
- **Grid layout math is fragile under proportional fonts / emoji width.** We're using monospace fixtures in tests (Fira
  Code), and chip labels are plain ASCII today, but keys can contain `<enter>` etc. Use `rich.cells.cell_len` for width
  math, not `len()`, to handle the occasional wide-char case.
- **Resize churn.** A user grabbing the terminal corner and dragging will fire many resize events. The existing
  signature cache prevents repaints when the rendered output is unchanged, and the layout decision is cheap (one width
  comparison), so this should be a non-issue. If it surfaces as a problem, debounce in `on_resize` with a 50ms timer.

## Rollout

Single commit / PR. Snapshot updates included. No feature flag — this is a pure visual upgrade that should land
everywhere immediately.

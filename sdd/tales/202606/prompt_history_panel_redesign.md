---
create_time: 2026-06-13 13:36:04
status: done
prompt: sdd/prompts/202606/prompt_history_panel_redesign.md
---
# Plan: Make the prompt-history modal near-fullscreen and beautify the list pane

## Goal / product context

The `sase ace` **prompt history modal** (`PromptHistoryModal`) is the surface for finding and re-running a past prompt.
Today it opens at `90% × 80%` of the terminal and splits its space 50/50 between a left **list pane** (the filterable
`OptionList` of past prompts) and a right **preview pane**.

The user wants two things:

1. **Make the modal almost fill the screen** — it currently leaves a wide margin and feels cramped for a surface you
   scan through thousands of prompts in.
2. **Make the list pane look much nicer** — lead the design, make it beautiful.

We recently landed structured per-row metadata (project / xprompt chips / directive token / cleaned preview — see
`sdd/tales/202606/prompt_history_metadata.md`). That work gave each row real columns, but the rows are still rendered on
a default-styled `OptionList` inside a half-width pane: the selected row uses Textual's plain default highlight
(inconsistent with the rest of the app), the columns don't form a clean aligned grid, the previews are hard-capped at 96
characters so they leave dead space in a wide pane, and there is no column header or sense of the list's scale. This
plan turns that list into a polished, full-bleed, gridded table that is a pleasure to scan.

This is **presentation-only** work (Textual layout, CSS, Rich `Text` rendering) — no Rust core change, no persisted
schema change, no parsing-grammar change. It builds directly on the existing `sase.history.prompt_metadata` helpers.

## Current behavior (files)

- `src/sase/ace/tui/styles.tcss` (≈1274–1350) — modal CSS. Container `90% × 80%`; list pane and preview pane each
  `width: 1fr`; the `OptionList` has only `height: 1fr; border: solid $secondary` and **no** highlight/option styling,
  so it falls back to Textual's default cursor highlight (unlike `AgentList` / `ChangeSpecList`, which style
  `.option-list--option-highlighted` with an accent background + thick accent left border).
- `src/sase/ace/tui/modals/prompt_history_modal.py`
  - `_create_prompt_history_label()` renders each row:
    `marker(2) + timestamp(11) + "  " + project(12) + "  " + tags(variable) + preview`. The preview is hard-truncated to
    `_PROMPT_PREVIEW_WIDTH = 96` by `_ellipsize_right`.
  - The **tags column is variable-width**, so the preview column starts at a different x on every row — there is no
    stable grid.
  - `compose()` lays out a `Label("History")` above the `OptionList` in the list pane, and `Label("Preview")` above the
    preview scroll.
  - `_create_options()` rebuilds an `Option` per filtered item; called on every keystroke in `on_input_changed()` and on
    `Ctrl+X` toggle. Per-row metadata is cached on `_PromptDisplayItem.summary` (parsed once per item).
- `src/sase/history/prompt_metadata.py` — `summarize_prompt_for_list()` / `summarize_prompt_for_preview()` and the
  `PromptListSummary` / `PromptPreviewSummary` dataclasses. **Reused as-is; no changes expected.**

## Design (the important part — must look beautiful)

### 1. Size: near-fullscreen modal

Bump `PromptHistoryModal > Container` from `90% × 80%` to **`98% × 96%`**, keeping `align: center middle` and the
existing `border: thick $primary`. The thin remaining margin lets the thick primary border read as a deliberate frame
rather than the modal touching every edge.

### 2. Proportions: give the list pane the lead role

The list is the primary surface and the focus of this request. Change the split from `1fr / 1fr` to **list `3fr` /
preview `2fr`** (≈60/40). The wide list is what lets cleaned previews finally breathe; the preview pane stays
comfortably readable at 40%. (Ratio is tunable against the snapshot.)

### 3. List pane: a clean, aligned, full-bleed table

The core visual idea: turn the rows into a **fixed-column grid with an aligned header**, styled with the app's own
highlight idiom, so every column lines up vertically and only the final preview column is ever ellipsized.

**a. Fixed-width columns (resolves grid alignment).** Today the tags column is variable-width, which means the preview
starts at a ragged x and no header could ever align. Make **every column except the preview fixed-width** so the grid is
perfectly vertical:

```
   WHEN          PROJECT        TAGS              PROMPT
 ──────────────────────────────────────────────────────────────────────────────────────
   06-13 14:30   gh:sase        #fork %amp        Fix the parser bug so it handles edge cases…
   06-13 09:15   git:home                         Refactor the workspace loader for clarity an…
   06-13 08:02   gh:beads       #research         Investigate the failing CI on the beads br…
   06-13 07:40   —                                Quick note without any project tag at all he…
 x 06-12 22:10   gh:sase        %m                try the experimental model on this one pleas…
```

Columns, left → right (all fixed except the last):

1. **marker** (2) — `x ` magenta for cancelled, else two spaces (unchanged).
2. **WHEN** (11) — `MM-DD HH:MM`, `dim` (unchanged content).
3. **PROJECT** (~14, slightly wider than today's 12 for breathing room) — `<wf>:` `dim` + ref basename in `cyan`; `—`
   placeholder in `dim` when absent.
4. **TAGS** (fixed, ~16) — xprompt chips (`green`) then the collapsed directive token (`yellow`), truncated to the
   column with a trailing `+N`/`…` on overflow. **Fixed width is the change** — it reserves space even when empty so the
   preview always starts at the same x.
5. **PROMPT** (fills the rest, `no_wrap`, `overflow="ellipsis"`) — the cleaned first-line preview.

**b. Adaptive preview width (use the new space).** Replace the hard `_PROMPT_PREVIEW_WIDTH = 96` cap with a budget
computed **once per option-list rebuild** from the actual list width
(`max(_MIN_PREVIEW_WIDTH, list_content_width − fixed_columns_width)`), with a generous constant fallback when the widget
isn't laid out yet (initial compose). This keeps the guaranteed trailing ellipsis while letting previews fill the
now-much-wider pane instead of stopping at 96 chars. The computation is O(1) per rebuild (not per row), so it adds
nothing to the keystroke hot path.

**c. App-consistent highlight + list chrome.** Add the missing `OptionList` styling so the selected row matches
`AgentList`/`ChangeSpecList`:

```
PromptHistoryModal OptionList { scrollbar-gutter: stable; }
PromptHistoryModal OptionList > .option-list--option { padding: 0 1; }
PromptHistoryModal OptionList > .option-list--option-highlighted {
    background: $accent 40%;
    text-style: bold;
    border-left: thick $accent;
    padding: 0 1 0 0;
}
```

`scrollbar-gutter: stable` keeps columns from shifting when the scrollbar appears.

**d. Aligned column header.** Add a header row (a `Static`) above the `OptionList` that prints the column titles
(`WHEN`, `PROJECT`, `TAGS`, `PROMPT`) in `bold`/`$text-muted`, built with the **exact same fixed column widths** as the
rows (and the same left inset, accounting for the option `padding`), with a full-width divider rule beneath it (via a
`border-bottom` on the header so it always spans the pane). Because the data columns are now fixed-width (3a), the
header lines up perfectly above them.

**e. Scale/feedback in the pane title.** Repurpose the static `Label("History")` into a live count:
`History · <filtered> / <total>` (e.g. `History · 1,234 / 9,104`), updated on filter change and on the cancelled toggle.
Cheap (one label update), and it gives the now-large list a sense of scale and immediate filter feedback.

**f. Cancelled rows** keep the established treatment — `x` marker in `magenta`, the rest of the row `dim italic` so it
recedes — applied over the new grid and highlight.

### 4. Preview pane (light cohesion pass)

Keep the preview pane's content and structure (raw prompt text + the `--- Metadata ---` block). Only adjust what's
needed for the new proportions/borders to read as a matched pair with the list pane (e.g. consistent label styling and
spacing). No metadata-content changes — the recently added Project/Workflows/Directives rows stay as-is.

### 5. Palette

Keep the row token colors as the file's existing literal Rich styles (`dim`, `cyan` project ref, `green` xprompt chips,
`yellow` directives, `magenta` cancelled marker) — they're the established idiom and read well; the highlight and
borders use theme tokens (`$accent`, `$secondary`, `$text-muted`). Final color/contrast choices are eyeballed and tuned
against the snapshot for beauty.

## Files to change / add

- **edit** `src/sase/ace/tui/styles.tcss` — container size (`98% × 96%`), pane ratio (`3fr` / `2fr`), `OptionList`
  highlight + option padding + `scrollbar-gutter`, header divider styling.
- **edit** `src/sase/ace/tui/modals/prompt_history_modal.py` — fixed-width tag column + wider project column, adaptive
  preview-width budget (once per rebuild), aligned header `Static`, live `History · N / M` count label, new column-width
  module constants. Keep the cached-summary fast path untouched.
- **edit** `tests/ace/tui/modals/test_prompt_history_modal.py` — assert fixed-column alignment (preview starts at the
  same offset regardless of tags), header content, the count label, adaptive-preview behavior (replacing the fixed-96
  assertion), and that cancelled dimming/marker is preserved.
- **add** `tests/ace/tui/visual/test_ace_png_snapshots_prompt_history.py` — a PNG visual snapshot of the redesigned
  modal (the concrete "is it beautiful" artifact), following the existing finder/saved-groups modal-snapshot pattern:
  push `PromptHistoryModal` with `get_prompts_for_fzf` monkeypatched to a curated deterministic set (varied projects, an
  `owner/repo` ref, multiple tags, a directives-only row, a no-tag row, a cancelled row, an empty-preview row), then
  `assert_page_png`. Golden generated with `--sase-update-visual-snapshots`.

## Performance (TUI-perf memory reviewed)

Reviewed `memory/long/tui_perf.md`. This change adds **no** synchronous I/O or event-loop blocking:

- Per-row metadata stays cached on `_PromptDisplayItem.summary` (parsed once per item, Rule 7 "memoize per-keystroke
  structures") — unchanged.
- The header is built once; the count label update is O(1); the adaptive preview budget is computed **once per
  option-list rebuild**, not per row. Fixed-width tag truncation is trivial string work.
- The existing per-keystroke `clear_options()` + re-add of options is pre-existing behavior; this plan does not add to
  it and does not introduce a new refresh path (Rule 4). Highlight repaint is CSS-only (Rule 6: highlight paints
  immediately).
- Quick open-latency sanity check on the real ~9k-entry corpus, as before, to confirm no regression from the bigger pane
  / adaptive width.

## Edge cases

- **No tags** → fixed tag column renders as blank padding; preview still starts at the aligned x.
- **Long tag set** → truncated within the fixed column with `+N`/`…`; full detail remains in the preview pane.
- **`owner/repo` project ref** → basename in the list column (full ref in the preview pane), unchanged.
- **Empty-preview rows** (prompt is only control tokens) → blank preview column; the chips convey the content.
- **Narrow terminals** → adaptive preview budget floors at `_MIN_PREVIEW_WIDTH`; the `no_wrap`/ellipsis Text and
  `scrollbar-gutter: stable` keep the grid intact; header stays aligned because all non-preview columns are fixed.
- **Cancelled rows** → existing `dim italic` + magenta `x`, over the new grid/highlight.

## Verification

- `just install` then `just check` (lint + mypy + tests) — required after file changes.
- `just test-visual` to render the new PNG snapshot; visually confirm alignment, highlight, header, count, cancelled
  dimming, and overall beauty; tune ratio/widths/palette and re-accept the golden with `--sase-update-visual-snapshots`.
- Manual `sase ace` smoke against the real history: open the modal, confirm near-fullscreen size, aligned columns,
  app-consistent highlight, full-width previews, live count, narrow-terminal behavior.
- Quick open-latency sanity check on `~/.sase/prompt_history.json` (~9k entries).

## Out of scope

- The persisted `PromptEntry` schema and the `prompt_metadata` extraction logic (reused unchanged).
- The non-TUI fzf prompt path and the command history modal.
- The per-keystroke full option-list rebuild (pre-existing; not made worse here). Called out as a known follow-up only
  if the latency sanity check surprises us.
- Any Rust `sase-core` change (none needed).

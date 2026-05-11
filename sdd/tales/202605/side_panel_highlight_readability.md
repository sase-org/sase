---
create_time: 2026-05-11 10:09:13
status: done
prompt: sdd/prompts/202605/side_panel_highlight_readability.md
---
# Improve readability of the highlighted entry in ACE TUI side-panels

## Problem

In the ACE TUI, the left side-panel list on every tab (ChangeSpecs, Agents, Axe) shows the currently-highlighted entry
with a saturated dark-blue background (Textual's `$accent`). The list rows render colored Rich `Text` — the
ChangeSpec/agent name is teal (`#00D7AF`), CL numbers are dim blue (`#569CD6`), the status-indicator suffix characters
are red/orange/yellow (`#FF5F5F`, `#FFAF00`, `#D7AF00`), the marked-row checkmark is green (`#00D700`), jump hints are
bright yellow (`#FFFF00`), etc. Mid- saturation foregrounds on a saturated blue background fight each other and reduce
contrast — the highlighted row is consistently the _hardest_ row to read on the panel.

The text color is never overridden by the highlight CSS, so the original per-token colors stay in place; the only thing
the highlight rule changes is the background.

## Goal

Make the highlighted row noticeably _easier_ to read than the unhighlighted rows without losing the per-token colors
that convey state (status indicator color = state class, CL-number style, mark color, hint color). The selection must
still be unambiguously visible at a glance.

## Scope

- **In scope**
  - The `.option-list--option-highlighted` rule for all three side-panel widgets: `ChangeSpecList`, `AgentList`,
    `BgCmdList`.
  - One new PNG snapshot test (per user request) demonstrating the new highlight, plus regeneration of any existing
    goldens that visually shift as a side effect.
- **Out of scope**
  - Touching the row-rendering helpers (`_changespec_list_helpers.py`, `_agent_list_render.py`, `_bgcmd_list_render.py`)
    — the per-token color set is already information-bearing and stays as-is.
  - The `AGENTS.md` "ChangeSpec suffix syntax highlighting" 4-file rule — that governs _suffix-token_ color choices, not
    the panel highlight background. No changes are needed in `saseproject.vim`, `display.py`, `query/highlighting.py`,
    or `changespec_detail.py`.
  - The detail-panel / right-side widgets.

## Files involved

| File                                             | Role                                            |
| ------------------------------------------------ | ----------------------------------------------- |
| `src/sase/ace/tui/styles.tcss`                   | Three highlight rules (lines ~133, ~989, ~1350) |
| `tests/ace/tui/visual/test_ace_png_snapshots.py` | New test + regen of existing snapshots          |
| `tests/ace/tui/visual/snapshots/png/`            | Regenerated and new golden PNGs                 |

## Approach

### 1. New highlight treatment (recommended option A)

Replace each `option-list--option-highlighted` block with a treatment that:

1. Uses a **neutral, slightly-lighter surface tone** for the background instead of `$accent`. Candidates: `$boost`,
   `$surface-lighten-2`, `$panel-lighten-2`. The neutral tone keeps the foreground token colors readable.
2. Adds **`text-style: bold`** so the row gains visual weight from typography rather than from a saturated fill.
3. Adds a **`border-left: thick $accent`** (or equivalent left edge accent bar) so the selection is unambiguous even
   when the background tone is subtle. Falls back to a solid block character prefix if `border-left` interacts badly
   with the existing `padding: 0 1` (verify during implementation).

If `border-left` causes layout shift (it does add 1 column on the left), the fallback is a `outline-left: thick $accent`
or simply omitting the bar and relying on `background + text-style: bold` alone. Pick the variant that doesn't shift the
text columns of the row.

The same rule is applied identically across all three widgets so the UX is consistent. (TCSS doesn't support shared
selectors via variables, so the three blocks are duplicated verbatim.)

### Alternatives considered

- **Keep `$accent` and force `color: $text` + bold** — simpler but flattens the per-token colors on the selected row,
  which removes information (status color, mark color). Rejected.
- **Reverse-video** (dark bg, light fg) — highest raw contrast but also flattens the per-token colors. Rejected.

### 2. Snapshot tests

Add one new visual test demonstrating the new style on a tab that doesn't already have a "highlighted row" snapshot:

- `test_axe_selected_row_png_snapshot` — switch to Axe tab, press `j` to highlight a non-first BgCmd entry, capture
  `axe_selected_row_120x40.png`.

Existing snapshots that _will_ shift because their first row is highlighted by default get their goldens regenerated (no
test code changes needed):

- `changespec_initial_120x40.png` (first ChangeSpec row highlighted on startup)
- `changespec_selected_row_120x40.png` (visual_billing row highlighted)
- `agents_list_120x40.png` (first agent row highlighted on tab-switch)

Regeneration uses `pytest --sase-update-visual-snapshots tests/ace/tui/visual/test_ace_png_snapshots.py -m visual`. Each
regenerated PNG is opened/inspected before commit to confirm the new style actually reads better, not worse.

### 3. Validation

- `just install` in the ephemeral workspace.
- `just check` (lint + mypy + tests) before reporting back.
- Visual spot-check of the regenerated and new PNGs.

## Open decisions

These are flagged for the user during plan review:

- **Q1 — Visual treatment**: confirm option A (neutral bg + bold + left accent bar) vs. option B (force `color: $text`
  on `$accent`) vs. option C (reverse-video).
- **Q2 — Snapshot scope**: just the one new Axe test, or also add an explicit `agents_selected_row` test for symmetry?
- **Q3 — Background tone**: agent's pick from `$boost` / `$surface-lighten-2` / `$panel-lighten-2` / explicit hex, or
  user-specified?

## Step-by-step (after plan approval)

1. `just install` in the current workspace.
2. Edit `src/sase/ace/tui/styles.tcss` at lines 133-135, 989-991, 1350-1352 — replace `background: $accent;` with the
   new treatment per Q1/Q3.
3. Add `test_axe_selected_row_png_snapshot` (and optionally `test_agents_selected_row`) in
   `tests/ace/tui/visual/test_ace_png_snapshots.py`.
4. Run `pytest --sase-update-visual-snapshots tests/ace/tui/visual/test_ace_png_snapshots.py -m visual` to regenerate
   goldens.
5. Visually inspect new and regenerated PNGs.
6. `just check`.
7. Report changed files, new snapshot paths, and a one-line description of the visual change.

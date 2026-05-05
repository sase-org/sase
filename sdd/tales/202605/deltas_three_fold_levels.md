---
create_time: 2026-05-05 16:42:46
status: done
prompt: sdd/prompts/202605/deltas_three_fold_levels.md
---
# Plan: DELTAS Three-Level Folding

## Goal

Allow the CLs tab DELTAS field to participate in the same three-step fold cycle as the other ChangeSpec sections when
using fold mode `zd`:

1. `COLLAPSED`: render `DELTAS:` plus the aggregate summary only.
2. `EXPANDED`: render each DELTAS file entry, but suppress the per-entry `| LINES:` drawer/details.
3. `FULLY_EXPANDED`: render each DELTAS file entry with the per-entry line details.

The user-facing result should be that pressing `zd` three times from the default folded state moves through summary,
file-list-only, file-list-with-lines, and back to summary.

## Current State

`src/sase/ace/tui/models/fold_state.py` currently treats DELTAS as a special two-state section:

- `normalize_deltas_fold_level(FoldLevel.EXPANDED)` maps to `FoldLevel.FULLY_EXPANDED`.
- `cycle_deltas_fold_level()` toggles between `COLLAPSED` and `FULLY_EXPANDED`.

`src/sase/ace/tui/widgets/deltas_builder.py` then checks that normalized level. Anything non-collapsed renders the full
file list, and `_append_entry()` always emits inline line stats when `entry.line_stats` is present.

That means `FoldLevel.EXPANDED` already exists in the shared model, but DELTAS deliberately skips it. The core DELTAS
data model and persistence do not need to change.

## Implementation Approach

1. **Make DELTAS cycle through the shared three states**
   - In `src/sase/ace/tui/models/fold_state.py`, change DELTAS-specific helpers so `cycle_deltas_fold_level()` advances
     `COLLAPSED -> EXPANDED -> FULLY_EXPANDED -> COLLAPSED`.
   - Either remove `normalize_deltas_fold_level()` usage for display/control paths, or redefine it as identity if it is
     still useful for centralized semantics. Avoid keeping a helper whose name implies two-state normalization.

2. **Render the new middle DELTAS level**
   - In `src/sase/ace/tui/widgets/deltas_builder.py`, make `build_deltas_section()` branch directly on the fold level:
     - `COLLAPSED`: current summary behavior.
     - `EXPANDED`: header plus sorted file entries, with no line-stat drawer/details.
     - `FULLY_EXPANDED`: header plus sorted file entries with line stats.
   - Update `_append_entry()` to accept a `show_line_stats` boolean and only append line stats when requested.
   - Keep file hints tied to visible file entries, so hints are present in both `EXPANDED` and `FULLY_EXPANDED` but
     absent when collapsed.

3. **Update fold-mode aggregate behavior**
   - In `src/sase/ace/tui/actions/navigation/_advanced.py`, stop normalizing DELTAS for `cycle_all`, `toggle_all`, and
     `_all_fold_states_aligned()`. DELTAS should align with the shared `FoldLevel` exactly.
   - Leave explicit toggles (`zD`) as a true collapsed/full toggle unless tests or existing conventions show that
     "toggle" should become a three-state cycle. The requested behavior is specifically for `zd`.

4. **Update user-facing fold documentation**
   - Update the help modal fold-mode text in `src/sase/ace/tui/modals/help_modal/bindings.py` so `zd` no longer says
     "folded/unfolded"; it should communicate cycling through summary, files, and lines within the 32-character limit.
   - Footer text can likely remain concise (`deltas`), but review whether the command catalog label
     (`src/sase/ace/tui/commands/catalog.py`) needs a wording tweak.

5. **Add focused regression tests**
   - Update `tests/ace/tui/test_deltas_fold_state.py` so DELTAS cycle tests assert the three-state sequence.
   - Update `tests/ace/tui/test_deltas_builder.py`:
     - `COLLAPSED` still renders summary only.
     - `EXPANDED` renders file entries without line stats.
     - `FULLY_EXPANDED` renders file entries with line stats.
     - File hints appear for visible entries at both non-collapsed levels.
   - Add an app-level CLs-tab test, probably in `tests/test_ace_tui_app.py` or a new focused TUI test, that constructs a
     ChangeSpec with line-statted deltas and presses `z`, `d` repeatedly:
     - after first `zd`, state is `expanded` and the screen shows file entries but not line details;
     - after second `zd`, state is `fully_expanded` and line details are visible;
     - after third `zd`, state is `collapsed` and only the summary is visible.

## Verification

Run the focused tests first:

```bash
just install
pytest tests/ace/tui/test_deltas_fold_state.py tests/ace/tui/test_deltas_builder.py tests/test_ace_tui_app.py -q
```

Then run the repo check required by project instructions after source edits:

```bash
just check
```

## Risks and Notes

- Existing tests deliberately assert the old two-state DELTAS behavior; those should be updated, not preserved.
- The new middle level should not alter DELTAS persistence, parsing, or Rust core/backend behavior.
- The phrase "`| LINES:` drawer" describes the ChangeSpec file format; the current TUI builder renders line stats
  inline. The implementation should preserve the current visual style while controlling whether those line stats are
  visible.

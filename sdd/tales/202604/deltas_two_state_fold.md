---
create_time: 2026-04-30 12:48:37
status: done
prompt: sdd/prompts/202604/deltas_two_state_fold.md
---

# Plan: Make DELTAS a Two-State Fold

## Problem

The previous collapsed-header fix changed DELTAS collapsed rendering from hidden to `DELTAS:\n`, but that removed the
useful compact information from the DELTAS line. With line-count support, the one-line DELTAS summary is the intended
folded surface: it preserves file counts, per-change line-count tokens, and the suffix on the same header line.

DELTAS should not have three meaningful visual states. It should have exactly two semantic states:

- **Folded**: a single `DELTAS:` summary line.
- **Unfolded**: the full alphabetical entry list.

The shared `FoldLevel` enum can stay three-valued because COMMITS, HOOKS, MENTORS, and TIMESTAMPS still use all three
levels. DELTAS should locally map that shared model onto two states.

## Current Shape

Relevant code paths:

- `src/sase/ace/tui/widgets/deltas_builder.py`
  - `COLLAPSED` currently renders only `DELTAS:\n`.
  - `EXPANDED` renders the useful one-line summary.
  - `FULLY_EXPANDED` renders the full entry list.
- `src/sase/ace/tui/actions/navigation/_advanced.py`
  - `cycle_deltas` uses the generic three-state `cycle_forward()`, so DELTAS can still cycle through an intermediate
    state.
  - `toggle_deltas` already jumps between `COLLAPSED` and `FULLY_EXPANDED`.
  - `cycle_all` can assign `FoldLevel.EXPANDED` to DELTAS.
- `src/sase/ace/tui/app.py` and `changespec_detail.py`
  - DELTAS defaults currently use `FoldLevel.EXPANDED`, which today means summary.
- `docs/ace.md`
  - The DELTAS fold wording is inconsistent: it says two-position cycle but names three enum levels.

## Intended Behavior

For `changespec.deltas is None` or `[]`, continue rendering nothing.

For non-empty DELTAS:

- Folded (`FoldLevel.COLLAPSED`): render the exact compact summary line, e.g.
  `DELTAS:  +3 (+428) ~6 (+91 ~37 -14) -1 (-22) (10 files)\n`.
- Unfolded (`FoldLevel.FULLY_EXPANDED`): render `DELTAS:\n` plus the full sorted list with inline line-count tokens.
- Any legacy or shared-control `FoldLevel.EXPANDED` value should be normalized to one of those two semantic states
  instead of producing a third DELTAS-specific presentation.

This restores the information lost by the header-only collapsed change while still preserving the original goal: folded
DELTAS remains visible when entries exist.

## Implementation

1. Update `build_deltas_section()`.
   - Keep the early return for `not deltas`.
   - Treat `FoldLevel.COLLAPSED` as folded summary by appending `DELTAS:` and calling the existing `_append_summary()`.
   - Treat every non-collapsed state as unfolded by rendering the full list.
   - Update the docstring to describe DELTAS' two semantic states and note that `FoldLevel.EXPANDED` is accepted only as
     a compatibility/shared-control input.

2. Update DELTAS fold navigation.
   - Add a small DELTAS-specific normalization/cycle helper near the navigation fold handling, or in fold-state code if
     that reads better locally.
   - Make `cycle_deltas` toggle only between `COLLAPSED` and `FULLY_EXPANDED`.
   - Keep `toggle_deltas` as a two-state toggle.
   - In `cycle_all` / `toggle_all`, map the assigned DELTAS state through the DELTAS normalization helper so DELTAS
     never lands in a distinct intermediate display state. If the shared all-sections state is `EXPANDED`, DELTAS should
     use the unfolded state.

3. Update defaults.
   - Change DELTAS defaults from `FoldLevel.EXPANDED` to the folded state (`FoldLevel.COLLAPSED`) wherever defaults
     exist only to get the summary rendering.
   - Leave call sites that pass through the app's current fold state alone unless they hard-code the old summary state.

4. Update tests.
   - In `tests/ace/tui/test_deltas_builder.py`, replace the header-only collapsed assertion with exact folded-summary
     assertions, including a line-count summary case.
   - Add/adjust tests proving `FoldLevel.FULLY_EXPANDED` renders the full list and `FoldLevel.EXPANDED` does not produce
     a third summary-only state.
   - Add a focused pure-unit test for the DELTAS-specific cycle/normalization helper so the two-state navigation
     contract is pinned without needing a full TUI app harness.

5. Update docs.
   - Fix `docs/ace.md` to describe DELTAS as folded/unfolded, not collapsed/expanded/fully-expanded.
   - Keep the documented folded example as the one-line file and line-count summary.

## Verification

Run focused checks first:

```bash
just install
.venv/bin/pytest tests/ace/tui/test_deltas_builder.py
```

If navigation helper tests land in a separate focused file, include that file in the same pytest invocation.

Then run the required repository check:

```bash
just check
```

## Risk

This is a TUI rendering and fold-control correction. It should not change DELTAS parsing, persistence, VCS computation,
or the ChangeSpec data model.

The main behavioral change is that collapsed DELTAS becomes a compact summary line rather than a bare header, and DELTAS
specific cycling stops exposing an intermediate state. Shared fold-all controls still work, but DELTAS maps their
three-level state into its two-state presentation.

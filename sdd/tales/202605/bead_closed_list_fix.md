---
create_time: 2026-05-13 10:22:08
status: done
prompt: sdd/prompts/202605/bead_closed_list_fix.md
---
# Fix `sase bead list -s closed` Reading Empty Legacy Store

## Problem

`sase bead list -s closed` currently prints `No issues found.` from `/home/bryan/projects/github/sase-org/sase_104`,
even though the checkout's `sdd/beads/issues.jsonl` contains hundreds of closed bead records.

The command is intercepted by the early bead fast path in `src/sase/main/entry.py`, which calls
`try_handle_bead_fast_path()` before the normal argparse/Python handler. The lightweight fast-path resolver currently
finds the primary workspace and immediately prefers `<primary>/.sase/sdd/beads` when that directory exists. In this
environment that legacy/non-version-controlled store exists at
`/home/bryan/projects/github/sase-org/sase/.sase/sdd/beads`, but its `issues.jsonl` is empty. As a result, fast-path
read commands report an empty store instead of using the current checkout's version-controlled `sdd/beads/issues.jsonl`.

This is consistent with the recent bead-read changes that removed merged workspace reads and made commands use a single
current store. The bug is not the closed-status filter itself; the local `sdd/beads/issues.jsonl` contains closed
records, and the Rust list parser accepts `closed`. The resolver is choosing the wrong single store before the list
operation runs.

## Goals

- Make fast-path bead reads and writes use the same store selection semantics as the normal Python bead CLI path.
- In version-controlled SDD checkouts, prefer the current checkout's `sdd/beads` store over a primary workspace
  `.sase/sdd/beads` directory.
- Preserve non-version-controlled behavior for projects that only have `.sase/sdd/beads`.
- Add regression coverage for the exact mixed-store case: current checkout has `sdd/beads`, primary workspace has
  `.sase/sdd/beads`, and fast-path context resolution must choose the current checkout.

## Implementation Plan

1. Update `src/sase/main/bead_fast_path.py` so `_resolve_lightweight_beads_context()` selects a current-checkout
   `sdd/beads` directory before considering `primary/.sase/sdd/beads`. This keeps the fast path aligned with
   `find_beads_location()` in `src/sase/bead/cli_common.py`, whose VC-mode behavior is current checkout first, primary
   workspace second.

2. Keep the non-VC fast-path write-command guard intact: `open`, `update`, `close`, and `dep` should continue to fall
   back to the slower Python path when the resolved store is `.sase/sdd/beads`.

3. Add a focused regression test in `tests/main/test_bead_fast_path.py`: create a primary workspace with
   `.sase/sdd/beads`, a sibling/current workspace with `sdd/beads`, and assert `_resolve_lightweight_beads_context()`
   returns the sibling/current `sdd/beads` store.

4. If needed, add or adjust a CLI-level test to prove `list -s closed` is not routed to the empty primary non-VC store.
   Keep this targeted so the test suite does not depend on this machine's real workspace layout.

5. Run the targeted bead fast-path/read tests first, then run `just install` if the workspace environment needs
   rebuilding, and finish with `just check` because code files in this repo changed.

## Verification

- Re-run `sase bead list -s closed` from this checkout and confirm it lists closed beads from `sdd/beads/issues.jsonl`.
- Re-run `sase bead stats` and confirm it reports the nonzero totals from the current checkout store.
- Run the focused tests around `tests/main/test_bead_fast_path.py`.
- Run `just check` before final response.

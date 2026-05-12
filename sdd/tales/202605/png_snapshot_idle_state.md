---
create_time: 2026-05-12 01:02:29
status: done
prompt: sdd/prompts/202605/png_snapshot_idle_state.md
---
# Plan: Fix PNG Snapshot Idle-State Drift

## Problem

The current GitHub Actions CI run for `a1644482` fails one PNG visual snapshot:

- `tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_constrained_width_no_wrap_png_snapshot`
- Snapshot: `axe_constrained_width_no_wrap_60x30`
- CI diff: `7758/586500` pixels, `1.322762%`, above the GitHub Actions visual tolerance of `1.0%`

The failure is not ordinary renderer anti-aliasing drift. The uploaded Actions artifact shows a semantic top-bar state
change:

- Committed expected PNG contains the `IDLE` badge in the top bar.
- Clean CI actual PNG does not contain `IDLE`.
- The rest of the narrow AXE layout is essentially stable.

This points to the visual test leaking persisted ACE idle state rather than asserting a deterministic app state.

## Root Cause Hypothesis

`AceApp` renders `InactiveIndicator` in the top bar. Startup code can restore pinned idle state from persisted user
state. The visual snapshot fixture currently patches deterministic startup loaders, notifications, grouping, and model
resolution, but it does not pin idle-state reads. That lets the rendered PNG depend on the external runtime environment:

- A local developer workspace with pinned/restored idle state can render `IDLE`.
- Clean GitHub Actions renders no `IDLE`.

The narrow `60x30` snapshot is the only remaining hard failure because the extra top-bar badge causes enough
layout/pixel change to exceed the CI tolerance.

## Approach

1. Make visual snapshot startup deterministic with respect to idle state.
   - Extend the shared visual fixture patching in `tests/ace/tui/visual/_ace_png_snapshot_helpers.py`.
   - Patch the idle-state restore path so visual tests always start non-idle and unpinned.
   - Keep this scoped to visual tests only; do not alter runtime ACE behavior.

2. Re-render the affected constrained-width snapshot under the deterministic state.
   - If the deterministic state is non-idle, update `axe_constrained_width_no_wrap_60x30.png` to remove the accidental
     `IDLE` badge.
   - Avoid broad snapshot churn. Only update other PNG goldens if the deterministic idle-state fix proves they were also
     depending on the leaked state and fail exact local comparison.

3. Add or adjust a focused assertion if useful.
   - For the constrained-width test, assert the rendered screen does not include `IDLE`, or assert the inactive
     indicator is not idle after startup.
   - This turns the root cause into an explicit test invariant instead of relying only on pixel output.

4. Verify.
   - Run the narrow failing visual test without `GITHUB_ACTIONS` for exact local equality.
   - Run `GITHUB_ACTIONS=true just test-visual` to match the Actions tolerance path.
   - Because files in this repo changed, run `just check` before final response.

## Expected Outcome

The visual snapshot suite no longer depends on a developer's persisted idle/pinned-idle state. The clean CI render and
local render agree on the constrained-width AXE top bar, and the one remaining GitHub Actions PNG failure is eliminated.

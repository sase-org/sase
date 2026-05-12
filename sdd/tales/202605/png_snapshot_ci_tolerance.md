---
create_time: 2026-05-12 00:36:14
status: done
prompt: sdd/prompts/202605/png_snapshot_ci_tolerance.md
---
# Allow Small PNG Snapshot Diffs In GitHub Actions

## Goal

Allow ACE PNG visual snapshot assertions to pass when no more than 1% of pixels differ, but only when the tests are
running inside a GitHub Actions workflow. Local runs should remain exact by default so developers still see every visual
regression while iterating.

## Current Shape

- PNG snapshot comparison is centralized in `tests/ace/tui/visual/png_diff.py`.
- `PngDiffSummary.is_within()` already supports both `max_diff_pixels` and `max_diff_ratio`.
- `AcePngSnapshotFixture.assert_page_png()` and `assert_png()` expose those tolerance knobs, but all current visual
  snapshot tests call them with the exact-match defaults.
- The pytest fixture in `tests/ace/tui/visual/conftest.py` constructs `AcePngSnapshotFixture` without environment-aware
  defaults.
- CI runs visual tests through `.github/workflows/ci.yml` using `just test-visual`, and failure reporting depends on
  mismatch artifacts written by `assert_png_matches()`.

## Design

1. Add a small environment helper in `tests/ace/tui/visual/png_diff.py`, for example
   `_running_in_github_actions_workflow()`, that returns true only when GitHub Actions workflow environment markers are
   present.
   - Use `GITHUB_ACTIONS == "true"` as the primary marker.
   - Require at least one workflow/run-specific marker such as `GITHUB_WORKFLOW` or `GITHUB_RUN_ID` so the behavior is
     tied to Actions workflow execution rather than a generic `CI=true` environment.
   - Keep the helper local to the visual test support module; this is test infrastructure, not product behavior.

2. Define the CI-only default tolerance in one place.
   - Recommended constants:
     - `GITHUB_ACTIONS_MAX_DIFF_RATIO = 0.01`
     - `GITHUB_ACTIONS_MAX_DIFF_PIXELS = 0`
   - Interpret `max_diff_pixels = 0` as "do not apply an absolute cap" only for the environment-derived default, or
     alternatively compute the pixel cap from the compared image size after `diff_pngs()` returns.
   - The cleaner approach is to add a small tolerance object/helper that resolves the effective caps after the summary
     is known:
     - local default: `changed_pixels == 0` and `changed_ratio == 0.0`
     - GitHub Actions default: `changed_ratio <= 0.01`
     - explicit per-call tolerances still take precedence.

3. Preserve strict local behavior.
   - If the GitHub Actions markers are absent, calls that omit tolerance parameters must still require byte-for-byte
     pixel equality.
   - Existing explicit `max_diff_pixels` or `max_diff_ratio` arguments should continue to work the same way.
   - Missing golden snapshots and dimension changes should still fail unless the changed-pixel ratio is within the
     effective threshold; missing goldens cannot be tolerated because there is no baseline to compare.

4. Keep failure artifacts and messages useful.
   - If a mismatch exceeds tolerance, keep writing the existing actual/expected/diff/summary/failure JSON artifacts.
   - Update the failure message so it reports the effective tolerance, including the CI-derived 1% allowance when
     active.
   - Do not write failure artifacts for tolerated diffs, matching current behavior for within-threshold comparisons.

5. Add focused tests in `tests/ace/tui/visual/test_png_diff.py`.
   - Local exact-match default still fails on a one-pixel diff.
   - With GitHub Actions environment markers set, a diff at or below 1% passes without artifacts.
   - With GitHub Actions environment markers set, a diff above 1% fails and writes artifacts.
   - Missing golden still fails in GitHub Actions mode.
   - Explicit per-call strictness can still force exact comparison if a caller passes `max_diff_ratio=0.0` and
     `max_diff_pixels=0`, or document if explicit zero is intentionally indistinguishable from omitted defaults.

## Open Decision

The existing API uses `max_diff_pixels=0` and `max_diff_ratio=0.0` as both "omitted" and "strict". To let future callers
explicitly request strict behavior even in GitHub Actions, we should change those parameters to `int | None = None` and
`float | None = None`, then resolve omitted values from the environment. This is slightly more invasive but avoids an
ambiguous API. Since current callers only rely on defaults, the migration is low risk.

## Verification

Run focused visual helper tests first:

```bash
just test-visual tests/ace/tui/visual/test_png_diff.py
```

Then run the repository-required check after code changes:

```bash
just check
```

Per repo memory, run `just install` before `just check` if the workspace has not already been prepared.

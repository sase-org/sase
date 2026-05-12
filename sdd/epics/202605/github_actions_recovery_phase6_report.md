# GitHub Actions Recovery — Phase 6 Final Status Report

Bead: `sase-31.6` (Phase 6 of `sase-31`).
Plan: [`sdd/epics/202605/github_actions_recovery.md`](github_actions_recovery.md).

## Latest `master` Workflow Set

- Head SHA: `6e79f32eef3c17539029357cb4a7997e8dffdb64`
  (title: "ref: split oversized test files below the pylimit threshold (Phase 5 of sase-31) (sase-31.5)").
- Workflows on this SHA:
  - `Deploy Docs` — **success** — https://github.com/sase-org/sase/actions/runs/25712696746
  - `CI` — **failure** — https://github.com/sase-org/sase/actions/runs/25712696707

`tools/last_workflow_set_status --repo sase-org/sase --branch master --limit 30 --tail 120` reports `FAIL`. Independent
verification via `gh run list`, `gh run view --json jobs`, `gh run view --log-failed`, and
`gh api repos/sase-org/sase/commits/<sha>/check-runs` all agree on the same job-level conclusions.

## Per-Job Outcome On `CI` For This SHA

- **Pass:** `docs-build`, `lint`, `build`, `bead-backend`, `fmt-md-check`, `install-smoke`,
  `launch-perf-floor`, `phase7-perf-floor`.
- **Fail:** `visual-test`, `test (3.14)`.
- **Cancelled (matrix sibling cancellation after `test (3.14)` failed):** `test (3.12)`, `test (3.13)`.
- External check `Workers Builds: sase` (Cloudflare) — success.

## Phase Outcomes Versus Baseline

The baseline failure surface (per the plan) was: docs PDF size, `Pylimit`, and ACE PNG snapshots. Status now:

- Phase 1 — workflow-status diagnostics improvements: present on master (commit `0acf6524`); script surfaces both
  annotations and log tails for the failing jobs below.
- Phase 2 — `axe_dashboard.py` pylimit fix (commit `c9fc3717`): `lint` job passes.
- Phase 3 — handbook PDF shrink (commit `0a1ac71f`): `Deploy Docs / Build docs PDF` and `CI / docs-build / Build docs`
  both pass.
- Phase 4 — fontconfig pinning + regenerated PNG goldens (commit `b8830bfb`): **does not hold in CI** — see residual
  failure below.
- Phase 5 — test-file pylimit split (commit `6e79f32e`): `tests/test_last_workflow_set_status_cli.py` and
  `tests/ace/tui/visual/test_ace_png_snapshots.py` are below the 1000-line limit; `lint` `Pylimit` step is green.

## Residual Failure: ACE PNG Snapshot Mismatches In CI

Both `CI / visual-test / Run visual tests` and `CI / test (3.14) / Run tests` fail with the same kind of
`AssertionError` from `tests/ace/tui/visual/png_diff.py:191`: every ACE PNG golden under
`tests/ace/tui/visual/snapshots/png/` has between ~7,250 and ~7,760 changed pixels versus the actual render. On the
120×40 captures (1,520,532 pixels) this is ~0.48–0.51%; on the 60×30 capture it is ~1.32% of a smaller canvas with
a roughly equal absolute pixel count, which is consistent with anti-aliasing/hinting drift, not content drift.

Affected tests (15 total, identical set in both `visual-test` and the 3.14 `test-cov` leg):

```
tests/ace/tui/visual/test_ace_png_snapshots.py::test_changespec_initial_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots.py::test_changespec_selected_row_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots.py::test_query_edit_modal_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots.py::test_agent_list_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots.py::test_agents_selected_row_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots.py::test_agents_unread_highlight_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_selected_row_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_empty_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_chop_run_info_panel_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_chop_run_info_panel_running_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_controlled_chop_output_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_lumberjack_tree_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_lumberjack_error_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_long_label_widening_png_snapshot
tests/ace/tui/visual/test_ace_png_snapshots_axe.py::test_axe_constrained_width_no_wrap_png_snapshot
```

`test (3.14) / Run tests` summary line: `===== 15 failed, 8488 passed, 8 skipped, 60 warnings in 166.27s =====`.
The 3.12 and 3.13 legs were cancelled by GitHub Actions' fail-fast matrix behavior and are not independent failures.

### CI-Only Classification

Phase 4 bundled Fira Code 6.2 under `tests/ace/tui/visual/fonts/`, builds a per-session `fonts.conf` in
`tests/ace/tui/visual/conftest.py`, and points `FONTCONFIG_FILE` at it so cairosvg/pango/fontconfig resolve
`monospace`/`sans-serif`/`serif` to the bundled font on every host. PNG goldens in
`tests/ace/tui/visual/snapshots/png/` were regenerated against that hermetic renderer.

`just test-visual` passed locally for Phase 5 (closure of `sase-31.5`), and the goldens were committed from that local
run. CI on the GitHub Actions Ubuntu image produces PNGs that differ from those committed goldens by a constant ~7K-pixel
band, evenly distributed (per the diff artifacts the test fixture writes under
`.pytest_cache/sase-visual/...`). The shape of the diff matches sub-pixel rendering differences
(cairo + pango glyph rasterization, FreeType hinting/LCD filter) rather than a logic or layout regression — every
snapshot mismatches by roughly the same per-glyph delta regardless of which tab or modal is rendered.

This is therefore a **CI-only residual** caused by environment drift in glyph rasterization between the host that wrote
the goldens and the GitHub Actions runner, despite Fira Code being pinned. Phase 4's font-file pinning is necessary but
insufficient; rasterizer/hinting parity is still missing.

### Recommended Follow-Up (Not Filed As A New Bead)

The Phase 6 plan asks for "a new small follow-up plan for only the remaining root cause". Per the closure instructions
for `sase-31.6` no new beads are created from this phase; this section records the recommended scope so a future bead or
manual fix can pick it up directly.

Likely-sufficient options, in increasing invasiveness:

1. Regenerate the 15 PNG goldens from inside a GitHub Actions CI run (push a one-off branch that runs
   `just test-visual --sase-update-visual-snapshots`, download the updated PNG artifacts, and commit them). This makes
   CI the source of truth for the goldens and removes the local-vs-CI divergence.
2. In addition to pinning the font file, pin FreeType/cairo/pango environment by either (a) running cairosvg inside a
   versioned container image referenced from the CI workflow and the dev `just test-visual` recipe, or
   (b) configuring fontconfig/`FREETYPE_PROPERTIES` to disable subpixel/LCD rendering and lock hinting to a single mode
   so cairo produces byte-identical output across hosts.
3. Loosen the per-snapshot tolerance in `tests/ace/tui/visual/png_diff.py` (`max_diff_pixels`/`max_diff_ratio`) for these
   ACE captures — accepted as a last resort because it weakens the snapshot contract.

The plan-level preference established by Phase 4 is to keep snapshot comparisons strict and fix the renderer/environment
instead. Option 1 is the smallest cross-host change that respects that preference and is the recommended starting point
for the follow-up.

## Cross-Phase Notes / Non-Blocking Warnings

- `lint` step reports a `.github:2 — warning` annotation on the failing check-runs; this is generic GitHub Actions
  cache/Node-version metadata, not a step failure.
- The `test (3.12)` and `test (3.13)` cancellations are matrix fail-fast effects of the 3.14 leg failing first and
  should not be treated as independent root causes (per the plan's "Cross-Phase Rules").
- Phase 1's diagnostic improvements were exercised against this SHA: `just workflow-status … --tail 120` and
  `gh run view --log-failed` returned equivalent root-cause text for both failing jobs, confirming the script no longer
  hides logs behind generic annotations.

## Closure

Per the bead's deliverable definition ("verify the latest master workflow set is green and isolate any CI-only residual
failures"), Phase 6's verification work is complete: the set is **not green**, the residual failure is **isolated** to
the ACE PNG snapshot rasterization-drift class above, and Phases 1–3 and 5 are confirmed green on this SHA. The
parent epic `sase-31` remains **open** pending the follow-up described above.

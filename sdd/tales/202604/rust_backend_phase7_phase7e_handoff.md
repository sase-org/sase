# Phase 7E Handoff: CI Regression Floor

Bead: `sase-1e.5`. Plan: `plans/202604/rust_backend_phase7.md`. Phase 7E turns the Phase 7B numbers into an enforceable
PR-gate guardrail without making CI flaky, and documents how the slow/manual end-to-end measurements get rerun out of
band.

## What landed

- `tests/perf/baselines/phase7_regression_floor.json` — versioned baseline file. `schema_version: 1` plus a 5-anchor
  `anchors` list keyed off the stable subset Phase 7B recommended (see "Anchors and rationale" below). Tolerance lives
  on the file itself (`tolerance.rust_slowdown_factor: 1.40`) so future agents can ratchet it without touching the
  checker code.
- `tests/perf/phase7_check_regression.py` — single-process driver for the floor check. Runs the four core-op harnesses
  Phase 7B already wrote adaptors for (`bench_core_parse`, `bench_core_query`, `bench_agent_scan`,
  `bench_status_state_machine`) at trimmed sample sizes, then for every anchor:
  - **absolute floor**: current Rust median ≤ `rust_slowdown_factor × phase7b_rust_median_s` (hardware-dependent;
    permissive on purpose);
  - **relative floor** for `must_beat_python: true` anchors: current Rust median strictly less than current Python
    median, both timed in the same process on the same hardware (hardware-independent).
  - Exits 1 if any anchor fails either check or any scenario is missing; always writes a JSON report to
    `plans/202604/perf_artifacts/rust_backend_phase7_floor_check.json` so CI can upload it on failure.
- `tests/perf/phase7/test_phase7_check_regression.py` — 10 fast unit tests for the comparison logic and the
  baseline-loader. Runs in the default (fast) test selection — no benchmarks executed. Includes a guard that the
  committed baseline only references surfaces with a known harness mapping in the checker.
- `Justfile` — `phase7-perf-check` body replaced with `python tests/perf/phase7_check_regression.py {{ args }}`. The
  Phase 7A helper-smoke that previously sat behind this target now runs as part of the default `just test` invocation
  via `tests/perf/phase7/test_phase7_helpers.py`, so coverage of the helpers is preserved.
- `.github/workflows/ci.yml` — new `phase7-perf-floor` job. Runs on every push/PR (matches the existing matrix triggers),
  invokes `just phase7-perf-check`, and uploads the JSON report under the `phase7-perf-floor-report` artifact name (with
  `if: always()`) so a regression can be inspected post-hoc without re-running the job locally.
- `.gitignore` — adds `plans/202604/perf_artifacts/rust_backend_phase7_floor_check.json` so per-machine reports are
  never committed; the README in the artifact dir documents the file as runtime-generated.

Out of scope for Phase 7E and explicitly not done:

- No documentation rewrite — `docs/rust_backend.md` updates belong to Phase 7D (sase-1e.4).
- No removal of the Python implementation, `SASE_CORE_BACKEND`, or `SASE_CORE_DUAL_RUN`. That is Phase 8.
- No new Phase 7C-style end-to-end artifacts. The floor check is intentionally core-op-only (the Phase 7B handoff
  excluded TUI/home-tree cold opens from the regression-floor anchor set because they are too environment-sensitive).

## Anchors and rationale

The five anchors in `tests/perf/baselines/phase7_regression_floor.json` come directly from the Phase 7B handoff's
recommended "safe floor anchor set":

| anchor                                                            | source artifact                                                | py median   | rust median | must beat python? |
| ----------------------------------------------------------------- | -------------------------------------------------------------- | ----------- | ----------- | ----------------- |
| `parse_project_bytes.golden_myproj.facade`                        | `rust_backend_phase7_parse_project_bytes_summary.json`         | 295.94 µs   | 124.35 µs   | yes (~2.4× win)   |
| `parse_project_bytes.synthetic_200_specs.facade`                  | `rust_backend_phase7_parse_project_bytes_summary.json`         | 26.67 ms    | 19.12 ms    | yes (~1.4× win)   |
| `parse_query.parse_only.direct`                                   | `rust_backend_phase7_parse_query_summary.json`                 | 12.31 µs    | 5.77 µs     | yes (~2.1× win)   |
| `scan_agent_artifacts.synthetic_6p_200pp.scan_facade`             | `rust_backend_phase7_scan_agent_artifacts_summary.json`        | 145.13 ms   | 119.99 ms   | yes (~1.21× win)  |
| `apply_status_update.golden_myproj_pure.apply_status_update`      | `rust_backend_phase7_apply_status_update_summary.json`         | 5.57 µs     | 5.80 µs     | no (must-not-regress-further guard) |

Surfaces explicitly excluded from the floor (per Phase 7B):

- `evaluate_query_many` — currently regresses vs the optimized Python batch path because per-call wire conversion
  dominates. Phase 8 is the right time to revisit, not Phase 7.
- All four small Git normalizers (`parse_git_branch_name`, `derive_git_workspace_name`, `parse_git_conflicted_files`,
  `parse_git_local_changes`) and `parse_git_name_status_z` — absolute medians are below 50 µs and noise alone moves
  them by more than 25 %. Anchoring on them would make CI flaky.
- `read_status_from_lines` and `plan_status_transition` — same dispatch-overhead-on-a-µs-core regression as the Git
  normalizers; not anchored.

## Tolerance and why it is not tighter

The plan recommended a 25-35 % absolute slowdown factor. Phase 7E ships at **1.40×** (40 %) for two reasons:

1. The Phase 7B captures came from a workstation; GitHub-hosted runners are shared infrastructure with materially more
   variance per run. Setting the floor right at the recommended 25 % would produce false positives the first time a CI
   runner happens to be loaded.
2. The relative `must_beat_python` check is the actual regression detector: it runs both medians in the same process on
   the same hardware, so it is hardware-independent. Four of the five anchors enforce it. The absolute floor exists as
   a backstop for the case where Rust regresses *below* Python on every CI runner — the 40 % factor is enough headroom
   that a single noisy run will not trip it.

Phase 7F should re-evaluate after a few weeks of CI history. If the runners stay quiet, ratchet the factor down toward
1.25-1.30 in a follow-up PR. The `tolerance.rust_slowdown_factor` field is the only knob you need to change.

## Verification commands run

- `just install`
- `.venv/bin/pytest -q tests/perf/phase7/test_phase7_check_regression.py` — 10 passed.
- `.venv/bin/python tests/perf/phase7_check_regression.py` — full local floor check, all 5 anchors PASS.
  ```
  [PASS] parse_project_bytes.golden_myproj.facade: rust=69.77us python=207.82us ceiling=174.09us
  [PASS] parse_project_bytes.synthetic_200_specs.facade: rust=5296.83us python=13572.38us ceiling=26762.65us
  [PASS] parse_query.parse_only.direct: rust=4.15us python=9.12us ceiling=8.08us
  [PASS] scan_agent_artifacts.synthetic_6p_200pp.scan_facade: rust=121441.63us python=148680.60us ceiling=167984.20us
  [PASS] apply_status_update.golden_myproj_pure.apply_status_update: rust=6.02us python=5.60us ceiling=8.12us
  ```
- `.venv/bin/python tests/perf/phase7_check_regression.py --smoke` — exits non-zero by design (smoke configuration uses
  smaller workload labels that do not match the baseline anchors). Smoke mode is intended for ad-hoc verification of
  the harness wiring, not for the regression check.
- `just check` — see commit message for the exact shell.

## Slow / manual end-to-end measurement

Phase 7E intentionally keeps the end-to-end TUI / `sase agents` / `sase run` startup measurements **out** of the PR
gate. They are still reproducible on demand:

- Re-run the Phase 7B core-op captures: `python tests/perf/phase7/run_phase7b.py` (the script Phase 7B used to produce
  the committed `rust_backend_phase7_*_summary.json` artifacts; ~95 s wall clock).
- TUI cold-open (Phase 7C surface): `python tests/perf/bench_tui_trace.py --output ...`
- Workflow-complete end-to-end (Phase 7C surface): `python tests/perf/bench_workflow_complete.py --projects 6
  --per-project 200 --runs 10 --warmup 2 --output ...`

When Phase 7C/7D produce a stable end-to-end anchor set, a follow-up PR can either:

1. Add new anchors to `tests/perf/baselines/phase7_regression_floor.json` *and* extend `_HARNESS_FOR_SURFACE` plus
   `_run_required_harnesses` in the checker so the same `just phase7-perf-check` flow covers them — only do this if the
   end-to-end medians prove stable on CI runners; or
2. Add a separate `workflow_dispatch`-only workflow (e.g. `.github/workflows/phase7_perf_e2e.yml`) that runs the slow
   captures and uploads the artifacts, without gating PRs on them.

Phase 7E ships option (1)'s plumbing (the checker is already a one-process driver that takes anchors from the baseline
file), but does not commit any Phase 7C end-to-end anchors. Phase 7D's
`sdd/research/202604/rust_backend_phase7_performance.md` recommends adding
`sase_agents_status_listing.synthetic_8_projects_25_agents` as the strongest end-to-end candidate, plus
`sase_run_startup.import_run_query_cold` as a non-gating sentinel; Phase 7B explicitly told 7E not to anchor on the
small Git/status normalizers or `sase_ace_cold_open` because their workstation-to-runner variance exceeds 25 %. Wiring
the recommended end-to-end anchor in is a one-PR change: extend `_HARNESS_FOR_SURFACE`, register a `bench_phase7_e2e`
adaptor in `_run_required_harnesses`, and add the row to `tests/perf/baselines/phase7_regression_floor.json`.

## Open questions for Phase 7F

- Confirm the floor check passes on CI hardware. The local 1.40× factor was set without GitHub Actions data; if the
  initial CI runs show consistent headroom, tighten the factor in a Phase 7F follow-up.
- The Phase 7E checker re-runs the harnesses every PR. If the median CI cost per run becomes a problem (>60 s for the
  job alone, before install/setup), an option is to drop the `parse_project_bytes.golden_myproj` anchor (it duplicates
  the synthetic_200_specs anchor's signal at lower workload size) and tighten the others. Phase 7F has the artifacts to
  decide.
- Once Phase 7C end-to-end anchors are merged, decide whether they belong in the same gate (option 1 above) or in a
  separate scheduled/manual workflow (option 2).

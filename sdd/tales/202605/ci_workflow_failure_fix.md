---
create_time: 2026-05-01 22:22:51
status: done
prompt: sdd/prompts/202605/ci_workflow_failure_fix.md
---
# CI Workflow Failure Fix Plan

## Context

The most recent completed GitHub Actions failure is CI run `25241279899`, created on `2026-05-02T02:13:51Z` for commit
`eb752a75ccad18303a3f194bbd1bfa123064329f` on `master`.

Two jobs failed:

- `launch-perf-floor`: `just launch-perf-check` raised `FileNotFoundError` for
  `plans/202605/perf_artifacts/agent_launch_phase1_baseline.json`.
- `bead-backend`: `just rust-check` failed in the checked-out `sase-core` repo because clippy denied a redundant closure
  in `crates/sase_core/src/bead/read.rs`.

The launch baseline exists under `sdd/tales/202605/perf_artifacts/agent_launch_phase1_baseline.json`, and the workflow
already uploads the report from `sdd/tales/202605/perf_artifacts/agent_launch_regression_check.json`. The checker still
uses the pre-SDD-migration root `plans/` path.

## Plan

1. Fix the launch regression checker paths in this repo:
   - Update `tests/perf/check_agent_launch_regression.py` defaults from `REPO_ROOT / "plans" / ...` to
     `REPO_ROOT / "sdd" / "plans" / ...`.
   - Add or update a focused unit test proving the committed default baseline/report paths live under `sdd/tales`.

2. Fix the Rust core clippy failure in the sibling repo:
   - Update `../sase-core/crates/sase_core/src/bead/read.rs` to pass the predicate function directly to `.filter()`
     instead of wrapping it in a redundant closure.
   - Keep this edit minimal because the failing CI line is style-only and behavior should not change.

3. Verify locally:
   - Run the focused Python regression-check tests.
   - Run `just launch-perf-check` to confirm the baseline file is found and the report is written under `sdd/tales`.
   - Run the focused Rust clippy/check command in `../sase-core` if practical, then run `just check` in this repo as
     required after edits.

4. Report the diagnosis and validation results:
   - Include the `gh` run ID and failed job names.
   - Mention that the current latest overall run may differ if a newer run is still in progress, but the fixed completed
     failure was `25241279899`.

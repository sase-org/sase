---
create_time: 2026-05-01 18:19:55
status: done
prompt: sdd/prompts/202605/fix_latest_ci_failure.md
---
# Fix Latest CI Failure

## Context

The most recent completed failed GitHub Actions run is CI run `25235433120` for commit
`14268439add239737d5bd271876210f21d6ac10f` on `master` (`chore: close bead Rust backend epic`, created 2026-05-01
22:13:19 UTC). Two jobs failed:

- `bead-backend` failed in `Run Rust bead checks`, specifically the `just rust-check` target. The first failing subcheck
  is `cargo fmt --all -- --check` in the sibling `sase-core` checkout. The log shows formatting diffs in
  `sase-core/crates/sase_core_py/src/lib.rs`.
- `phase7-perf-floor` failed in `just phase7-perf-check`. Every floor anchor passed except
  `notification_store.synthetic_5k.notification_modal_dismiss_burst`, whose CI median was about `4,656,134us` against a
  `4,461,181us` ceiling.

The broad Python test matrix, lint, packaging, install smoke, launch perf floor, and markdown formatting jobs passed in
that run.

## Diagnosis

The immediate hard failure is cross-repo drift: the `sase` workflow checks out the latest `sase-core` `master`, and that
checkout is currently not rustfmt clean. Because `rust-check` runs before the bead parity tests and smoke, the job exits
before any bead behavior can be exercised.

The performance floor failure is likely a threshold/harness robustness issue rather than a functional correctness
failure. It is isolated to a long, multi-second notification modal dismiss burst scenario and missed the absolute
ceiling by roughly 4.4%. The rest of the performance floor passed, including notification snapshot, mark-all-read,
append/rewrite concurrency, and the core query/parser/status anchors.

## Implementation Plan

1. Fix the Rust formatting failure in `../sase-core`.
   - Run `cargo fmt --all -- --check` in `../sase-core` to confirm the local failure matches CI.
   - Run `cargo fmt --all` and inspect the resulting diff, keeping the change limited to formatting in
     `crates/sase_core_py/src/lib.rs`.
   - Re-run the Rust format check. If time allows, run the broader Rust check through this repo's `just rust-check`.

2. Reproduce and harden the Phase 7 floor failure in this repo.
   - Inspect `tests/perf/phase7_check_regression.py`, `tests/perf/bench_notification_store.py`, and
     `tests/perf/baselines/phase7_regression_floor.json` for how the modal dismiss burst is measured and gated.
   - Re-run the focused floor check or a reduced notification-store harness to see whether the miss is repeatable
     locally.
   - Prefer a targeted fix to the gate over a broad baseline relaxation: either make the noisy modal burst anchor use a
     statistically more stable measurement strategy, or adjust only that anchor's ceiling/slowdown with an explicit
     comment explaining why this scenario has higher CI variance.
   - Preserve the other Phase 7 floor anchors as hard gates.

3. Verify before finishing.
   - Run `just install` first if needed in this workspace.
   - Run focused checks for the changed files/harnesses.
   - Run `just check` in this repo because the repo memory requires it after file changes.
   - Run the relevant `sase-core` Rust formatting/check command for any sibling-repo change.

## Expected Outcome

The next CI run should no longer fail immediately in `bead-backend` due to Rust formatting drift, and
`phase7-perf-floor` should stop failing on a single high-variance notification modal dismiss burst while still catching
meaningful regressions in the stable performance anchors.

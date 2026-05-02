---
create_time: 2026-05-01 19:33:52
status: done
prompt: sdd/prompts/202605/fix_recent_ci_rustfmt_failure.md
---
# Fix Recent CI Rustfmt Failure

## Context

The most recent completed GitHub Actions failure for `sase-org/sase` is CI run `25236481624` from `2026-05-01T22:48:25Z`
on `master`. A newer run `25237216530` was still in progress when inspected, but its `bead-backend` job had already
failed the same way.

The failure is isolated to the `bead-backend` job, step `Run Rust bead checks`. That step runs `just rust-check`, whose
first dependency is `rust-fmt-check`:

```sh
cd "$SASE_CORE_DIR" && cargo fmt --all -- --check
```

CI checks out `sase-org/sase-core` into the Actions workspace and runs the Rust format check there. The log shows
`cargo fmt --check` emitting formatting diffs across `sase-core` files such as:

- `crates/sase_core/examples/bench_parse.rs`
- `crates/sase_core/src/agent_cleanup/execution.rs`
- `crates/sase_core/src/agent_cleanup/mod.rs`
- `crates/sase_core_py/src/lib.rs`

The Python test matrix, lint, build, install smoke, markdown formatting, and performance floor jobs are not the primary
failure.

## Diagnosis

The root cause is Rust formatting drift in the sibling `sase-core` repository, exposed by the `sase` repository's bead
backend CI gate. The `sase` workflow uses a floating checkout of `sase-core` plus the stable Rust toolchain, so a
formatting mismatch in `sase-core` breaks `sase` CI even when no Python files in `sase` are wrong.

Local `../sase-core` is at the same `master` commit reported by GitHub (`12423288b92d89795271c27e65bf9b2489391a30`), but
local `cargo fmt --check` does not reproduce the CI diff, indicating a formatter/toolchain environment difference. The
fix still needs to make the checked-in Rust sources acceptable to the formatter used by CI, and preferably avoid
creating churn for the local toolchain.

## Plan

1. Capture the exact failed CI diff from `gh run view --log-failed` and use it as the source of truth for the CI
   formatter's expected output.
2. Inspect the affected `sase-core` files locally and determine whether applying the CI formatter output is also
   accepted by the local rustfmt version.
3. Make the minimal cross-repo fix in `../sase-core`:
   - Prefer running or applying formatting only to Rust files that CI reports.
   - If the formatter versions disagree after that, pin or align the Rust toolchain/config in `sase-core` rather than
     adding broader code churn.
4. Re-run focused verification:
   - `cargo fmt --all -- --check` in `../sase-core`.
   - `just rust-check` from `sase_100` if the local environment can reproduce the CI gate reliably.
   - `just check` from `sase_100` if any files in this repo are changed.
5. Use `gh` to re-check the latest run status after the local fix so the final diagnosis distinguishes between the
   already-failed run and any newer run.

## Expected Outcome

The `bead-backend` job should stop failing at the Rust format check. If the only changes are in `../sase-core`, the
final work product will be a small formatting or toolchain-alignment patch in that repository plus verification output.

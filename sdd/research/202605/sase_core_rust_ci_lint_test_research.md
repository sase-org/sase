# SASE Core Rust CI, Linters, and Test Strategy

Date: 2026-05-06

## Question

What would "excellent CI integration, linters, and tests" mean for `sase-core`, given that it is a Rust workspace with a
pure-Rust core crate and a PyO3 Python extension crate?

## Summary

`sase-core` already has a sound first CI layer: `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D
warnings`, `cargo test --workspace`, and a `maturin` wheel/import smoke job. The next step is not to replace that. The
right target is a layered CI system:

1. Keep a fast PR gate for format, Clippy, compile, tests, and wheel import smoke.
2. Make test output easier to diagnose with `cargo-nextest` and JUnit artifacts.
3. Add `--locked` to normal CI commands so CI enforces the checked-in lockfile.
4. Add Rust documentation warnings as a real gate.
5. Add dependency policy checks with `cargo-deny`.
6. Add coverage reporting with `cargo-llvm-cov`, initially informational.
7. Add MSRV verification for the declared `rust-version = "1.78"`.
8. Add release-adjacent checks for public API compatibility and wheel matrix behavior.

For SASE specifically, the highest-value tests are contract and parity tests: Rust behavior must keep matching Python
and the serialized wire formats must stay stable. The current suite already leans in that direction, so CI should make
those contracts visible and hard to regress.

## Current `sase-core` State

Repository inspected: `../sase-core`.

Workspace members:

- `crates/sase_core`: pure-Rust backend/domain crate.
- `crates/sase_core_py`: PyO3 binding crate exposing `sase_core_rs`.

Toolchain and packaging:

- `rust-toolchain.toml` uses `stable` with `rustfmt` and `clippy`.
- Workspace package metadata declares `edition = "2021"` and `rust-version = "1.78"`.
- `Cargo.lock` is committed.
- `sase_core_py` uses `maturin>=1.7,<2.0`, Python `>=3.12`, and PyO3 `abi3-py312`.

Existing GitHub Actions workflow:

- `rust-checks`: checkout, install stable Rust, cache Cargo, run format, Clippy with `-D warnings`, and workspace tests.
- `wheel-smoke`: build an abi3 wheel with `PyO3/maturin-action@v1`, install it into a fresh venv, import
  `sase_core_rs`, smoke `parse_query`, and run `twine check`.

Local verification during this research:

- `cargo test --workspace --no-run` passed.
- `cargo test --workspace` passed.
- The suite included 330 `sase_core` unit tests, eight integration-test executables under `crates/sase_core/tests`, 12
  `sase_core_rs` binding tests, and doc-test passes with zero doc tests.

## What Rust CI Should Gate

### Format

Use `cargo fmt --all -- --check` as a required PR gate. This is standard Rust hygiene and the repo already does it.

Recommendation:

```bash
cargo fmt --all -- --check
```

### Clippy

Keep Clippy on the same stable toolchain used to compile the crate. The official Clippy CI docs recommend `-Dwarnings`
for CI and recommend using Clippy from the same toolchain used for compilation.

Recommendation:

```bash
cargo clippy --workspace --all-targets --locked -- -D warnings
```

Do not enable `clippy::pedantic` globally at first. For a migration-heavy core crate, that tends to create churn without
much product signal. Add narrower lints only when they protect a real SASE invariant.

### Compile and Test

The baseline should remain Cargo-native because `cargo test` is the Rust default and runs unit, integration, and
documentation tests by default. The Cargo docs also call out that `cargo test` compiles multiple targets and runs test
executables serially by target, which is one reason `nextest` can improve CI diagnostics and runtime.

Recommended PR gate:

```bash
cargo test --workspace --locked
```

Recommended next step:

```bash
cargo nextest run --workspace --locked
```

Use `cargo test --workspace --doc --locked` separately only if the crate starts adding meaningful public doctests.
`nextest` does not replace Cargo doctests; for now `cargo test --workspace` already runs the doc-test pass.

### Documentation Warnings

Rust library APIs benefit from a doc build gate even when missing-docs is not required. The low-churn version is to fail
on rustdoc warnings, especially broken intra-doc links.

Recommendation:

```bash
RUSTDOCFLAGS="-D warnings" cargo doc --workspace --no-deps --locked
```

Do not enable `#![deny(missing_docs)]` immediately. That should be a deliberate API documentation project, not incidental
CI hardening.

### Lockfile Reproducibility

Because `Cargo.lock` is committed, CI should normally use `--locked`. Cargo documents `--locked` as the flag that asserts
the exact dependency versions in the lockfile are used and errors if Cargo would update it. That is the right default for
PR CI.

Add `--locked` to:

- `cargo clippy`
- `cargo test` or `cargo nextest`
- `cargo doc`
- `cargo llvm-cov`, unless a coverage tool specifically needs to install/update itself outside Cargo

### Dependency Policy and Security

Prefer `cargo-deny` over only `cargo-audit` because it covers more of the dependency policy surface: licenses, duplicate
or banned crates, advisories, and sources. `cargo-audit` is still useful, but `cargo-deny` can centralize the project
policy in `deny.toml`.

Recommended checks:

```bash
cargo deny check bans licenses sources
cargo deny check advisories
```

Policy suggestion:

- Gate `bans`, `licenses`, and `sources` on every PR touching Rust dependency files.
- Run `advisories` on PRs and on a schedule, but consider making the scheduled advisory job non-blocking at first so a
  newly published advisory does not unexpectedly block unrelated work before maintainers triage it.

Initial license allowlist should match the workspace license posture:

- `MIT`
- `Apache-2.0`
- `BSD-2-Clause`
- `BSD-3-Clause`
- `ISC`
- `Unicode-3.0`
- any other license already present in the resolved dependency graph after review

### MSRV

The workspace declares `rust-version = "1.78"`, but CI currently installs `stable`. That proves the code works on current
stable, not that the declared minimum is correct.

Recommended job:

```bash
cargo hack check --rust-version --workspace --all-targets --locked
```

For a pure published library, the Cargo Book example uses `--ignore-private`. For SASE, `crates/sase_core_py` is
`publish = false` but still matters because users may build the Python extension from source. Prefer checking both
workspace crates unless PyO3 or maturin constraints make that infeasible. If infeasible, split the job:

```bash
cargo hack check --rust-version -p sase_core --all-targets --locked
cargo +stable check -p sase_core_py --all-targets --locked
```

### Coverage

Use `cargo-llvm-cov`. It is the current practical Rust coverage tool because it wraps rustc source-based coverage and
supports `cargo test` and `cargo nextest`.

Recommended initial command:

```bash
cargo llvm-cov nextest --workspace --locked --lcov --output-path lcov.info
```

Rollout stance:

- Start as informational: upload HTML or LCOV artifacts and show a PR summary.
- Do not add a hard percentage gate immediately.
- Later add focused thresholds for high-risk modules after measuring current coverage.

Good first coverage targets for SASE:

- Query parser/evaluator.
- Status planner and field updates.
- Bead mutation/storage.
- Agent/artifact ingest and graph query behavior.
- PyO3 binding error mapping.

### Python Wheel Smoke

Keep the existing `maturin` job. It catches a class of failures that pure Cargo cannot: wheel build shape, import module
name, abi3 configuration, `twine check`, and Python exception mapping.

Recommended additions:

- Add `--locked` to the maturin args if compatible with the action and current packaging.
- Run the import smoke on at least Linux PRs.
- On release or a scheduled workflow, run a matrix for Linux, macOS, and Windows because the package classifiers claim
  those operating systems.
- Keep testing the actual installed wheel in a fresh venv rather than importing from the source tree.

## Suggested GitHub Actions Shape

### Fast PR Workflow

Required jobs:

- `fmt`: `cargo fmt --all -- --check`
- `clippy`: `cargo clippy --workspace --all-targets --locked -- -D warnings`
- `test`: install `nextest`, then `cargo nextest run --workspace --locked`; optionally run `cargo test --workspace
  --doc --locked`
- `doc`: `RUSTDOCFLAGS="-D warnings" cargo doc --workspace --no-deps --locked`
- `wheel-smoke`: current maturin/import smoke
- `dependency-policy`: `cargo deny check bans licenses sources`, plus advisories once the ignore policy is in place

Useful workflow settings:

- `concurrency` per branch to cancel stale PR runs.
- `permissions: contents: read` by default.
- `CARGO_TERM_COLOR: always`.
- `Swatinem/rust-cache@v2`, already present.
- JUnit test artifact upload from nextest if a CI reporting surface will consume it.

### Scheduled Workflow

Nightly or weekly:

- `cargo update` then build/test, non-blocking or issue-creating rather than required on every PR.
- `cargo deny check advisories`.
- Full coverage artifact.
- Linux/macOS/Windows test matrix if not run on every PR.

### Release Workflow

Before publishing or tagging:

- Run the full PR workflow.
- Run wheel matrix for target platforms.
- Run `cargo-semver-checks` for published Rust crates. This action is designed to check public API semver compatibility
  against the latest published normal crate version before publishing. For SASE, apply it to `sase_core` if that crate is
  published to crates.io; it is less relevant to the private PyO3 crate.

## Test Strategy for `sase_core`

The best Rust test suite for this project is not just "more unit tests." It should preserve the SASE boundary contract.

### Keep and Expand Parity Tests

Current tests already include golden/parity suites for Python wire behavior, query evaluation, bead storage, git query
parsers, notification store behavior, and agent scanning. That is exactly the right emphasis while Rust is absorbing
backend behavior from Python.

Add parity tests whenever:

- A Python caller depends on serialized JSON shape.
- A parser accepts legacy or malformed data.
- A command output parser handles VCS or filesystem edge cases.
- A Rust function replaces Python behavior that has existing fixtures.

### Unit-Test Private Rust Invariants

Use module-local `#[cfg(test)]` tests for small invariants that are awkward to expose publicly:

- Parser token transitions.
- Status transition table rules.
- Path normalization rules.
- Stable sort order and tie breakers.
- Error classification.

### Use Integration Tests for Public Contracts

Use `crates/sase_core/tests/*.rs` for tests that should treat `sase_core` as an external consumer would:

- Public API JSON contracts.
- End-to-end fixture ingestion.
- Cross-module behavior, such as artifact ingest followed by query.
- PyO3-visible behavior that must not depend on private internals.

### Add Property/Fuzz Testing Selectively

Property testing is most useful where SASE parses user-controlled strings or maintains bidirectional serialization:

- Query tokenizer/parser round trips.
- Suffix parsing.
- ChangeSpec section parsing.
- Artifact graph invariants.

Candidate tools:

- `proptest` for deterministic property tests inside normal CI.
- `cargo-fuzz` later for fuzz targets, probably scheduled rather than required on each PR.

Do not start with fuzzing as the first CI improvement. Add it after the basic gates and coverage are in place.

## Recommended Rollout

### Phase 1: Tighten Existing CI

- Add `--locked` to Cargo commands.
- Add `RUSTDOCFLAGS="-D warnings" cargo doc --workspace --no-deps --locked`.
- Add workflow concurrency and least-privilege permissions.
- Keep the current maturin smoke job.

### Phase 2: Better Test Runner and Reports

- Install `nextest` with `taiki-e/install-action@nextest`.
- Replace the main runtime test step with `cargo nextest run --workspace --locked`.
- Keep a separate doc-test step if doctests become meaningful.
- Upload nextest JUnit output if the team wants PR annotations or historical flakes.

### Phase 3: Dependency Policy

- Add `deny.toml`.
- Gate licenses, bans, and sources.
- Add advisory checking after the ignore/triage policy is clear.

### Phase 4: Coverage and MSRV

- Add `cargo-llvm-cov` informational coverage artifacts.
- Add `cargo hack check --rust-version`.
- Decide whether `sase_core_py` must honor Rust 1.78 source builds or whether MSRV is only a `sase_core` library
  contract.

### Phase 5: Release Hardening

- Add wheel matrix checks for Linux/macOS/Windows.
- Add `cargo-semver-checks` before publishing `sase_core`.
- Add scheduled latest-dependency tests.

## Open Decisions

- Should every PR test Linux/macOS/Windows, or should non-Linux run on push/schedule only?
- Is `rust-version = "1.78"` a hard contract for the PyO3 crate too, or only for `sase_core`?
- Should advisory failures block PRs immediately, or start as scheduled triage?
- Should coverage have thresholds, or remain an informational trend until the Rust migration stabilizes?
- Should `sase-core` expose a repo-local `just check` equivalent so CI and local agents run the same command?

## Sources

- Rust Cargo Book, Continuous Integration:
  https://doc.rust-lang.org/cargo/guide/continuous-integration.html
- Rust Cargo Book, `cargo test`:
  https://doc.rust-lang.org/cargo/commands/cargo-test.html
- Clippy Documentation, Continuous Integration:
  https://doc.rust-lang.org/clippy/continuous_integration/index.html
- cargo-nextest docs, pre-built binaries and GitHub Actions:
  https://nexte.st/docs/installation/pre-built-binaries/
- cargo-llvm-cov README:
  https://github.com/taiki-e/cargo-llvm-cov
- cargo-deny checks:
  https://embarkstudios.github.io/cargo-deny/checks/index.html
- cargo-hack README:
  https://github.com/taiki-e/cargo-hack
- cargo-semver-checks GitHub Action:
  https://github.com/obi1kenobi/cargo-semver-checks-action
- PyO3 maturin-action README:
  https://github.com/PyO3/maturin-action

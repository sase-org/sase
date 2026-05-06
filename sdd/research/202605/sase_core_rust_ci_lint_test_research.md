# SASE Core Rust CI, Linters, and Test Strategy

Date: 2026-05-06 (revised 2026-05-05 with additional research)

## Question

What would "excellent CI integration, linters, and tests" mean for `sase-core`, given that it is a Rust workspace with a
pure-Rust core crate and a PyO3 Python extension crate?

## Summary

`sase-core` already has two CI workflows: `ci.yml` (format, Clippy with `-D warnings`, workspace tests, abi3 wheel
import smoke) and `release.yml` (Linux x86_64/aarch64, macOS universal2, Windows x86_64 wheel matrix plus sdist, twine
metadata check, optional PyPI publish on tag). The next step is not to replace either; the goal is a layered system on
top of them:

1. Keep a fast PR gate for format, Clippy, compile, tests, and wheel import smoke.
2. Make test output easier to diagnose with `cargo-nextest` and JUnit artifacts.
3. Add `--locked` to normal CI commands so CI enforces the checked-in lockfile.
4. Add Rust documentation warnings as a real gate.
5. Centralize lint policy in a `[workspace.lints]` table and a `clippy.toml`.
6. Add dependency policy checks with `cargo-deny`, plus unused-dep detection (`cargo-machete`).
7. Add coverage reporting with `cargo-llvm-cov`, initially informational.
8. Add MSRV verification for the declared `rust-version = "1.78"`.
9. Add `insta` snapshot tests for SASE's serialized wire formats.
10. Add release-adjacent checks for public API compatibility, Python type stubs, and wheel matrix behavior.
11. Harden GitHub Actions itself: pin action SHAs, switch PyPI publish to Trusted Publishing, add scheduled beta/nightly
    jobs.

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

Existing GitHub Actions workflows:

- `ci.yml` / `rust-checks`: checkout, read pinned toolchain channel from `rust-toolchain.toml`, install stable Rust,
  cache Cargo via `Swatinem/rust-cache@v2`, run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets
  -- -D warnings`, and `cargo test --workspace`.
- `ci.yml` / `wheel-smoke`: build an abi3 wheel with `PyO3/maturin-action@v1` (`manylinux: "2_28"`), install it into a
  fresh venv, import `sase_core_rs`, smoke `parse_query("status:Ready")`, smoke a `parse_query("(")` ValueError, and
  run `twine check`.
- `release.yml`: triggered on tag push `v*` and `workflow_dispatch`. Builds wheels for Linux x86_64, Linux aarch64
  (cross via QEMU, smoke skipped), macOS universal2, and Windows x86_64; builds an sdist; runs `twine check` on the
  combined artifact set; optionally publishes to PyPI when `PYPI_API_TOKEN` is set.

Notable existing config:

- `rustfmt.toml` sets `max_width = 80` (no other rustfmt customization).
- The PyO3 binding crate has two `unsafe` blocks (the FFI surface), making sanitizer/Miri coverage relevant.
- No `Cargo.toml` `[workspace.lints]` table, no `clippy.toml`, no `deny.toml`, no `nextest.toml`, no `.cargo/audit.toml`.

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

#### Centralize Lint Policy in `[workspace.lints]`

Since Rust 1.74, Cargo accepts a `[workspace.lints]` table that workspace members opt into via `lints.workspace = true`
in their own `Cargo.toml`. This is the right home for cross-crate lint policy in `sase-core` because both crates should
agree on the same warning posture.

Suggested skeleton in the workspace `Cargo.toml`:

```toml
[workspace.lints.rust]
unsafe_op_in_unsafe_fn = "warn"
unreachable_pub = "warn"
missing_debug_implementations = "warn"
rust_2018_idioms = "warn"

[workspace.lints.clippy]
# Groups (lower priority so individual overrides win)
all = { level = "warn", priority = -1 }
pedantic = { level = "allow", priority = -1 }  # opt in selectively
# Targeted opt-ins
dbg_macro = "warn"
print_stdout = "warn"
print_stderr = "warn"
todo = "warn"
unimplemented = "warn"
unwrap_used = "warn"   # consider "deny" once existing call sites are cleaned up
expect_used = "warn"

[workspace.lints.rustdoc]
broken_intra_doc_links = "deny"
private_intra_doc_links = "warn"
```

Then in each crate:

```toml
[lints]
workspace = true
```

This keeps `cargo clippy --workspace --all-targets -- -D warnings` as the single CI gate while making policy diffs
reviewable in one place.

#### Use `clippy.toml` for Project Constants

A `clippy.toml` next to `Cargo.toml` lets the project ban specific symbols project-wide without writing per-call lint
attributes:

```toml
msrv = "1.78"
disallowed-methods = [
    { path = "std::env::set_var", reason = "non-thread-safe; use a test helper instead" },
]
disallowed-types = [
    # Add types if SASE settles on a project-wide preference (e.g. always
    # `BTreeMap` over `HashMap` for deterministic serialization order).
]
```

The `msrv` key makes Clippy's MSRV-aware lints honor the declared minimum Rust version, which means lints that
recommend newer-stdlib idioms will not fire below the floor.

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

#### `.config/nextest.toml`

A small profile keeps CI behavior explicit:

```toml
[profile.default]
slow-timeout = { period = "60s", terminate-after = 3 }
fail-fast = false

[profile.ci]
fail-fast = false
failure-output = "immediate-final"
final-status-level = "flaky"
retries = { backoff = "exponential", count = 2, delay = "1s", jitter = true }
junit = { path = "target/nextest/ci/junit.xml" }
```

CI should run `cargo nextest run --workspace --locked --profile ci`. Retries-on-flake should be paired with a flaky
test report, not used as a way to ignore flakes; `final-status-level = "flaky"` makes flakes visible in the summary.

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

`--frozen` vs `--locked`: `--frozen` implies `--locked` and additionally forbids any network access. Prefer `--locked`
in CI unless the runner is air-gapped, because `--frozen` will fail if the registry index needs a refresh that Cargo
would otherwise do silently. `Swatinem/rust-cache@v2` keys its cache on the lockfile, so using `--locked` also keeps
cache hits stable.

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

Concrete `deny.toml` skeleton:

```toml
[graph]
# Check all targets the workspace actually compiles for. Add windows / macOS /
# linux targets explicitly so license/advisory checks don't silently skip a
# platform-specific dep tree.
targets = [
    { triple = "x86_64-unknown-linux-gnu" },
    { triple = "aarch64-unknown-linux-gnu" },
    { triple = "x86_64-apple-darwin" },
    { triple = "aarch64-apple-darwin" },
    { triple = "x86_64-pc-windows-msvc" },
]
all-features = true

[advisories]
version = 2
yanked = "deny"
ignore = [
    # { id = "RUSTSEC-YYYY-NNNN", reason = "..." },
]

[licenses]
version = 2
confidence-threshold = 0.93
allow = [
    "MIT",
    "Apache-2.0",
    "Apache-2.0 WITH LLVM-exception",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "Unicode-3.0",
    "Unicode-DFS-2016",
    "Zlib",
]

[bans]
multiple-versions = "warn"
wildcards = "deny"
deny = []
skip = []
skip-tree = []

[sources]
unknown-registry = "deny"
unknown-git = "deny"
allow-registry = ["https://github.com/rust-lang/crates.io-index"]
allow-git = []
```

`bans.multiple-versions = "warn"` is a pragmatic default; raising to `"deny"` is a project policy choice once the
existing dep graph has been deduplicated.

### Unused Dependencies

`cargo-machete` is a fast static checker for unused dependencies. It runs without compiling the crate, has a
maintained GitHub Action, and supports a `Cargo.toml` ignore list for false positives. Prefer it over `cargo-udeps`,
which requires nightly.

Recommended PR job:

```bash
cargo machete --with-metadata
```

`--with-metadata` reads the resolved dependency graph rather than just `Cargo.toml`, which catches a wider set of cases
(such as deps only used through workspace inheritance).

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
  those operating systems. `release.yml` already does this on tag push and `workflow_dispatch`; consider also wiring it
  to a weekly `schedule` trigger to catch upstream `manylinux` regressions before a release.
- Keep testing the actual installed wheel in a fresh venv rather than importing from the source tree.

### PyO3-Specific Testing

The Rust unit/integration suite cannot fully cover the FFI seam. Several classes of bug only manifest after the wheel
is built and imported:

- abi3 forward compatibility: the wheel claims compatibility with CPython 3.12+ via `abi3-py312`, so smoke tests should
  ideally run on at least 3.12 and the latest stable 3.x.
- Panic-to-exception mapping: a Rust `panic!` on the PyO3 boundary should surface as `pyo3_runtime.PanicException` (or a
  mapped Python exception). A targeted test that intentionally triggers a panic and asserts the exception class is
  cheap and prevents accidental aborts.
- Error class mapping: SASE's `parse_query("(")` test already asserts `ValueError`; add similar checks for each error
  class the binding exposes, so the public Python contract is in CI.
- GIL behavior: any function that releases the GIL via `Python::allow_threads` should have a Python-side concurrency
  test that calls it from multiple threads to confirm the release is correct.
- Reference-cycle / leak smoke: build with `PYTHONMALLOC=debug` for one CI run, exercise the binding, and check there
  are no debug-allocator complaints. This catches a class of bugs that release-mode tests will not.

Add a `tests/python/` directory under `crates/sase_core_py/` for Python-side parity tests, and run them as a separate CI
step after the wheel-smoke install:

```bash
/tmp/smoke/bin/pip install pytest hypothesis
/tmp/smoke/bin/pytest crates/sase_core_py/tests/python -q
```

`hypothesis` (Python's property-based tester) pairs naturally with `proptest` on the Rust side: the same generators can
be expressed in both, with the Python side asserting parity against a Python reference implementation.

### Python Type Stubs

Because `sase_core_rs` is consumed from typed Python in the sase repo, the binding should ship a `py.typed` marker and
a `.pyi` stub file. Without stubs, every Python caller using mypy/pyright will see `Any` and lose type safety.

Recommendations:

- Author stubs by hand for now (the surface is small) and check them into `crates/sase_core_py/python/sase_core_rs/`.
- Include both `__init__.pyi` and `py.typed` in the wheel via `pyproject.toml` `tool.maturin` config.
- Add a CI step that runs `mypy --strict` against a tiny `tests/python/typing_smoke.py` that imports and uses each
  exported symbol. This makes stub regressions visible.
- Optionally evaluate `pyo3-stubgen` for autogeneration, but treat its output as a starting draft, not a contract.

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

`release.yml` already builds the Linux/macOS/Windows wheel matrix plus an sdist on tag push. To make it ready for an
"excellent" target:

- Add a `needs: [rust-checks, wheel-smoke]` gate so a tag never publishes without the PR-style checks succeeding on the
  same SHA.
- Run `cargo-semver-checks` for `sase_core` once it is published to crates.io. The action is designed to check public
  API semver compatibility against the latest published normal crate version before publishing. It is less relevant to
  the private PyO3 crate.
- Switch the PyPI publish step from a long-lived `PYPI_API_TOKEN` secret to PyPI Trusted Publishing (OIDC). PyPI and
  PyPA `gh-action-pypi-publish` support Trusted Publishing; it removes the rotating-secret class of leak entirely.
- Verify `cargo-public-api` diffs as a non-blocking PR comment for `sase_core`. This complements `cargo-semver-checks`
  by showing a human-readable surface diff even when no semver violation occurs.

### GitHub Actions Hardening

Independent of the Rust content, the workflow file itself benefits from supply-chain hardening:

- Pin third-party actions to commit SHAs, not floating tags. A v2 tag can be repointed by the action owner; a SHA
  cannot. Tools like `pinact` or `dependabot` (with `version-update: "all"`) automate the pin/upgrade cycle.
- Set `permissions:` at the workflow or job level to least privilege. Default `contents: read`; the publish job needs
  `id-token: write` for Trusted Publishing.
- Add `step-security/harden-runner` at the start of each job to detect outbound network calls to unexpected hosts.
- Enable `concurrency: { group: "${{ github.workflow }}-${{ github.ref }}", cancel-in-progress: true }` on PR
  workflows to free runner minutes.
- Set `RUST_BACKTRACE=short` for test jobs so failures include a backtrace without flooding logs.

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

### Snapshot Testing for Wire Formats

The `insta` crate is the right tool for SASE's serialized JSON shapes (the `python_wire_parity.rs`, `bead_*_parity.rs`,
`agent_scan_parity.rs`, and `golden_corpus_parity.rs` suites are essentially hand-rolled snapshot checks today). `insta`
provides:

- Inline (`assert_snapshot!`) or external `.snap` files committed to the repo and reviewable in PRs.
- A `cargo insta review` workflow for accepting intended changes.
- `INSTA_UPDATE=no` in CI so unintended snapshot changes fail loudly.
- `cargo-insta` integration with `nextest` for fast runs.

Recommended adoption pattern:

- Convert one parity suite (e.g. `python_wire_parity.rs`) as a pilot to validate the diff ergonomics.
- Use `insta::with_settings!` with sorted maps and stable redactions for fields like timestamps or random IDs.
- Set `INSTA_UPDATE=no INSTA_FORCE_PASS=0` in CI; `cargo nextest run` honors these env vars.

A typical snapshot test:

```rust
#[test]
fn agent_scan_emits_expected_shape() {
    let out = sase_core::agent_scan::scan(fixture("two_agents")).unwrap();
    insta::assert_json_snapshot!(out, {
        ".agents[].started_at" => "[timestamp]",
        ".agents[].artifact_root" => "[path]",
    });
}
```

Snapshot tests pair well with the `cargo insta pending-snapshots` GitHub Actions check, which fails CI when a PR
introduces `*.snap.new` files (i.e. an unaccepted snapshot change).

### Sanitizers and Miri for the FFI Boundary

The PyO3 binding has `unsafe` blocks. `cargo test --workspace` cannot detect undefined behavior in unsafe Rust; that
needs sanitizer or Miri runs.

Recommendations:

- Schedule (not required per PR): run Miri against the pure-Rust crate.
  ```bash
  rustup +nightly component add miri
  cargo +nightly miri test -p sase_core --locked
  ```
  Miri does not work through the PyO3 FFI boundary — it cannot execute foreign code — so it should target `sase_core`
  only. It still catches a meaningful class of UB in pure-Rust modules (slice OOB, use-after-free in `unsafe`,
  uninit reads).
- Schedule: run AddressSanitizer on the Python wheel build for one platform.
  ```bash
  RUSTFLAGS="-Z sanitizer=address" \
    cargo +nightly test -p sase_core --target x86_64-unknown-linux-gnu
  ```
  This catches FFI-side memory bugs that Miri cannot.
- Track the `unsafe` block count over time. Adding a `#![deny(unsafe_op_in_unsafe_fn)]` at the binding crate root
  enforces explicit `unsafe { ... }` blocks inside `unsafe fn`, which is the modern idiom and improves audit clarity.

### Mutation Testing

`cargo-mutants` injects small mutations (changing operators, returning defaults) and re-runs the test suite. A
"surviving" mutant means the suite would not have caught that real bug. It is too slow to run on every PR but is
high-value as a scheduled job, especially for parser/evaluator code where coverage percentage often overstates actual
test quality.

Recommended scheduled invocation:

```bash
cargo mutants --workspace --in-place --jobs 4 --timeout 90 --no-shuffle
```

Start with `--package sase_core --file 'src/query/**'` to scope to high-leverage modules; expand once the team is
comfortable interpreting results.

### Benchmark Regressions

For a backend that needs to match Python latency expectations, regressions should be visible. `criterion` is the
de-facto Rust benchmarking crate; pair it with one of:

- `bencher.dev` or `codspeed-io/codspeed-rust` for hosted regression tracking with PR comments.
- `iai-callgrind` for instruction-count-based benchmarks (deterministic across noisy CI runners; complementary to
  wall-clock criterion).

Do not gate PRs on benchmark wall-clock numbers from shared GitHub-hosted runners — the noise floor is too high. Either
gate on instruction counts (iai/iai-callgrind) or treat wall-clock benches as informational with a hosted comparison
service.

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

- Confirm `release.yml` requires PR checks via `needs:` before the publish job runs.
- Add `cargo-semver-checks` and `cargo-public-api` against the latest published version.
- Add scheduled latest-dependency tests (`cargo update && cargo test`) and a scheduled rerun of `release.yml`'s wheel
  matrix to catch upstream `manylinux` regressions before tag day.
- Switch PyPI publish to Trusted Publishing.

### Phase 6: Local-CI Parity

- Add a `justfile` (or `xtask` Cargo binary) at the `sase-core` repo root that wraps the same commands CI runs:
  `just fmt`, `just clippy`, `just test`, `just deny`, `just docs`. Both CI and local runs invoke the same recipes,
  which removes the "passes locally, fails in CI" class of failure.
- Document `just check` (the umbrella target) in the README so first-time contributors and agents have one entry point.

### Phase 7: Snapshots, Mutations, and FFI Sanitizers

- Migrate one parity suite to `insta` snapshots and add the pending-snapshot CI check.
- Add a scheduled `cargo mutants` run scoped to the parser/evaluator modules.
- Add a scheduled Miri job for `sase_core` and a scheduled AddressSanitizer job for the FFI surface.

## Open Decisions

- Should every PR test Linux/macOS/Windows, or should non-Linux run on push/schedule only?
- Is `rust-version = "1.78"` a hard contract for the PyO3 crate too, or only for `sase_core`?
- Should advisory failures block PRs immediately, or start as scheduled triage?
- Should coverage have thresholds, or remain an informational trend until the Rust migration stabilizes?
- Should `sase-core` expose a repo-local `just check` equivalent so CI and local agents run the same command?
- Should snapshot tests live alongside parity tests (one suite per concern, same file) or in a parallel `*_snapshots.rs`
  file? The first is easier to navigate; the second makes the migration mechanical.
- Should the binding's `unwrap_used` Clippy lint be `warn` or `deny`? `deny` improves the FFI seam (panics become
  exceptions on the Python side rather than aborts) but requires a one-time audit pass.
- Are Python type stubs hand-authored or generated? Hand-authored is more accurate for the small surface today, but a
  generator pays off if the surface grows.
- Pin third-party GitHub Actions to SHAs immediately, or wait until `dependabot` is configured to keep them current?

## Sources

Primary project documentation:

- Rust Cargo Book, Continuous Integration:
  https://doc.rust-lang.org/cargo/guide/continuous-integration.html
- Rust Cargo Book, `cargo test`:
  https://doc.rust-lang.org/cargo/commands/cargo-test.html
- Cargo Book, workspace lints (`[workspace.lints]`):
  https://doc.rust-lang.org/cargo/reference/workspaces.html#the-lints-table
- Clippy Documentation, Continuous Integration:
  https://doc.rust-lang.org/clippy/continuous_integration/index.html
- Clippy Documentation, configuration (`clippy.toml`, `msrv`):
  https://doc.rust-lang.org/clippy/configuration.html

Test runners and coverage:

- cargo-nextest docs:
  https://nexte.st/
- cargo-nextest configuration reference:
  https://nexte.st/docs/configuration/
- cargo-llvm-cov README:
  https://github.com/taiki-e/cargo-llvm-cov

Dependency policy and supply chain:

- cargo-deny checks:
  https://embarkstudios.github.io/cargo-deny/checks/index.html
- cargo-machete README:
  https://github.com/bnjbvr/cargo-machete
- cargo-hack README:
  https://github.com/taiki-e/cargo-hack
- cargo-semver-checks GitHub Action:
  https://github.com/obi1kenobi/cargo-semver-checks-action
- cargo-public-api:
  https://github.com/cargo-public-api/cargo-public-api

Snapshot, mutation, and unsafe testing:

- insta snapshot testing:
  https://insta.rs/docs/
- cargo-mutants book:
  https://mutants.rs/
- Miri (Rust UB detector):
  https://github.com/rust-lang/miri
- Rustc unstable book, sanitizers:
  https://doc.rust-lang.org/unstable-book/compiler-flags/sanitizer.html

PyO3 / Python wheel:

- PyO3 maturin-action README:
  https://github.com/PyO3/maturin-action
- PyO3 user guide, building and distribution:
  https://pyo3.rs/main/building-and-distribution
- maturin user guide:
  https://www.maturin.rs/
- PyPA `gh-action-pypi-publish` (Trusted Publishing):
  https://github.com/pypa/gh-action-pypi-publish
- PyPI Trusted Publishers documentation:
  https://docs.pypi.org/trusted-publishers/

GitHub Actions hardening:

- step-security/harden-runner:
  https://github.com/step-security/harden-runner
- OpenSSF Scorecard guidance on pinning Actions:
  https://github.com/ossf/scorecard/blob/main/docs/checks.md#pinned-dependencies

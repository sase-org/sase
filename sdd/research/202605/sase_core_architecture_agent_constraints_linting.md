# SASE Core Architecture, Agent Constraints, and Rust Linting

Date: 2026-05-15

## Question

What should `../sase-core` add so Rust changes are easier for agents and Python-first contributors to keep architecturally
clean?

This is a second-pass note after `sdd/research/202605/sase_core_rust_ci_lint_test_research.md`. That earlier note
covered the general CI/test stack. This one focuses on architecture constraints, agent instructions, and lint policy
that encode SASE-specific boundaries.

## Executive Summary

The highest-value improvement is to make `sase-core`'s architecture explicit in three places:

1. A repo-local `AGENTS.md` that tells agents what each crate owns, what must not cross crate boundaries, and what
   checks to run.
2. Workspace lint policy in `Cargo.toml` plus a small `clippy.toml`, starting with low-churn lints that protect real
   invariants.
3. Dependency and API guardrails: `cargo-deny`, `cargo-machete`, doc warnings, and public API review for library
   crates.

Do **not** start by enabling broad `clippy::pedantic`, `clippy::unwrap_used`, or `clippy::expect_used` across the whole
workspace. The current code has many intentional test unwraps and parser/assertion unwraps, so that would create churn
before it creates architecture. Use targeted restrictions first.

## Current `sase-core` State

Repository inspected: `../sase-core`.

Workspace crates:

- `crates/sase_core`: shared Rust backend/domain crate. It has parser/query/bead/status/notification/agent logic and
  is deliberately PyO3-free.
- `crates/sase_core_py`: PyO3 extension crate exposing `sase_core_rs`.
- `crates/sase_gateway`: local HTTP gateway for mobile clients.
- `crates/sase_xprompt_lsp`: xprompt language server.

Existing guardrails:

- `rust-toolchain.toml` pins stable Rust with `rustfmt` and `clippy`.
- CI runs `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  `cargo test --workspace`, and a maturin wheel smoke.
- `rustfmt.toml` sets `max_width = 80`.
- `sase_xprompt_lsp` already has `#![deny(clippy::print_stdout)]`.

Gaps:

- No `../sase-core/AGENTS.md`.
- No workspace `[workspace.lints]` / per-crate `[lints] workspace = true`.
- No `clippy.toml`.
- No `deny.toml`.
- No `Justfile` in `sase-core`; contributors use raw Cargo commands or the sibling Python repo's `just rust-*`
  commands.
- No public API diff/review gate.

Local observations:

- `rg` found `unsafe` only in `crates/sase_core_py/src/lib.rs`, in Unix process/session handling:
  `pre_exec`/`setsid` and `libc::kill`. That makes `unsafe_code` a good architectural boundary: forbid it in pure
  library/server/LSP crates, allow and document it narrowly in the PyO3 binding.
- `cargo tree -d` shows duplicate versions for `base64`, `bitflags`, `getrandom`, `hashbrown`, `http`,
  `http-body`, `hyper`, `socket2`, `sync_wrapper`, and `thiserror`. Most are caused by the `reqwest 0.11` stack
  living beside the newer `axum 0.7`/`hyper 1` stack. This is a dependency hygiene target, not an emergency.
- `serde_yaml v0.9.34+deprecated` is a direct dependency of `sase_core` and is used in `xprompt_catalog.rs`. Treat it
  as a planned dependency replacement, because new YAML work should not deepen reliance on it.

## Primary Sources Checked

- Cargo documents `[workspace.lints]` as the shared lint policy table inherited by workspace members with
  `[lints] workspace = true`; it is respected as of Rust 1.74:
  https://doc.rust-lang.org/cargo/reference/workspaces.html#the-lints-table
- Clippy documents `clippy.toml`, MSRV configuration, Cargo lint tables, and warns that `clippy::pedantic` is
  aggressive and prone to false positives:
  https://doc.rust-lang.org/stable/clippy/configuration.html
- Clippy supports configured `disallowed-methods`, `disallowed-macros`, `disallowed-types`, and related project-specific
  restriction lints:
  https://rust-lang.github.io/rust-clippy/stable/index.html#disallowed_methods
- The `unsafe_code` rustc lint catches unsafe blocks and unsafe-adjacent constructs such as `no_mangle`,
  `export_name`, and `link_section`:
  https://doc.rust-lang.org/stable/nightly-rustc/rustc_lint/builtin/static.UNSAFE_CODE.html
- The Rust 2024 edition guide explains `unsafe_op_in_unsafe_fn`; it separates the obligation of calling an unsafe
  function from the explicit block that performs an unsafe operation:
  https://doc.rust-lang.org/edition-guide/rust-2024/unsafe-op-in-unsafe-fn.html
- cargo-deny checks dependency graph policy: licenses, bans/duplicates, advisories, and sources:
  https://embarkstudios.github.io/cargo-deny/checks/index.html
- cargo-deny license policy denies licenses not explicitly allowed:
  https://embarkstudios.github.io/cargo-deny/checks/licenses/cfg.html
- cargo-nextest supports repo-local `.config/nextest.toml` profiles, including CI profiles:
  https://nexte.st/docs/configuration/
- cargo-machete is fast but imprecise unused-dependency detection and supports metadata/ignore configuration:
  https://github.com/bnjbvr/cargo-machete
- Rust API Guidelines recommend documenting errors, panics, and safety considerations and using `?` instead of `unwrap`
  in examples:
  https://rust-lang.github.io/api-guidelines/checklist.html
- cargo-public-api can list and diff public Rust library APIs, but currently relies on nightly rustdoc JSON:
  https://github.com/cargo-public-api/cargo-public-api
- cargo-semver-checks is useful but still has known cross-crate item limitations according to Rust project-goal
  tracking:
  https://rust-lang.github.io/rust-project-goals/2025h2/cargo-semver-checks.html
- RustSec marks `yaml-rust` unmaintained and recommends `yaml-rust2`; the `serde_yaml` ecosystem has also moved into
  deprecated/forked territory, so YAML dependency choice needs explicit review:
  https://rustsec.org/advisories/RUSTSEC-2024-0320.html

## Recommended Architecture Contract

Use crate boundaries as the main architecture enforcement mechanism:

| Crate | Owns | Should not own |
| --- | --- | --- |
| `sase_core` | Deterministic domain behavior, wire structs, parsers, state machines, storage rules, parity-critical behavior. | PyO3 types, HTTP route shape, LSP protocol state, UI-only concerns. |
| `sase_core_py` | Python conversion, PyO3 error mapping, Python extension exports, unavoidable binding/FFI/process glue. | New domain logic that can live in `sase_core`; JSON shape decisions not mirrored by core wire structs. |
| `sase_gateway` | Mobile HTTP routes, daemon config, local gateway storage/push/session concerns. | Parser/query/bead/status logic that a CLI/TUI/editor client would need to match. |
| `sase_xprompt_lsp` | LSP protocol adaptation and diagnostics/completion presentation. | Catalog parsing rules that can live in `sase_core`; gateway or Python binding behavior. |

Agent-facing rule of thumb:

If Python, mobile, LSP, CLI, or future WASM clients need the behavior to match, put the behavior in `sase_core`, expose
it through wire structs, and add parity/contract tests. Adapter crates should translate transport/runtime shape only.

## Suggested `AGENTS.md` for `../sase-core`

The repo should have its own `AGENTS.md` so agents do not rely on the Python repo's memory. Suggested content:

```markdown
# SASE Core Agent Instructions

This repo is the Rust backend/domain boundary for SASE.

## Crate Ownership

- `crates/sase_core`: shared deterministic domain logic and wire contracts. Keep this PyO3-free, HTTP-free, and UI-free.
- `crates/sase_core_py`: PyO3 adapter only. Prefer converting to/from `sase_core` wire types over adding behavior here.
- `crates/sase_gateway`: mobile gateway transport, daemon, routes, local gateway storage, and push/session behavior.
- `crates/sase_xprompt_lsp`: LSP transport/presentation only. Reuse `sase_core` for catalog parsing and diagnostics rules.

If multiple clients must agree on behavior, it belongs in `sase_core`.

## Wire and Parity Rules

- Preserve JSON wire shapes unless deliberately versioning a contract.
- Keep `schema_version` fields explicit.
- Do not omit nullable fields if Python wire dataclasses expect `null`.
- Add/update parity fixtures when behavior mirrors Python.

## Safety and Dependencies

- Do not add `unsafe` outside the binding/FFI boundary without an explicit design note.
- Do not add new direct dependencies without checking existing workspace dependencies and license/security impact.
- Do not add new `serde_yaml` usage; prefer a planned YAML replacement decision.

## Checks

Run before handoff when touching Rust code:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
```

Run dependency/API checks when dependency or public API surfaces change:

```bash
cargo deny check --locked
cargo machete
RUSTDOCFLAGS="-D warnings" cargo doc --workspace --no-deps --locked
```
```

## Workspace Lint Policy

Start with low-churn lints that encode boundaries. Example workspace root additions:

```toml
[workspace.lints.rust]
rust_2018_idioms = "warn"
unreachable_pub = "warn"
unsafe_op_in_unsafe_fn = "deny"
missing_debug_implementations = "warn"

[workspace.lints.rustdoc]
broken_intra_doc_links = "deny"
bare_urls = "warn"

[workspace.lints.clippy]
all = { level = "warn", priority = -1 }
dbg_macro = "warn"
todo = "warn"
unimplemented = "warn"
print_stdout = "warn"
print_stderr = "warn"
disallowed_methods = "warn"
disallowed_macros = "warn"
disallowed_types = "warn"
```

Then each crate opts in:

```toml
[lints]
workspace = true
```

Crate-specific safety policy:

```rust
// crates/sase_core/src/lib.rs
#![forbid(unsafe_code)]

// crates/sase_gateway/src/lib.rs
#![forbid(unsafe_code)]

// crates/sase_xprompt_lsp/src/lib.rs
#![forbid(unsafe_code)]

// crates/sase_core_py/src/lib.rs
#![deny(unsafe_op_in_unsafe_fn)]
```

Do **not** use `#![forbid(unsafe_code)]` in `sase_core_py` unless the current Unix process code is redesigned. Instead,
require short `// SAFETY:` comments around its two existing unsafe blocks.

## Suggested `clippy.toml`

Use `clippy.toml` for project-specific policy rather than broad style ideology:

```toml
msrv = "1.78"

disallowed-macros = [
  { path = "std::dbg", reason = "debug output must not land in core/library code" },
  { path = "std::println", reason = "use tracing/logging at process boundaries; libraries should return structured data" },
  { path = "std::eprintln", reason = "use tracing/logging at process boundaries; libraries should return structured errors" },
]

disallowed-methods = [
  { path = "std::env::set_var", reason = "process-global mutation is unsafe for parallel tests; pass env through Command/test helpers" },
  { path = "std::env::remove_var", reason = "process-global mutation is unsafe for parallel tests; pass env through Command/test helpers" },
]
```

Add type restrictions later only when SASE has a clear invariant. Example: if JSON field order must remain deterministic,
prefer linting or review rules that keep public wire maps as `BTreeMap` rather than ad hoc `HashMap`, but do not ban
`HashMap` globally without checking performance-sensitive indexes first.

## Dependency Policy

Add `deny.toml` and gate it in CI. Initial stance:

- Allow `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `Unicode-3.0`, and narrow exceptions discovered by
  the first run.
- Deny wildcard dependency requirements.
- Warn, then later deny, duplicate crate versions after the `reqwest 0.11` / `hyper 0.14` stack is addressed.
- Allow only `crates.io` and the local workspace as sources unless a change explicitly adds a git dependency.
- Run advisories in PR and on a schedule; use explicit ignored advisories with reasons and dates.

The current duplicate dependency output is mostly expected from mixed HTTP stacks. The clean architectural move is to
eventually update `reqwest` to a version aligned with `hyper 1`/newer `rustls`, not to paper over the duplicates forever.

`cargo machete` should be a periodic or dependency-PR check. It is intentionally fast/imprecise, so keep false-positive
ignores in Cargo metadata with comments.

## Public API Constraints

For `sase_core`, public API is not just "published crate API"; it is also the API used by PyO3, gateway, LSP, and Python
parity tests. Recommended layers:

1. Keep public exports centralized in `src/lib.rs` so public surface review is mechanical.
2. Add `RUSTDOCFLAGS="-D warnings" cargo doc --workspace --no-deps --locked` to catch broken docs and links.
3. Add `cargo public-api` or `cargo-semver-checks` as a review tool before release. Prefer public API diffs for PR
   review because the crate is still young and not every public change is a semver violation yet.
4. Once `sase_core` is published or treated as stable by external crates, add `cargo-semver-checks` to release CI.

## YAML Dependency Note

`sase_core` currently uses `serde_yaml` for xprompt/config catalog parsing. Because `serde_yaml` is deprecated/forked and
YAML parser maintenance is unsettled, architecture constraints should say:

- No new `serde_yaml` call sites.
- Keep YAML parsing centralized in `xprompt_catalog.rs` or a future `yaml` adapter module.
- Before adding advanced YAML behavior, evaluate `serde-saphyr`, `serde_yaml_ng`/`serde_norway`, and `yaml-rust2` against
  SASE's actual files and malformed-input behavior.
- Add a small compatibility fixture suite before swapping parser crates.

## Prioritized Implementation Plan

1. Add `../sase-core/AGENTS.md` with crate ownership, wire contract, dependency, unsafe, and check rules.
2. Add `[workspace.lints]` and `[lints] workspace = true` to all crate manifests.
3. Add `#![forbid(unsafe_code)]` to non-FFI crates; add `// SAFETY:` comments and `unsafe_op_in_unsafe_fn = "deny"` for
   `sase_core_py`.
4. Add `clippy.toml` with MSRV and targeted `disallowed-*` restrictions.
5. Add `deny.toml`, start duplicate crates as `warn`, and gate licenses/sources/advisories/bans.
6. Add `cargo machete` as a dependency hygiene check, with explicit metadata ignores only after review.
7. Add rustdoc warnings and public API diff tooling.
8. Plan a YAML dependency migration spike with compatibility fixtures.

## Architecture Fitness Tests (Executable Boundary Enforcement)

`AGENTS.md` and Clippy restrictions describe the boundary; only an executable check actually defends it. The Rust
ecosystem standard for this is `cargo metadata` introspection from an `xtask` crate or a workspace integration test.
The advantage over comment-based rules: an agent that adds `pyo3` to `sase_core`'s dependencies will get a red CI run,
not a polite review note.

Concrete pattern: add a `crates/sase_arch_tests` integration crate (or a `tests/architecture.rs` file in a small
`xtask` binary) that parses `cargo metadata --format-version=1` and asserts:

```rust
// pseudo-sketch — uses the `cargo_metadata` crate
#[test]
fn sase_core_has_no_adapter_dependencies() {
    let md = cargo_metadata::MetadataCommand::new().exec().unwrap();
    let banned = ["pyo3", "axum", "hyper", "tower-lsp-server", "lsp-types", "reqwest"];
    let core = md.packages.iter().find(|p| p.name == "sase_core").unwrap();
    let resolved = resolve_transitive(&md, &core.id);
    for pkg in resolved {
        assert!(
            !banned.contains(&pkg.name.as_str()),
            "sase_core must not transitively depend on {}", pkg.name,
        );
    }
}

#[test]
fn sase_gateway_does_not_re_export_pyo3() {
    // Read crate manifest and assert no `pyo3` direct dep, etc.
}
```

Run this as a regular workspace test so it gates every PR. The `cargo_metadata` crate is the standard programmatic
interface to Cargo's resolver output:
https://docs.rs/cargo_metadata/latest/cargo_metadata/

For richer module-level enforcement, `cargo-modules` can produce a textual or DOT module graph that an `xtask` can
diff against a checked-in expected graph:
https://github.com/regexident/cargo-modules

This converts "do not let `parser::*` call into `gateway::*`" from a review heuristic into a snapshot test. Treat the
checked-in graph the same way as `insta` snapshots: changes are visible in PR diffs and require explicit acceptance.

## Feature Layering and "Compiles Without Adapters" Gate

The boundary policy in `AGENTS.md` is only meaningful if `sase_core` actually builds without PyO3, HTTP, or LSP
features even when the workspace has them. Add explicit CI matrix entries:

```bash
cargo check -p sase_core --locked --no-default-features
cargo check -p sase_core --locked --all-features
cargo check -p sase_core --locked --target x86_64-unknown-linux-gnu
# Optional once a wasm port is on the roadmap:
cargo check -p sase_core --locked --target wasm32-unknown-unknown
```

These four jobs make accidental coupling visible. If `sase_core` ever stops compiling under `--no-default-features`,
or starts failing for `wasm32`, an agent has implicitly pulled in a platform-specific dependency from a sibling crate.

Use Cargo features at crate boundaries rather than at the workspace level for adapter-only behavior. For example, any
serde-feature-gated wire helpers belong behind a `serde` feature on the producing crate, not a workspace-wide
default. The Cargo reference's feature documentation covers default-feature pitfalls and the recommended additive
pattern: https://doc.rust-lang.org/cargo/reference/features.html

## Workspace Dependency Unification (`cargo-hakari`)

The duplicate `base64`/`bitflags`/`getrandom`/`hashbrown`/`http`/`http-body`/`hyper`/`socket2`/`sync_wrapper`/
`thiserror` versions reported earlier are the kind of feature-resolution drift that `cargo-hakari` is designed to
solve. It generates a small synthetic `workspace-hack` crate that depends on the union of features each member uses,
which forces Cargo's feature unifier to resolve a single version per crate where possible.

Reference: https://docs.rs/cargo-hakari/latest/cargo_hakari/

Recommended adoption stance for `sase-core`:

- Add a `workspace-hack` member after the `reqwest 0.11 -> 0.12` / `hyper 0.14 -> 1` migration is decided. Doing it
  before that swap will just freeze the wrong unified versions.
- Gate `cargo hakari generate --diff` in CI so regressions in feature unification are caught at the source.
- Keep `cargo machete` allowed to ignore the hack crate explicitly; both tools will otherwise fight each other on the
  hack crate manifest.

This is the architectural mate to the `bans.multiple-versions = "warn" -> deny"` ramp described in the dependency
policy section.

## Wire-Contract API Constraints

`sase_core`'s public types are simultaneously a Rust library API, a JSON wire format, and a parity contract with
Python. The Rust attributes that encode that are:

- `#[non_exhaustive]` on every public enum and any public struct whose set of fields may grow. This forces external
  matchers to use `_ => ...` arms and external constructors to use builders, so adding a new variant or field is not
  an SemVer break. Rust reference: https://doc.rust-lang.org/reference/attributes/type_system.html
- `#[must_use]` on builders, parser handles, transactions, and any `Result`-shaped wire return that is easy to drop
  silently: https://doc.rust-lang.org/reference/attributes/diagnostics.html#the-must_use-attribute
- `#[serde(deny_unknown_fields)]` should be applied deliberately, not by default: it makes the wire format strict in
  one direction (Python may not invent fields) but breaks forward compatibility for new Rust producers feeding older
  Rust consumers. Pick one direction per wire type explicitly. Serde docs:
  https://serde.rs/container-attrs.html#deny_unknown_fields
- `#[serde(default)]` and explicit `Option<T>` for newly added fields, so older payloads still parse.
- `#[deprecated(since = "...", note = "...")]` on items that will be removed at the next compatible release, paired
  with `cargo-semver-checks` so removal is gated.

These are non-negotiable for a crate whose JSON shape is a contract with Python; the `[lints]` block cannot enforce
them, so add a short checklist in `AGENTS.md` under "Wire and Parity Rules" naming each attribute.

## Error-Handling Architecture

Mix-ups between library and binary error styles are one of the most common Rust review notes for Python-first
contributors. Encode the convention once:

- `sase_core`, `sase_core_py`, `sase_gateway`, and `sase_xprompt_lsp` are all library-style for the purposes of error
  types: each public failure mode should be a `thiserror`-derived enum with explicit variants, not `anyhow::Error`.
  Reference: https://docs.rs/thiserror/latest/thiserror/
- `anyhow` is acceptable inside binaries, examples, and tests where call-site ergonomics dominate over caller error
  inspection. Reference: https://docs.rs/anyhow/latest/anyhow/
- Add a Clippy disallowed-type entry for `anyhow::Error` in `sase_core` once the boundary is clean:
  ```toml
  # clippy.toml (per-crate override is unsupported; gate via crate-level
  # `#![deny(clippy::disallowed_types)]` plus a workspace clippy.toml entry
  # tagged with `replacement = "use thiserror enum instead"`).
  ```
- Error variants that cross the PyO3 boundary must round-trip cleanly to a Python exception class. Document the
  mapping in `crates/sase_core_py/src/errors.rs` and add a parity test that asserts each Rust variant produces the
  expected Python class. PyO3 exception mapping:
  https://pyo3.rs/main/exception
- Avoid `Box<dyn std::error::Error>` in public signatures; prefer a concrete enum so callers can match on
  classifications without downcasts.

## PyO3 0.22 Bound API and Unsafe Boundary Policy

The binding currently pins `pyo3 = "0.22"`. That version has the `Bound<'py, T>` API stable and the older "GIL Ref"
API (`&'py PyAny`, etc.) deprecated behind a `gil-refs` feature flag, scheduled for removal in 0.23. Reference:
https://pyo3.rs/main/migration

Architecture rules to encode now (so a future 0.23 bump is mechanical):

- New PyO3 code must use `Bound<'py, T>` and `Py<T>` exclusively; no `&PyAny` patterns. Add this to `AGENTS.md` under
  "Safety and Dependencies."
- Do not enable the `gil-refs` feature in `sase_core_py`; let the compiler force migration of any leftover call
  sites.
- `Python::with_gil` is preferred over functions taking `Python<'py>` directly except where a function is already
  inside a `#[pymethods]` impl. This keeps GIL acquisition explicit at the boundary.
- Any `Python::allow_threads` block must have a comment naming the Rust-side computation that is GIL-safe to release
  for, plus a test that exercises it under contention.
- The two existing `unsafe` blocks (`pre_exec`/`setsid` and `libc::kill`) should each have a `// SAFETY:` block
  citing POSIX semantics and the `libc` invariant. Rust's API Guidelines explicitly call this out:
  https://rust-lang.github.io/api-guidelines/documentation.html#c-failure
- Pair `#![deny(unsafe_op_in_unsafe_fn)]` with `#![warn(clippy::undocumented_unsafe_blocks)]` so any new unsafe block
  without a `// SAFETY:` comment becomes a Clippy warning. Reference:
  https://rust-lang.github.io/rust-clippy/master/index.html#undocumented_unsafe_blocks

## `rusqlite` and Persistence Boundary

`sase_core` currently depends directly on `rusqlite` with the `bundled` feature. That mixes domain logic with a
specific storage technology, and bundles SQLite into every consumer crate. For mobile, WASM, or in-memory testing
clients, this is a friction point.

Options worth recording (decision can be deferred):

- Status quo: keep `rusqlite` in `sase_core` and treat the storage adapter as part of the domain. Document that
  `sase_core` is opinionated about SQLite as the wire/persistence layer.
- Trait boundary: define a `BeadStore` / `ChangeSpecStore` trait inside `sase_core` and put the `rusqlite`
  implementation behind a `sqlite` feature, defaulted on. Other consumers can implement the trait.
- Adapter crate: move `rusqlite` use into `crates/sase_storage_sqlite`, leaving `sase_core` storage-agnostic. This
  matches the boundary pattern the existing note recommends for PyO3 and HTTP.

`rusqlite` upstream: https://docs.rs/rusqlite/latest/rusqlite/

The wasm-target check from the feature-layering section is the simplest fitness check that flags this coupling: a
`wasm32` build will fail until `rusqlite` is feature-gated or moved.

## Local Enforcement Parity (`xtask` and Pre-Commit)

The previous note recommended a `justfile` for local-CI parity. An equivalent that some Rust teams prefer is an
`xtask` crate, which keeps automation in Rust rather than a separate tool:
https://github.com/matklad/cargo-xtask

Either is fine; pick one and stick to it. Concrete recipes the workspace needs in addition to the CI list:

- `cargo xtask arch-check` (or `just arch-check`): runs the architecture fitness tests above plus
  `cargo check -p sase_core --no-default-features`.
- `cargo xtask docs`: runs `RUSTDOCFLAGS="-D warnings" cargo doc --workspace --no-deps --locked`.
- `cargo xtask py-parity`: builds the wheel into a venv and runs `crates/sase_core_py/tests/python/`.

For pre-commit, prefer `lefthook` over `cargo-husky`. `lefthook` is actively maintained, language-agnostic, and
trivially shareable across the SASE repos:
https://lefthook.dev/

A minimal `lefthook.yml` should run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets --locked
-- -D warnings`, and the architecture fitness test. Anything heavier (full nextest, cargo-deny advisories) belongs in
CI only.

## CODEOWNERS as an Architecture Gate

Add `.github/CODEOWNERS` with crate-level ownership:

```text
crates/sase_core/        @sase-org/core-maintainers
crates/sase_core_py/     @sase-org/python-bindings
crates/sase_gateway/     @sase-org/mobile
crates/sase_xprompt_lsp/ @sase-org/editor-integrations
AGENTS.md                @sase-org/core-maintainers
deny.toml                @sase-org/core-maintainers
clippy.toml              @sase-org/core-maintainers
Cargo.toml               @sase-org/core-maintainers
```

This is not a permission system; it is a routing system. Combined with branch-protection rules requiring an owner
review for the touched paths, it makes "PyO3 work landing in `sase_core`" structurally awkward instead of merely
discouraged.

GitHub docs: https://docs.github.com/en/repositories/managing-your-repositories-settings-and-features/customizing-your-repository/about-code-owners

## Tracing and Instrumentation Policy

The previous note correctly banned `println!`/`eprintln!`. The positive pairing is an explicit `tracing` convention:

- `sase_core`: emit `tracing` events; never configure a subscriber. The library does not own log output.
- `sase_core_py`: bridge `tracing` to Python logging via a subscriber set up at module init; document the bridge.
- `sase_gateway` and `sase_xprompt_lsp`: configure `tracing-subscriber` at startup with `env-filter`; emit one
  high-cardinality span per request/method.
- All adapter entry points (HTTP handlers, LSP method handlers, PyO3 `#[pyfunction]` boundaries) should be
  `#[tracing::instrument(skip(...))]` so failures surface with consistent context.

References:
- `tracing` crate: https://docs.rs/tracing/latest/tracing/
- `tracing-subscriber` env-filter: https://docs.rs/tracing-subscriber/latest/tracing_subscriber/

This complements the disallowed-macro list (no `println!`) by giving authors something to write *instead*.

## Concrete Duplicate-Dependency Resolution Path

The duplicate-version warning is a specific symptom: `reqwest 0.11` brings `hyper 0.14`/`http 0.2`, while `axum 0.7`
uses `hyper 1`/`http 1`. The clean resolution is to move `reqwest` to `0.12`, which uses `hyper 1`/`http 1` and
`rustls 0.23`. Reference:
https://github.com/seanmonstar/reqwest/blob/master/CHANGELOG.md

Suggested sequence so the duplicate-deps gate can ramp from `warn` to `deny`:

1. Audit current `reqwest` call sites and TLS configuration.
2. Bump to `reqwest = "0.12"` with whatever TLS backend SASE prefers (`rustls-tls` is the default for most server
   deployments).
3. Re-run `cargo tree -d`. Most other duplicates should resolve as a side effect.
4. Update `deny.toml` to set `bans.multiple-versions = "deny"`.
5. Then introduce `cargo-hakari`.

## Bottom Line

For this repo, architecture will come more from explicit ownership boundaries and narrow policy lints than from stricter
style lints. The first implementation should make it hard for agents to put PyO3, HTTP, or LSP behavior into the core
wrongly; then dependency/API tooling can keep the Rust workspace honest as it grows.

The second-pass additions tighten that approach in three ways: a `cargo metadata`-driven architecture fitness test
makes boundary violations a red CI run instead of a review comment; explicit feature-layering and a `--no-default-
features` check prevent adapter dependencies from drifting into `sase_core`; and wire-contract attributes
(`#[non_exhaustive]`, `#[must_use]`, deliberate `serde` attributes) plus a clean `thiserror`/`anyhow` split protect
the SASE Python parity contract at the type level. PyO3 0.22's `Bound<'py, T>` API and the 0.23 `gil-refs` removal
are close enough to encode now rather than during the bump.

## Sources

Cargo, Clippy, and rustc:

- Cargo `[workspace.lints]`: https://doc.rust-lang.org/cargo/reference/workspaces.html#the-lints-table
- Cargo features reference: https://doc.rust-lang.org/cargo/reference/features.html
- Clippy configuration (`clippy.toml`, MSRV): https://doc.rust-lang.org/stable/clippy/configuration.html
- Clippy `disallowed_methods`: https://rust-lang.github.io/rust-clippy/stable/index.html#disallowed_methods
- Clippy `undocumented_unsafe_blocks`:
  https://rust-lang.github.io/rust-clippy/master/index.html#undocumented_unsafe_blocks
- `unsafe_code` lint: https://doc.rust-lang.org/stable/nightly-rustc/rustc_lint/builtin/static.UNSAFE_CODE.html
- `unsafe_op_in_unsafe_fn` (2024 edition): https://doc.rust-lang.org/edition-guide/rust-2024/unsafe-op-in-unsafe-fn.html
- Rust attribute reference (`#[non_exhaustive]`, `#[must_use]`, `#[deprecated]`):
  https://doc.rust-lang.org/reference/attributes/type_system.html

Dependency policy, build, and test:

- cargo-deny: https://embarkstudios.github.io/cargo-deny/checks/index.html
- cargo-deny licenses: https://embarkstudios.github.io/cargo-deny/checks/licenses/cfg.html
- cargo-machete: https://github.com/bnjbvr/cargo-machete
- cargo-hakari: https://docs.rs/cargo-hakari/latest/cargo_hakari/
- cargo-modules: https://github.com/regexident/cargo-modules
- cargo_metadata crate: https://docs.rs/cargo_metadata/latest/cargo_metadata/
- cargo-xtask pattern: https://github.com/matklad/cargo-xtask
- cargo-nextest: https://nexte.st/docs/configuration/
- cargo-public-api: https://github.com/cargo-public-api/cargo-public-api
- cargo-semver-checks status: https://rust-lang.github.io/rust-project-goals/2025h2/cargo-semver-checks.html

Errors and serialization:

- thiserror: https://docs.rs/thiserror/latest/thiserror/
- anyhow: https://docs.rs/anyhow/latest/anyhow/
- Serde container attributes: https://serde.rs/container-attrs.html#deny_unknown_fields
- Rust API Guidelines: https://rust-lang.github.io/api-guidelines/checklist.html
- API Guidelines documentation of failure conditions:
  https://rust-lang.github.io/api-guidelines/documentation.html#c-failure

PyO3 and FFI:

- PyO3 migration guide (0.21/0.22 `Bound` API): https://pyo3.rs/main/migration
- PyO3 exceptions: https://pyo3.rs/main/exception

Persistence, HTTP, and tracing:

- rusqlite: https://docs.rs/rusqlite/latest/rusqlite/
- reqwest CHANGELOG (0.12/hyper 1 migration):
  https://github.com/seanmonstar/reqwest/blob/master/CHANGELOG.md
- tracing: https://docs.rs/tracing/latest/tracing/
- tracing-subscriber: https://docs.rs/tracing-subscriber/latest/tracing_subscriber/

Local and repo enforcement:

- lefthook: https://lefthook.dev/
- GitHub CODEOWNERS:
  https://docs.github.com/en/repositories/managing-your-repositories-settings-and-features/customizing-your-repository/about-code-owners

Security baseline:

- RustSec serde_yaml advisory context: https://rustsec.org/advisories/RUSTSEC-2024-0320.html

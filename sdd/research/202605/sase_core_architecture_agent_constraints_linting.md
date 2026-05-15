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

## Bottom Line

For this repo, architecture will come more from explicit ownership boundaries and narrow policy lints than from stricter
style lints. The first implementation should make it hard for agents to put PyO3, HTTP, or LSP behavior into the core
wrongly; then dependency/API tooling can keep the Rust workspace honest as it grows.

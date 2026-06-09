---
create_time: 2026-06-09 09:03:53
status: done
prompt: sdd/prompts/202606/release_plz_internal_dependency_versions.md
---
# Plan: Fix release-plz PR package verification

## Context

The failing GitHub Actions job is `Release-plz PR` in `sase-org/sase-core`, run `27206889681`. The `release-plz release`
job succeeded and created `v0.1.1`; wheel builds and `twine check` also succeeded. The error in this plan is the
separate `release-plz release-pr` maintenance job failure:

```text
failed to determine next versions
run cargo package
failed to verify manifest at .../crates/sase_core_py/Cargo.toml
all dependencies must have a version requirement specified when packaging.
dependency `sase_core` does not specify a version
```

## Diagnosis

`release-plz release-pr` runs Cargo package verification while determining the next release PR state. Cargo validates
the manifests that participate in packaging. For path dependencies, Cargo requires a registry version requirement too,
because packaged manifests cannot rely on local paths; the path is removed and the version is used instead.

`crates/sase_core_py/Cargo.toml` currently has:

```toml
sase_core = { path = "../sase_core" }
```

That is valid for local workspace builds, but invalid for Cargo package verification. `publish = false` does not exempt
the manifest from this validation; it only prevents publishing the crate to a registry. The same path-only dependency
shape also exists in `crates/sase_gateway/Cargo.toml` and `crates/sase_xprompt_lsp/Cargo.toml`, so fixing only the PyO3
crate would solve the immediate job but leave the same latent packaging issue elsewhere.

## Proposed Fix

Centralize the internal `sase_core` dependency in the root workspace:

```toml
[workspace.dependencies]
sase_core = { path = "crates/sase_core", version = "0.1.1" }
```

Then replace each member crate's path-only dependency with inherited workspace dependency metadata:

```toml
sase_core = { workspace = true }
```

Apply this to:

- `crates/sase_core_py/Cargo.toml`
- `crates/sase_gateway/Cargo.toml`
- `crates/sase_xprompt_lsp/Cargo.toml`

This keeps local builds using the path dependency while giving Cargo a real version requirement for package
verification. It also keeps the internal dependency version in one place instead of duplicating it in every member
manifest.

## Validation

After the manifest change:

1. Run `cargo metadata --format-version 1 --no-deps` to confirm workspace dependency inheritance resolves cleanly.
2. Run `cargo package -p sase_core --allow-dirty` to reproduce the failing Cargo package verification path locally.
3. Run `cargo package -p sase_core_py --allow-dirty` if Cargo allows packaging the unpublished PyO3 crate locally.
4. Run the repository's Rust validation path, starting with `cargo test --workspace` unless a faster documented project
   command exists.
5. Run `release-plz release-pr` in a non-mutating mode if available locally, or otherwise rely on the local
   `cargo package` reproduction plus CI after the fix is pushed.

## Non-Goals

- Do not change the release/tag state for `v0.1.1`.
- Do not change the wheel build or PyPI publish workflow as part of this fix.
- Do not address the separate PyPI Trusted Publisher failure in this change; that is external configuration and already
  distinct from the `release-plz release-pr` manifest error.

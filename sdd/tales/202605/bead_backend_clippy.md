---
create_time: 2026-05-05 11:56:25
status: wip
prompt: sdd/prompts/202605/bead_backend_clippy.md
---
# Plan: Fix bead-backend Rust clippy gate

## Context

The `bead-backend` GitHub Actions job checks out this repository plus the sibling `sase-org/sase-core` repository, then
runs `just rust-check`. In this repo's `Justfile`, `rust-check` delegates `rust-fmt-check`, `rust-clippy`, and
`rust-test` to `../sase-core`.

The failing command is:

```bash
cd ../sase-core && cargo clippy --workspace --all-targets -- -D warnings
```

The failing file is `../sase-core/crates/sase_core/src/artifact/ingest.rs`.

## Root Cause

The Rust code compiles, but the CI gate treats all clippy warnings as errors with `-D warnings`. A newer or stricter
clippy run now rejects four style issues in `artifact/ingest.rs`:

- Two loops iterate over arrays of `Option<&Path>` and then manually unwrap each item with `if let Some(...)`. Clippy's
  `manual_flatten` lint requires using `.into_iter().flatten()` for this shape.
- `non_empty` takes `&String` where `&str` is sufficient, triggering `ptr_arg`.
- One metadata default uses `unwrap_or_else(Map::new)` where `unwrap_or_default()` is equivalent and preferred.

These are mechanical lint failures, not behavioral failures in the artifact ingestion logic.

## Implementation Plan

1. Update the two optional-path loops in `ingest.rs` to iterate over flattened paths directly while preserving the same
   path set and per-path behavior.
2. Change `non_empty` to accept `&str` and return `value.to_owned()` for non-empty values.
3. Replace `request.metadata.clone().unwrap_or_else(Map::new)` with `request.metadata.clone().unwrap_or_default()`.
4. Format the Rust code with `cargo fmt --all` or the repo's `just rust-fmt` equivalent.
5. Verify the failing gate locally with `cargo clippy --workspace --all-targets -- -D warnings` in `../sase-core`.
6. Because this SASE repo's memory requires it after file changes, run `just check` from this repo if the local
   environment supports it; otherwise report the blocker clearly.

## Risk

Risk is low. The changes keep the same inputs and outputs and only remove lint-rejected spelling. The main verification
is clippy, with Rust tests or the broader repo check as additional confidence if runtime cost and environment allow.

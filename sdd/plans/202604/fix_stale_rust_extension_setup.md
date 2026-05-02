---
create_time: 2026-04-29 21:51:41
status: done
prompt: sdd/prompts/202604/fix_stale_rust_extension_setup.md
---
# Fix stale `sase_core_rs` setup checks

## Context

`sase-1f` closed Phase 8 of the Rust backend migration: ported facades now call `sase_core_rs` directly and no longer
fall back to Python. The reported `just test` run failed in two clusters:

- Most failures were `AttributeError` for missing Rust bindings such as `parse_git_name_status_z`,
  `read_status_from_lines`, and `derive_git_workspace_name`.
- The remaining timestamp failures showed scalar `plan_submitted_at` being dropped from the agent-artifact snapshot.

The current source in `../sase-core` already exports the missing bindings, and its Rust parity test for scalar timestamp
normalization passes. Focused Python tests also pass after the workspace extension is rebuilt. That means the root cause
is not the facade code itself: `just test` can run with an importable but stale `sase_core_rs` wheel. The existing
`Justfile` `_setup` recipe only runs `just rust-install` when `import sase_core_rs` fails, so an older wheel from before
Phase 8 is accepted even when it is missing new bindings or older scan behavior.

## Plan

1. Add a small setup validation helper for the local Rust extension.
   - Keep it under `tools/` so `Justfile` remains readable.
   - The helper should import `sase_core_rs`, verify the required post-Phase-8 binding surface, and perform a tiny
     behavioral probe for the scalar `plan_submitted_at` contract.
   - It should exit `0` only when the installed wheel is good for the current Python tests.

2. Wire `_setup` in `Justfile` through that helper.
   - When `../sase-core` exists and `cargo` is available, run the validation helper with the repo `.venv` Python.
   - If validation fails, print a clear message and run `just rust-install`.
   - Leave the existing editable Python dependency install behavior intact.

3. Verify the failure mode and regression coverage.
   - Run focused tests for the previously reported missing-binding surfaces.
   - Run the scalar timestamp tests.
   - Run `just test` or `just check` after the source edits, per repo memory.

## Expected outcome

After this change, `just test` will not silently reuse an importable stale `sase_core_rs` wheel. A workspace whose Rust
extension predates Phase 8 will self-heal during `_setup` by rebuilding from `../sase-core`, and the reported test
failures should collapse to a clean run.

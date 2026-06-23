---
create_time: 2026-06-23 07:19:33
status: done
prompt: sdd/prompts/202606/rust_clippy_196_fix.md
---
# Rust Clippy 1.96 CI Failure Fix

## Context

GitHub Actions fails in the linked `sase-core` Rust workspace during:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
```

The CI log shows `clippy::chars-last-cmp` in `crates/sase_core/src/editor/completion.rs`. A local repro with
Cargo/Clippy 1.96 against the linked checkout `$SASE_LINKED_REPO_SASE_CORE_DIR` also reports two additional warnings
promoted to errors:

- `clippy::unnecessary-sort-by` in `crates/sase_core/src/agent_launch/mod.rs`
- `clippy::chars-last-cmp` in `crates/sase_core/src/editor/completion.rs`
- `clippy::type-complexity` in a test in `crates/sase_core/src/xprompt_catalog.rs`

The root cause is not a logic regression in the completion code. The Rust workspace is pinned to stable, and the current
stable toolchain is Cargo/Clippy 1.96. Existing code now trips stricter/default Clippy lints, and the workflow treats
all warnings as errors.

## Plan

1. Update the completion context guard in `crates/sase_core/src/editor/completion.rs` to use
   `document.text()[..byte].ends_with('+')` instead of manually taking the last char with `chars().next_back()`. This
   preserves the existing behavior that a non-BOF bare `+` suppresses file-history completion.

2. Update `render_alternative_prompt` in `crates/sase_core/src/agent_launch/mod.rs` to sort replacement ranges with
   `sort_by_key` and `std::cmp::Reverse`, keeping the descending start-offset ordering required for safe reverse
   replacement.

3. Reduce the test-only type complexity in `crates/sase_core/src/xprompt_catalog.rs` by introducing local type aliases
   for the golden-vector case shape. This should keep the parity table readable without changing runtime code or test
   semantics.

4. Run `cargo fmt --all -- --check` in the linked Rust core checkout.

5. Run the CI-equivalent Clippy command in the linked Rust core checkout:

   ```bash
   VIRTUAL_ENV=/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_11/.venv \
   PYO3_PYTHON=/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_11/.venv/bin/python \
   cargo clippy --workspace --all-targets -- -D warnings
   ```

6. If Clippy exposes additional 1.96 warnings after the first set is fixed, apply the same behavior-preserving cleanup
   approach and rerun fmt/clippy until the workspace passes.

## Non-Goals

- Do not change release-plz-managed versions or dependency version pins.
- Do not relax lint settings or add `#[allow(...)]` for these straightforward cleanup cases.
- Do not change Python/TUI behavior in the main `sase` repo.

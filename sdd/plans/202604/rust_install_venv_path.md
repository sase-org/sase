---
create_time: 2026-04-29 11:32:10
status: done
prompt: sdd/prompts/202604/rust_install_venv_path.md
---
# Plan: Fix `just rust-install` venv path handling

## Context

`just rust-install` is intended to build the optional PyO3 extension from the sibling `../sase-core` repo and install it
into this repo's `.venv`. The failing output is:

```text
cd ../sase-core/crates/sase_core_py && .venv/bin/maturin develop --release
sh: 1: .venv/bin/maturin: not found
```

The local workspace has `.venv/bin/maturin`, and `cargo`/`uv` are available. The missing binary is caused by path
resolution after the recipe changes directories.

## Root Cause

`venv_bin` is defined as the relative path `.venv/bin`. Line 184 checks `.venv/bin/maturin` while the shell is still in
the repo root, so that check can succeed. Line 185 then changes into `../sase-core/crates/sase_core_py`, and line 186
uses the same relative `.venv/bin/maturin` path from inside the Rust crate directory. That resolves to
`../sase-core/crates/sase_core_py/.venv/bin/maturin`, which does not exist.

## Implementation

1. Add an absolute venv-bin variable derived from `justfile_directory()` so recipe commands can safely reference this
   repo's virtualenv even after `cd`.
2. Update `rust-install` to use the absolute venv-bin path for both the `maturin --version` probe and the
   `maturin develop --release` invocation.
3. Keep the rest of the Justfile unchanged to avoid widening the scope. Other targets do not currently use `venv_bin`
   after changing directories.

## Verification

1. Re-run `just rust-install`; it should invoke the absolute `.venv/bin/maturin` after changing into the Rust crate.
2. Verify the extension imports from this repo's venv with `.venv/bin/python -c "import sase_core_rs"`.
3. Because this repo's memory says to run `just check` after changes, run `just check` before reporting back.

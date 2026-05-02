---
create_time: 2026-04-29 19:30:38
status: done
prompt: sdd/prompts/202604/fix_ci_sase_core_rs_install.md
---
# Plan: Fix CI dependency resolution for `sase-core-rs`

## Context

GitHub Actions fails during `just install` while resolving `sase[dev]`:

```text
Because sase-core-rs was not found in the package registry and sase==0.1.0 depends on sase-core-rs>=0.1.0,<0.2.0
```

The Python package declares `sase-core-rs` as a required runtime dependency in `pyproject.toml`. The CI workflow only
checks out the `sase` repository, so `uv pip install -e ".[dev]"` can satisfy that dependency only if
`sase-core-rs>=0.1.0,<0.2.0` is already published to the package registry. The failure proves that the registry source
is not currently available.

There is also an ordering bug in `Justfile`: `install` depends on `_setup`, and `_setup` itself runs
`uv pip install -e ".[dev]"`. That means dependency resolution happens before `install` reaches its local `../sase-core`
build/install step. A local sibling checkout cannot help the first `_setup` resolution.

## Root Cause

CI assumes the Rust core distribution is already available from PyPI, but it is not. The source-install escape hatch
exists in `Justfile`, but `_setup` performs the editable Python install too early, before the Rust extension can be
built from source. As a result both fresh CI and some fresh local source checkouts can fail before the intended
`sase_core_rs` local build path runs.

## Implementation Strategy

1. Make the Rust core source location configurable in `Justfile`.
   - Keep the existing default of `../sase-core` for local developer workspaces.
   - Add an environment override such as `SASE_CORE_DIR` so CI can check out the core repo inside the Actions workspace.

2. Split virtualenv creation from dependency installation.
   - Add a small venv-only helper.
   - Change `rust-install` to depend on the venv-only helper, not `_setup`, so it can be called before editable
     dependency resolution.
   - Change `_setup` to build/install `sase_core_rs` first when a source checkout and `cargo` are available, then run
     `uv pip install -e ".[dev]"`.
   - Keep `just install` explicit and idempotent: build/install the Rust extension first when source is present, then
     install `sase[dev]`.

3. Update CI jobs that run `just install`.
   - Check out `sase-org/sase-core` into a stable local path.
   - Set `SASE_CORE_DIR` for `just install`.
   - Install a Rust toolchain before `just install`, so the local source build path is active instead of falling back to
     the unavailable registry package.

4. Preserve release semantics.
   - The publish workflow can continue to rely on PyPI for release smoke tests; release ordering still requires the Rust
     core package to be published before publishing `sase`.

5. Verify.
   - Reproduce the fixed install path locally with a fresh or existing venv.
   - Run `just check` as required by repo instructions after file changes.
   - If the full check is blocked by environment-specific tooling, run the narrow install/health checks and report the
     exact blocker.

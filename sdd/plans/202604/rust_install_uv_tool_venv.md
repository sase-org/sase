---
status: draft
create_time: 2026-04-29 11:42:50
prompt: sdd/prompts/202604/rust_install_uv_tool_venv.md
---

# Plan: Install `sase_core_rs` into the user's installed sase venv

## Problem

`SASE_CORE_BACKEND=rust sase ace` raises `RustBackendUnavailableError`:

```
sase.core.backend.RustBackendUnavailableError: Rust backend requested for
'parse_query' but no Rust implementation is registered (Phase 0A ships
Python only). Unset SASE_CORE_BACKEND or install the optional sase_core_rs
extension.
```

The user's `sase` CLI lives at `~/.local/bin/sase` and runs from the uv‑tool venv `~/.local/share/uv/tools/sase/` (an
editable install of the repo's Python source via a `.pth` file). `just rust-install` only builds `sase_core_rs` into the
local repo `.venv`, so the uv‑tool venv has no Rust extension and `load_rust_extension()` returns `None`. Dispatching
`SASE_CORE_BACKEND=rust` for any operation then correctly raises.

## Root cause

`just rust-install` hard‑codes `VIRTUAL_ENV={{ venv_dir_abs }}` (the local `.venv`) when invoking
`maturin develop --release`. There is no way to target a different venv, and no documentation or target for the
"installed sase" case (uv tool). Users who run `sase` from anywhere other than the local repo `.venv` see Rust as
silently absent.

## Goals

- `SASE_CORE_BACKEND=rust sase ace` works for the user's installed sase (uv‑tool venv) after a single, documented
  command.
- `.venv`-based dev workflows (`just rust-install`, dual‑run benchmarks, parity tests) keep working unchanged.
- No opaque "install into every venv we can find" magic; the user opts in explicitly per venv.

## Non‑goals

- Auto‑install the Rust extension as part of `uv tool install sase`. That belongs to a future packaging change
  (publishing `sase[rust]` / a wheel) and is out of scope.
- Changing the Python facade dispatch behavior or the `RustBackendUnavailableError` contract.

## Design

Recommended: **option (c) — parameterize `rust-install`** plus a small convenience target for the uv‑tool case. This is
the simplest robust approach with no magic.

1. Add a `VENV` argument to the `rust-install` recipe with the existing default of the repo `.venv`. The recipe uses
   that path for both the maturin probe and the `maturin develop --release` invocation.

   ```just
   rust-install VENV=venv_dir_abs: _setup
       ...
       cd {{ sase_core_dir }}/crates/sase_core_py && \
           VIRTUAL_ENV={{ VENV }} \
           PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
           {{ VENV }}/bin/maturin develop --release
   ```

   Behavior with no argument is identical to today.

2. Add a convenience target `rust-install-uv-tool` that resolves the uv‑tool venv path for `sase` and invokes
   `rust-install` with it. The path is `~/.local/share/uv/tools/sase` on Linux (the standard uv tools directory). Use
   `uv tool dir` to discover the prefix in a portable way and append `/sase`. If `uv` is not on PATH or the `sase` tool
   is not installed there, print a friendly message and exit 0 (mirror the existing "no `../sase-core`" pattern).

   ```just
   rust-install-uv-tool:
       @if ! command -v uv > /dev/null 2>&1; then ... fi
       @TOOL_VENV="$(uv tool dir)/sase"; \
        if [ ! -x "$TOOL_VENV/bin/python" ]; then ... fi; \
        just rust-install VENV="$TOOL_VENV"
   ```

   Maturin needs to be present in the target venv; install it on demand via
   `uv pip install --python "$TOOL_VENV/bin/python" maturin` (the existing recipe uses `uv pip install maturin` which
   relies on `VIRTUAL_ENV`; this variant works for any venv).

3. Update `docs/rust_backend.md` "Installing the Rust Backend" section to document both flows:
   - `just rust-install` — installs into the repo `.venv` (dev workflow).
   - `just rust-install-uv-tool` — installs into `~/.local/share/uv/tools/sase` for users who run `sase` via
     `uv tool install`.

   Mention the explicit form `just rust-install VENV=/path/to/venv` for anyone using a different install method (pipx,
   system, etc.).

## Why not the alternatives

- **(a) extend `rust-install` to install into every venv it can find** — Opaque, slow (two builds), and can succeed for
  the wrong target while failing silently for the right one. Worse failure modes than today.
- **(b) separate `rust-install-tool` only, no parameterization** — Doesn't help users on pipx, system Python, or other
  installs. The parameterized form costs nothing extra and is strictly more general.

## Verification

1. From the repo: `just rust-install` still installs into `.venv`; `.venv/bin/python -c "import sase_core_rs"` works.
2. `just rust-install-uv-tool` installs into the uv‑tool venv;
   `~/.local/share/uv/tools/sase/bin/python -c "import sase_core_rs"` works.
3. `SASE_CORE_BACKEND=rust sase ace` launches without raising `RustBackendUnavailableError` (the original failure).
4. `just rust-install VENV=/tmp/explicit-venv` works on an arbitrary venv (smoke test of parameterization).
5. `just check` passes (per repo convention).

## Risks

- Building maturin/wheel into a non‑repo venv may shadow a previously installed wheel. Maturin's `develop --release`
  rebuilds and replaces, so this is a feature; document it in the docs change.
- The uv‑tool venv path discovery via `uv tool dir` is the supported uv API and is stable, but if `uv` evolves we
  re-derive it via the same command rather than hard-coding `~/.local/share/uv/tools/`.

## Out of scope follow‑ups

- Publishing a `sase[rust]` extra that pulls a prebuilt `sase_core_rs` wheel from PyPI so `uv tool install sase[rust]`
  becomes one‑shot.
- Auto‑detecting which venv the user's `sase` script points at and installing there by default.

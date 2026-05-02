---
create_time: 2026-04-29 16:50:00
status: done
bead_id: sase-1b.2
---
# Rust Backend Phase 6B Handoff — `sase` Dependency And Source-Install Story

## Scope landed in this phase

Phase 6B wires `sase` to the `sase-core-rs` distribution that Phase 6A made
buildable from `../sase-core/crates/sase_core_py/`. Default backend selection
is **unchanged** — Python is still the default through Phase 6E and the
`SASE_CORE_BACKEND=rust` opt-in path keeps the same shipped/unported contract.

## Changes in this repo

- `pyproject.toml`: added `sase-core-rs>=0.1.0,<0.2.0` to `[project] dependencies`.
  The pin is compatible with the Phase 6A `sase-core-rs` 0.1.0 metadata
  (`abi3-py312`, CPython 3.12+) and tracks the same major-zero series until a
  later phase explicitly bumps it.
- `Justfile`: `install` now first invokes `just rust-install` when both
  `../sase-core` exists and a `cargo` toolchain is on `PATH`. `rust-install`
  itself is unchanged — it still no-ops when the sibling repo is absent and
  exits 1 when sibling is present but `cargo` is missing. Net effect: source
  dev with a sibling Rust checkout satisfies the new `sase-core-rs` dep
  locally via `maturin develop --release` instead of round-tripping through
  PyPI; pure-Python contributors without a sibling are unaffected by the new
  step (it short-circuits) and rely on the published PyPI wheel.
- `.github/workflows/publish.yml`: added an `install-smoke` job that runs
  between `build` and `publish`. It installs the freshly built `sase` wheel
  into a fresh venv (which also resolves `sase-core-rs` from PyPI) and
  verifies (1) `import sase_core_rs` works and `is_rust_available()` is
  `True`, (2) `parse_query("status:Ready")` succeeds through the facade, and
  (3) the `SASE_CORE_BACKEND=python` escape hatch still parses without
  requiring the Rust extension. `publish` now `needs: [build, install-smoke]`,
  so a broken release artifact never reaches PyPI.
- `.github/workflows/ci.yml`: added a parallel `install-smoke` job that runs
  on every push/PR. It mirrors the publish-time checks against a `just install`
  editable build so we catch packaging regressions before tag time. The full
  backend matrix (`SASE_CORE_BACKEND` unset vs `python`, dual-run parity,
  golden corpus) lands in Phase 6G; this job is intentionally a small
  scaffold.
- `docs/rust_backend.md`: rewrote the title, opening blurb, and "Installing
  the Rust Backend" section to describe the new install story (PyPI for
  users, sibling-checkout source override for contributors,
  `SASE_CORE_BACKEND=python` as the pure-Python fallback). Added a Phase 6A
  and Phase 6B entry to the roadmap; the default-backend selection table is
  unchanged because the default is still Python until Phase 6F.

## Release-coordination prerequisite

The `sase-core-rs` 0.1.0 wheel set produced by the Phase 6A release workflow
**must be on PyPI** before this commit can land green on the public CI matrix
or before any user-facing `sase` release tag is cut. The Phase 6A handoff
records that publishing is gated on `secrets.PYPI_API_TOKEN` in the
`sase-core` repo and a `vX.Y.Z` tag push.

If `sase-core-rs` 0.1.0 is not yet on PyPI when this PR is reviewed, the
unblock paths are (in order of preference):

1. **Publish the wheels first.** In `../sase-core`, run the maturin release
   workflow on the existing 0.1.0 metadata: push tag `v0.1.0` (or trigger
   `workflow_dispatch` with `publish=true`). The workflow builds the four-arch
   wheel matrix, runs `twine check`, and uploads to PyPI when the token is
   configured. Once the package is reachable on PyPI, this PR's CI goes green
   without further changes.
2. **Use a sibling checkout for local validation only.** With
   `../sase-core` checked out, `just install` will satisfy the dependency
   from local source for hand verification before publish completes. CI on
   GitHub-hosted runners has no access to a sibling checkout in this phase
   (Phase 6B intentionally avoids touching the existing lint/test/build jobs
   beyond the new `install-smoke` job), so the public CI still requires the
   PyPI publish.

The handoff intentionally does **not** introduce a Git/path direct-URL
fallback in `pyproject.toml`. The release model that Phase 6 commits to is
"PyPI distribution → wheel install"; a direct-URL would mask exactly the
breakage that the install-smoke job is meant to catch.

## Verification performed

- `just install` in the `sase_100` workspace with `../sase-core` checked out:
  the new pre-step rebuilt `sase_core_rs` 0.1.0 via `maturin develop --release`,
  then `uv pip install -e ".[dev]"` saw the dependency satisfied locally and
  installed the rest of the editable `sase` tree. `python -c "import
  sase_core_rs"` and `python -c "from sase.core.backend import
  is_rust_available; assert is_rust_available()"` both succeed in `.venv`.
- `just check` was run in this workspace after the edits and stays green.
- The `install-smoke` job in `publish.yml` and `ci.yml` is exercised by the
  same set of commands in shell form, so the YAML changes are mechanical
  copies of the verified incantations.

## Out of scope (handed to later subphases)

- `Phase 6C` — backend contract audit and fallback tests. The shipped vs.
  unported classification still needs explicit per-operation tests and the
  error text needs to name the operation, the extension module, and the
  `SASE_CORE_BACKEND=python` escape hatch.
- `Phase 6D` — backend health command. The install-smoke jobs in
  `publish.yml` and `ci.yml` are deliberately import-and-binding-call only;
  Phase 6D should retarget them at the new `sase core health --json` command
  (or whatever the smallest-surface health entrypoint ends up being).
- `Phase 6F` — flipping `DEFAULT_BACKEND` to `Backend.RUST`. Phase 6B keeps
  the default at Python; the only user-visible behavior change of this phase
  is that `import sase_core_rs` works on a fresh `sase` install.
- `Phase 6G` — full CI backend matrix and dual-run parity gate. The Phase
  6B `install-smoke` job is single-mode (default backend with the Rust
  extension installed). Phase 6G should add the `SASE_CORE_BACKEND=python`
  full-test job and the dual-run parity gate against the golden corpus and
  sanitized home-tree fixture.
- `Phase 6H` — documentation rewrite for "Rust is the default" and the
  rollback plan. The docs in this phase still describe Python as the default
  backend because that is still true; the "optional" framing was the only
  piece that was already wrong as of Phase 6B.

## Exit criteria

- [x] `sase` declares a versioned runtime dependency on `sase-core-rs`.
- [x] `just install` produces a working editable install whose `sase_core_rs`
      is loadable, both with a sibling Rust checkout and (post-publish)
      from PyPI.
- [x] A documented path exists for a Rust-toolchain-less contributor:
      published wheel from PyPI, plus `SASE_CORE_BACKEND=python` if the
      wheel ever fails to load.
- [x] The Phase 6 release pipeline now smoke-tests the built `sase` wheel
      end-to-end before PyPI upload.
- [x] No default-backend change has landed.

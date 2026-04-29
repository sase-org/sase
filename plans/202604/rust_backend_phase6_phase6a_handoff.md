---
create_time: 2026-04-29
status: done
bead_id: sase-1b.1
---

# Rust Backend Phase 6A — Wheel Packaging And Release Matrix

Closes Phase 6A of `plans/202604/rust_backend_phase6_default_rust.md`.
Stands up the maturin-based Python distribution for `sase_core_rs`, adds
GitHub Actions release and CI workflows in `../sase-core/`, and verifies
locally that wheels and sdist install and import in a fresh CPython 3.12
venv. **No `sase`-side dependency or default-backend change has landed
yet — that is Phase 6B and Phase 6F.**

## Distribution name and import name

- **PyPI distribution name**: `sase-core-rs`. Pip filenames normalize the
  hyphens, so the wheel is `sase_core_rs-<version>-...whl`.
- **Python import module**: `sase_core_rs`. Unchanged from Phase 1D.
- **Cargo crate name**: `sase_core_py` (workspace member at
  `crates/sase_core_py/`). Unchanged. The Cargo crate is not published to
  crates.io (`publish = false`); the wheel is the published artifact.

The trio is intentional: callers `pip install sase-core-rs` and
`import sase_core_rs`. The Cargo crate name is an internal workspace
identifier only.

## Versioning policy

- Single source of truth: `crates/sase_core_py/pyproject.toml`'s
  `project.version`. Bump it before tagging a release.
- The Cargo workspace version (`Cargo.toml [workspace.package].version`)
  stays synchronized with the pyproject version. The Cargo version is
  technically internal because the crate is unpublished, but keeping
  them in lockstep prevents confusion in release notes.
- Tag format `vX.Y.Z` triggers `release.yml`. Untagged
  `workflow_dispatch` builds the matrix and twine-checks but does not
  publish.

The Phase 6 release tag will be the first `sase-core-rs` published to
PyPI. Existing `sase` consumers continue to use `just rust-install` /
`maturin develop --release` from a sibling checkout until Phase 6B
adds the Python-side dependency.

## Target wheel matrix

PyO3 0.22 with the `abi3-py312` feature is enabled, so a single
`cp312-abi3-<plat>` wheel covers regular CPython 3.12, 3.13, and 3.14
on each platform/architecture. The published matrix:

| OS      | Architecture | Tag                                  |
| ------- | ------------ | ------------------------------------ |
| Linux   | x86_64       | `cp312-abi3-manylinux_2_28_x86_64`   |
| Linux   | aarch64      | `cp312-abi3-manylinux_2_28_aarch64`  |
| macOS   | universal2   | `cp312-abi3-macosx_*_universal2`     |
| Windows | x86_64       | `cp312-abi3-win_amd64`               |
| (sdist) | —            | `sase_core_rs-<version>.tar.gz`      |

Rationale for `manylinux_2_28`: matches PyO3 / maturin defaults for
modern stable ABI and avoids the older `manylinux2014` toolchain.
Free-threaded CPython (3.13t / 3.14t) is **not** included because the
free-threaded build has a distinct ABI that abi3 does not cover. Per
the Phase 6 plan, free-threaded support is recorded as out of scope
for this release; if Phase 7+ adds it, build version-specific (non-abi3)
wheels for `cp31*t` from a separate matrix.

### sdist fallback

`maturin sdist` packs the workspace root (`Cargo.toml`, `Cargo.lock`,
`crates/sase_core/`, `crates/sase_core_py/`, `pyproject.toml`,
`PYPI_README.md`). Locally verified that `pip install
sase_core_rs-0.1.0.tar.gz` builds and imports — this is the source-install
escape hatch when no matching wheel exists.

## Files added or changed in `../sase-core/`

- `crates/sase_core_py/pyproject.toml` — **new**. Declares the
  `sase-core-rs` distribution, its 3.12+ Python requirement, license,
  classifiers, repository URLs, and `[tool.maturin]` settings
  (`module-name = "sase_core_rs"`, `pyo3/extension-module` feature,
  `strip = true`).
- `crates/sase_core_py/PYPI_README.md` — **new**. PyPI long
  description. Kept local to the crate so maturin's sdist scope can
  pick it up without referencing files outside the workspace's
  `manifest-path`.
- `crates/sase_core_py/Cargo.toml` — **modified**. Added `abi3-py312`
  to the PyO3 features list; refreshed the description to match the
  full set of bindings shipped through Phase 5.
- `.github/workflows/ci.yml` — **new**. Runs `cargo fmt --check`,
  `cargo clippy -D warnings`, `cargo test --workspace`, plus a maturin
  wheel build, fresh-venv import smoke, and `twine check` on every
  push/PR to master. Caches Cargo + maturin build artifacts via
  `Swatinem/rust-cache@v2`.
- `.github/workflows/release.yml` — **new**. Builds the Linux x86_64,
  Linux aarch64, macOS universal2, and Windows x86_64 wheel matrix
  plus an sdist; runs the wheel smoke on each native runner; runs
  `twine check` on the merged artifact set; publishes to PyPI when a
  `vX.Y.Z` tag is pushed and `secrets.PYPI_API_TOKEN` is configured.
  Without the token, artifacts are uploaded to the workflow run only
  (manual `twine upload` fallback).

No `Cargo.toml`, `Cargo.lock`, or `rust-toolchain.toml` changes were
required — reproducibility was already adequate. `rust-toolchain.toml`
pins `stable + rustfmt + clippy + minimal profile`.

## Smoke test inputs

Both workflows install the freshly built wheel into a brand-new venv
and run:

```python
import sase_core_rs
sase_core_rs.parse_query("status:Ready")   # positive smoke
try:
    sase_core_rs.parse_query("(")         # negative smoke
except ValueError:
    ...
```

`'!!!'` was originally suggested by the Phase 6 plan as a negative
smoke but is **not** used: `!` is the error-suffix operator, so
`parse_query('!!!')` parses as a string match with `is_error_suffix =
True` rather than raising. `'('` is a structurally invalid query
(open-paren with no expression and EOF), so it produces a stable
`ValueError("parser: Expected string or '(', got Eof (at position 1)")`
across the Phase 2 parser refactors.

There is intentionally no `__version__` attribute on the module
today. The smoke does not check one. Phase 6D adds the proper backend
health helper that records package version and platform tag through
importlib metadata.

## Local verification (run before commit)

Workstation: this repo's ephemeral workspace `sase_102` on Linux
x86_64, CPython 3.12.11. Maturin 1.13.1 from `.venv`.

```bash
# Rust workspace checks (no_change to existing toolchain)
cd ../sase-core
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace                     # all 11 + 0 doc tests pass

# Build abi3 wheel from crates/sase_core_py
cd crates/sase_core_py
.../sase_102/.venv/bin/maturin build --release --out dist --strip
# -> dist/sase_core_rs-0.1.0-cp312-abi3-manylinux_2_34_x86_64.whl

# Build sdist
.../sase_102/.venv/bin/maturin sdist --out dist
# -> dist/sase_core_rs-0.1.0.tar.gz

# Twine metadata check
.venv/bin/twine check dist/*               # both PASSED

# Wheel smoke in fresh CPython 3.12 venv
python3.12 -m venv /tmp/sase_smoke
/tmp/sase_smoke/bin/pip install dist/sase_core_rs-*.whl
/tmp/sase_smoke/bin/python -c "import sase_core_rs; print(sase_core_rs.parse_query('status:Ready'))"
/tmp/sase_smoke/bin/python -c "import sase_core_rs; sase_core_rs.parse_query('(')"  # ValueError

# Sdist smoke in fresh CPython 3.12 venv (built from source)
python3.12 -m venv /tmp/sase_sdist
/tmp/sase_sdist/bin/pip install dist/sase_core_rs-0.1.0.tar.gz
/tmp/sase_sdist/bin/python -c "import sase_core_rs; print('sdist install ok')"
```

The local manylinux tag emitted by maturin on this host
(`manylinux_2_34_x86_64`) is a function of the host glibc; the CI
release workflow pins `manylinux: "2_28"` so PyPI artifacts are
broadly compatible. The local tag is fine for development verification
but should not be uploaded as the published artifact.

## Publish path

Recommended (preferred):

1. Bump `project.version` in `crates/sase_core_py/pyproject.toml` and
   `[workspace.package].version` in `../sase-core/Cargo.toml`.
2. Commit, tag `vX.Y.Z` on `master`, and push the tag.
3. `release.yml` builds the matrix, runs smoke + twine check, and
   publishes when `PYPI_API_TOKEN` is configured on the repo's `pypi`
   environment.

Manual fallback (no PyPI token, or for the very first publish that
needs human review):

1. Run `release.yml` via `workflow_dispatch` (no tag).
2. Download the four wheels and the sdist from the workflow run's
   artifacts.
3. From a trusted workstation: `pip install twine && twine check
   dist/* && twine upload dist/*`.

The exact artifact list to expect from a successful run:

```
sase_core_rs-<version>-cp312-abi3-manylinux_2_28_x86_64.whl
sase_core_rs-<version>-cp312-abi3-manylinux_2_28_aarch64.whl
sase_core_rs-<version>-cp312-abi3-macosx_*_universal2.whl
sase_core_rs-<version>-cp312-abi3-win_amd64.whl
sase_core_rs-<version>.tar.gz
```

## Caveats and known limitations

- **`PYPI_API_TOKEN` is not yet configured on the GitHub repo.** The
  first release should be done via the manual fallback above so the
  token can be added before automation handles publishing.
- **Linux aarch64 wheel is built via QEMU emulation** in
  `PyO3/maturin-action@v1`; the smoke step is skipped on that target
  because the runner is x86_64 and cannot import the cross-built
  wheel. The aarch64 import is exercised end-to-end by the Phase 6B
  release-install smoke (which can spin up an arm64 runner) and by
  user installs.
- **Free-threaded CPython (`3.13t` / `3.14t`) wheels are out of
  scope.** Decision recorded above. Phase 7 can revisit if usage
  justifies the cost.
- **The release workflow does not yet call the Phase 6D backend
  health command** because Phase 6D has not landed. The wheel smoke
  deliberately uses a small inline import + parse_query check that
  Phase 6B / 6D can replace.
- **First-release workflow run on a fresh GitHub Actions runner will
  recompile pyo3 + sase_core + sase_core_py from cold caches** — the
  Cargo cache action speeds up subsequent runs but the very first
  matrix run is the slowest.
- **manylinux base** is `2_28` (CentOS Stream 8 era). Older
  distributions (RHEL 7 / CentOS 7 era, glibc < 2.28) will need to
  install from sdist with a local toolchain, or use
  `SASE_CORE_BACKEND=python` from Phase 6B onward.

## What Phase 6B picks up

Phase 6B adds `sase-core-rs >= <Phase-6A-version>` to `sase`'s
`pyproject.toml`, updates `Justfile` so a fresh `just install`
installs the wheel by default (and `just rust-install` from a
sibling checkout still overrides for local Rust development), and
wires the release-install smoke in `.github/workflows/publish.yml`.
None of Phase 6A's changes flip the default backend; that is Phase
6F's job, gated on Phase 6B–6E.

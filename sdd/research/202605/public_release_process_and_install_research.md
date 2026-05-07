# SASE Public Release Process and Install Research

Date: 2026-05-07

## Question

What release process and install instructions should SASE use for a first serious public release, given the required
Rust core (`sase_core_rs`) and Python plugin architecture?

## Executive Summary

SASE should publish as a small coordinated package family, not as one monolithic artifact:

1. `sase-core-rs`: required PyO3 Rust extension, built and published first.
2. `sase`: Python CLI/TUI host package, published after the Rust wheel matrix is live.
3. Public-safe optional plugins: `sase-github`, `sase-telegram`, and `sase-nvim`.
4. Internal or audit-gated plugins: `sase-google` and `sase-gchat` should not be promoted in public quickstart docs until
   they are reviewed for internal assumptions, naming, and external usefulness.

The best user-facing install path is:

```bash
uv tool install "sase>=0.2,<0.3" --with "sase-github>=0.2,<0.3"
sase core health
```

That shape matters because SASE discovers plugins through Python entry points. The host package and every plugin must
live in the same Python environment. Installing `sase` as a global tool and installing `sase-github` into a project venv
will not work.

The current public registry state makes a version bump mandatory. As of 2026-05-07, PyPI already has `sase==0.1.0` and
`sase-github==0.1.0`, both uploaded on 2026-02-23, while `sase-core-rs`, `sase-google`, `sase-telegram`, and `sase-gchat`
return 404 from the PyPI JSON API. PyPI does not allow distribution filenames to be reused, and filenames include the
project name, version, and distribution type. The next public release cannot reuse `0.1.0`; use `0.2.0` for `sase` and
public plugins.

## Current Package Topology

### `sase`

Current repo: `/home/bryan/projects/github/sase-org/sase_101`

`pyproject.toml` declares:

- Package: `sase`
- Current local version: `0.1.0`
- Python: `>=3.12`
- Required Rust dependency: `sase-core-rs>=0.1.1,<0.2.0`
- Host build backend: `hatchling`
- Main script: `sase = "sase.main.entry:main"`
- Built-in plugin entry point groups:
  - `sase_llm`: Claude, Codex, Gemini, OpenCode, Qwen
  - `sase_vcs`: `bare_git`
  - `sase_workspace`: `bare_git`, `cd`

Current release workflow:

- `.github/workflows/publish.yml` triggers on `v*` tags.
- Builds `sase` with `uv build`.
- Runs an install smoke in a fresh venv.
- Smoke installs the built `sase` wheel and resolves `sase-core-rs` from PyPI.
- Runs `sase core health --json`.
- Publishes with `pypa/gh-action-pypi-publish@release/v1` and `id-token: write`, so it is already shaped for PyPI
  Trusted Publishing.

This is close to the desired public workflow, but it depends on `sase-core-rs` already being available on PyPI.

### `sase-core-rs`

Current repo: `../sase-core`

Workspace facts:

- Cargo workspace version: `0.1.1`
- Rust edition: 2021
- Rust MSRV field: `rust-version = "1.78"`
- PyO3 crate: `crates/sase_core_py`
- Python package: `sase-core-rs`
- Import module: `sase_core_rs`
- Python: `>=3.12`
- Build backend: `maturin>=1.7,<2.0`
- Wheel metadata says Linux, macOS, and Windows are supported.

Current release workflow:

- Builds Linux x86_64, Linux aarch64, macOS universal2, Windows x86_64, and sdist.
- Uses `PyO3/maturin-action@v1`.
- Uses `manylinux: "2_28"` for Linux.
- Runs wheel smoke tests where importable.
- Runs `twine check`.
- Publishes only when a `PYPI_API_TOKEN` secret is configured.

This should be switched to PyPI Trusted Publishing before public release. PyPI's Trusted Publishing model mints
short-lived tokens from GitHub Actions OIDC instead of storing long-lived PyPI API tokens. PyPI explicitly recommends
isolating publish responsibility to a small release workflow, and publishing with `pypa/gh-action-pypi-publish`.

### Public Python Plugins

Current plugin repos:

- `../sase-github`: `sase-github==0.1.0`, depends on `sase>=0.1.0`, publishes on `v*` tags with Trusted Publishing.
- `../sase-telegram`: `sase-telegram==0.1.0`, depends on `sase>=0.1.0`, has no GitHub release workflow currently.
- `../sase-nvim`: Neovim plugin, installed from GitHub plugin managers, not a PyPI package.

`sase-github` must bump to `0.2.0` and depend on `sase>=0.2,<0.3`; otherwise a fresh `pip install sase-github` can
resolve the stale public `sase==0.1.0`.

`sase-telegram` should also use `sase>=0.2,<0.3`. If its console scripts need to be callable directly outside the SASE
process, document `pipx inject --include-apps` or a regular venv install path. For the main `uv tool install` path, the
important property is that the package is installed into the same tool environment as `sase`.

### Audit-Gated Plugins

`../sase-google` and `../sase-gchat` are probably not first-public-release packages:

- `sase-google` includes Mercurial provider support, Google-specific helper scripts, and a `jetski` LLM provider. The
  package name is broad, but the implementation appears tied to internal workflows.
- `sase-gchat` shells out to a `gchat` binary and its README references an internal release path.

Recommendation: keep these off the public install quickstart unless they are intentionally public and audited. If they
remain useful for internal users, publish them to a private index or document source installs separately.

## Registry State Checked

Checked with `https://pypi.org/pypi/<package>/json` on 2026-05-07:

| Package        | PyPI status | Current public latest | Notes                                                                 |
| -------------- | ----------- | --------------------- | --------------------------------------------------------------------- |
| `sase`         | 200         | `0.1.0`               | Uploaded 2026-02-23; metadata predates required `sase-core-rs`.       |
| `sase-core-rs` | 404         | none                  | Must be published before current `sase` can be publicly installable.  |
| `sase-github`  | 200         | `0.1.0`               | Uploaded 2026-02-23; dependency lower bound is too loose for current. |
| `sase-google`  | 404         | none                  | Do not publish publicly before audit.                                 |
| `sase-telegram`| 404         | none                  | Public candidate after dependency bound and publish workflow.         |
| `sase-gchat`   | 404         | none                  | Do not publish publicly before audit.                                 |

PyPI's file-reuse rule makes this operationally important: deleting and recreating a release does not allow the same
filename to be uploaded again. Any fixed public package needs a new version.

## Recommended Release Versioning

Use `0.2.0` for the first coordinated public release of the Python host and public plugins.

Recommended versions:

| Package        | Version | Dependency policy                              |
| -------------- | ------- | ---------------------------------------------- |
| `sase-core-rs` | `0.1.1` | First publish is okay because PyPI has no copy. |
| `sase`         | `0.2.0` | `sase-core-rs>=0.1.1,<0.2.0`                   |
| `sase-github`  | `0.2.0` | `sase>=0.2,<0.3`                               |
| `sase-telegram`| `0.2.0` | `sase>=0.2,<0.3`                               |

If the Rust/Python binding contract is not yet stable enough to treat `sase-core-rs` patch releases as compatible,
tighten the host dependency for this first public release to `sase-core-rs==0.1.1`. The downside is slower emergency
rollout, because every Rust patch requires a matching `sase` release. The upside is fewer accidental breakages from a
future Rust wheel that satisfies a broad range.

My recommendation is to keep `>=0.1.1,<0.2.0`, but treat that as a real compatibility promise: no binding removals or
wire-breaking changes inside `0.1.x`.

## Recommended Release Order

### 1. Preflight

Run this before tagging anything:

```bash
# sase
just install
just check
just build-check

# sase-core
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
# plus the existing wheel-smoke workflow

# public plugin repos
just check
just build
```

Also run an end-to-end local wheelhouse install:

```bash
mkdir -p /tmp/sase-release-wheelhouse

# Build core wheel from ../sase-core/crates/sase_core_py into wheelhouse.
# Build sase and plugin wheels into the same wheelhouse.

uv venv --python 3.12 /tmp/sase-release-smoke
uv pip install --python /tmp/sase-release-smoke/bin/python \
  --no-index --find-links /tmp/sase-release-wheelhouse \
  "sase==0.2.0" "sase-github==0.2.0"
/tmp/sase-release-smoke/bin/sase core health --json
```

The wheelhouse smoke catches the exact failure that matters most: a new `sase` wheel that cannot resolve or import the
new Rust extension.

### 2. Publish `sase-core-rs`

Tag `../sase-core` first:

```bash
git tag -a v0.1.1 -m "Release sase-core-rs 0.1.1"
git push origin v0.1.1
```

Required workflow behavior:

- Build Linux x86_64, Linux aarch64, macOS universal2, Windows x86_64, and sdist.
- Run import/query smoke.
- Run `twine check`.
- Publish to PyPI with Trusted Publishing, not a stored API token.
- Use a protected `pypi` GitHub environment with manual approval for public releases.

Hardening worth doing before public release:

- Add `--locked` to maturin build args.
- Add `--compatibility pypi` to maturin build args.
- Pin `PyO3/maturin-action` to a commit SHA or at least set an explicit `maturin-version`.
- Preserve the separate build and publish jobs so only the publish job can request the OIDC token.

### 3. Verify Registry Availability

Do not tag `sase` until this succeeds from a clean networked environment:

```bash
uv venv --python 3.12 /tmp/sase-core-rs-smoke
uv pip install --python /tmp/sase-core-rs-smoke/bin/python "sase-core-rs==0.1.1"
/tmp/sase-core-rs-smoke/bin/python -c "import sase_core_rs; print(sase_core_rs.__version__)"
```

### 4. Publish `sase`

Bump `sase` to `0.2.0` and verify the dependency still points at the just-published core:

```toml
[project]
version = "0.2.0"
dependencies = [
  "sase-core-rs>=0.1.1,<0.2.0",
  # ...
]
```

Tag:

```bash
git tag -a v0.2.0 -m "Release sase 0.2.0"
git push origin v0.2.0
```

The existing publish workflow is mostly right because it:

- builds in one job;
- installs the built wheel into a fresh venv;
- resolves the Rust dependency from PyPI;
- runs `sase core health --json`;
- publishes from a separate protected environment via Trusted Publishing.

Add one more smoke after the release lands:

```bash
uv tool install --force "sase==0.2.0"
sase core health
sase --help
```

### 5. Publish Public Plugins

Publish `sase-github` after `sase==0.2.0` is live:

```toml
dependencies = ["sase>=0.2,<0.3"]
version = "0.2.0"
```

Then tag `v0.2.0`.

For `sase-telegram`, first add a publish workflow similar to `sase-github`, then tag `v0.2.0`. It should run an install
smoke against `sase==0.2.0` and import the package or run script help in a fresh venv.

### 6. Publish/Tag `sase-nvim`

`sase-nvim` should remain GitHub-installed for now:

```lua
{ "sase-org/sase-nvim" }
```

Create a GitHub tag matching the SASE minor release, e.g. `v0.2.0`, and document that the plugin expects `sase lsp` on
PATH. A later phase can add a rockspec or publish to a Neovim plugin registry if users ask for it.

## Recommended Public Install Docs

### Recommended: `uv tool`

Core only:

```bash
uv tool install "sase>=0.2,<0.3"
sase core health
```

With GitHub PR support:

```bash
uv tool install "sase>=0.2,<0.3" --with "sase-github>=0.2,<0.3"
sase core health
```

With Telegram integration:

```bash
uv tool install "sase>=0.2,<0.3" \
  --with "sase-github>=0.2,<0.3" \
  --with "sase-telegram>=0.2,<0.3"
sase core health
```

Upgrade:

```bash
uv tool upgrade sase
sase core health
```

If plugin constraints need to change, use `uv tool install` again rather than relying on a previous constrained tool
install to change shape.

### Alternative: `pipx`

Core only:

```bash
pipx install "sase>=0.2,<0.3"
sase core health
```

Add plugins to the same isolated environment:

```bash
pipx inject sase "sase-github>=0.2,<0.3"
pipx inject --include-apps sase "sase-telegram>=0.2,<0.3"
sase core health
```

`--include-apps` matters for plugin packages whose scripts should be directly exposed on PATH.

### Developer / Source Install

```bash
git clone https://github.com/sase-org/sase-core.git
git clone https://github.com/sase-org/sase.git
cd sase
uv venv .venv
source .venv/bin/activate
just install
sase core health
```

`just install` builds `sase_core_rs` from sibling `../sase-core` when the checkout and Rust toolchain are present. Users
installing from PyPI should not need Rust.

### Neovim Plugin

`lazy.nvim`:

```lua
{ "sase-org/sase-nvim" }
```

Then:

```lua
require("sase").setup({
  complete = {
    keymap = true,
  },
})
```

Document that `sase` must be on PATH and `sase core health` should pass first. The LSP path is `sase lsp`.

## Why Not One Binary?

A single static binary would simplify installation, but it fights the current architecture:

- The TUI/CLI host is Python and Textual.
- Plugins are Python packages discovered at install time through PyPA entry point metadata.
- The Rust core is already a required extension package with a wheel matrix.
- Some plugins contribute config files and xprompt resources through package metadata.

Python entry points are a standardized packaging mechanism for runtime-discovered integrations. They are a good match
for SASE's current plugin design as long as the docs consistently say "install plugins into the same environment as
`sase`."

A standalone Rust binary can be a future phase after the plugin boundary moves to a process/Wasm/manifest protocol. It
should not block the first public release.

## CI And Release Gaps To Close

Highest priority:

- Publish `sase-core-rs` through Trusted Publishing instead of `PYPI_API_TOKEN`.
- Bump public versions away from already-uploaded `0.1.0`.
- Tighten plugin dependency lower bounds to `sase>=0.2,<0.3`.
- Add publish workflows for `sase-telegram` if it is public.
- Add post-publish install smoke jobs that install from PyPI, not only local artifacts.
- Add a top-level release checklist that encodes the package ordering.

Medium priority:

- Add `project.urls`, authors/maintainers, classifiers, and README metadata to every public package.
- Decide license expression consistency: `sase-core-rs` uses `MIT OR Apache-2.0`; `sase` and plugins use `MIT`.
- Add `--locked` to Rust release builds.
- Generate GitHub releases with notes and artifacts for every tag.
- Consider a `sase[github]` or `sase[telegram]` extra only if SASE wants `pip install "sase[github]"` venv users. Extras
  are less useful for `uv tool`/`pipx` than explicit `--with`/`inject`, but can improve normal venv ergonomics.

Lower priority:

- Homebrew formula or installer script. Useful later, but PyPI plus `uv tool` is the shortest reliable public path.
- A standalone binary. Desirable only after the plugin model changes.

## Sources

Project files reviewed:

- `pyproject.toml`
- `.github/workflows/ci.yml`
- `.github/workflows/publish.yml`
- `Justfile`
- `README.md`
- `docs/rust_backend.md`
- `docs/plugins.md`
- `docs/vcs.md`
- `../sase-core/Cargo.toml`
- `../sase-core/crates/sase_core_py/pyproject.toml`
- `../sase-core/.github/workflows/ci.yml`
- `../sase-core/.github/workflows/release.yml`
- `../sase-github/pyproject.toml`
- `../sase-github/.github/workflows/publish.yml`
- `../sase-google/pyproject.toml`
- `../sase-telegram/pyproject.toml`
- `../sase-gchat/pyproject.toml`
- `../sase-nvim/README.md`

External references:

- PyPI Trusted Publishing overview: https://docs.pypi.org/trusted-publishers/
- PyPI Trusted Publishing security model: https://docs.pypi.org/trusted-publishers/security-model/
- PyPI digital attestations: https://docs.pypi.org/attestations/
- PyPA entry points specification: https://packaging.python.org/en/latest/specifications/entry-points/
- PyPI file reuse behavior: https://pypi.org/help/#file-name-reuse
- uv tool install reference: https://docs.astral.sh/uv/reference/cli/#uv-tool-install
- pipx docs, including `inject`: https://pipx.pypa.io/latest/docs/
- maturin publishing and manylinux notes: https://github.com/PyO3/maturin
- maturin-action hardening notes: https://github.com/PyO3/maturin-action
- PyO3 `abi3` features: https://pyo3.rs/main/features.html
- PyO3 building/distribution notes: https://pyo3.rs/latest/building-and-distribution.html

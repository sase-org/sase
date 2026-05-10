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
4. Internal or audit-gated plugins: `retired Mercurial plugin` and `retired chat plugin` should not be promoted in public quickstart docs until
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
`sase-github==0.1.0`, both uploaded on 2026-02-23, while `sase-core-rs`, `retired Mercurial plugin`, `sase-telegram`, and `retired chat plugin`
return 404 from the PyPI JSON API. PyPI does not allow distribution filenames to be reused, and filenames include the
project name, version, and distribution type. The next public release cannot reuse `0.1.0`; use `0.2.0` for `sase` and
public plugins.

## Follow-up Findings from Fresh Research

The earlier draft is directionally right, but it under-specifies several operational realities that materially affect
the first-public-release plan:

- **The Rust extension already uses `abi3-py312`, which is the right call and should be documented as load-bearing.**
  `sase-core-rs/Cargo.toml` declares `pyo3 = { version = "0.22", features = ["abi3-py312"] }` and the release workflow
  uses `setup-python@v5` with `python-version: "3.12"` only. abi3 means *one* wheel per platform/architecture covers
  CPython 3.12, 3.13, and 3.14, so the matrix stays a 4-cell grid (Linux x86_64, Linux aarch64, macOS universal2,
  Windows x86_64) instead of a 12-cell grid. Wheel filenames will be of the form
  `sase_core_rs-0.1.1-cp312-abi3-<platform>.whl`. The cost is that **free-threaded CPython (PEP 703 / `t`-suffixed
  builds) is NOT covered by abi3** — those interpreters refuse abi3 wheels and fall through to the sdist. If
  free-threaded support matters, that is a separate version-specific build matrix.
- **The Rust workflow currently publishes via stored `PYPI_API_TOKEN`, not Trusted Publishing.** The action used is
  `twine upload`, which cannot emit PEP 740 digital attestations. Switching to `pypa/gh-action-pypi-publish@release/v1`
  with `id-token: write` both retires the long-lived token and gets PyPI attestations for free, which downstream users
  can verify with `pip install --require-hashes` plus the [PEP 740 verifier](https://docs.pypi.org/attestations/).
- **Publishing the `sase-core-rs` sdist is a footgun for the platforms it should help.** An sdist install requires
  CPython headers, a Rust toolchain matching the workspace MSRV (`1.78`), `cargo`, and a working linker. Users on
  musl/Alpine, Linux ppc64le, FreeBSD, Termux, etc. will hit `pip install sase-core-rs` and either succeed slowly with
  Rust pre-installed or fail with an opaque maturin/cargo trace. Two reasonable options:
  1. Ship the sdist but add a `PYPI_README.md` install warning naming the toolchain and minimum Rust version, and make
     `sase` print a clear "no compatible wheel for your platform — install Rust 1.78+ first" message when it cannot
     load `sase_core_rs`.
  2. Skip the sdist entirely and rely on platform wheels until a non-trivial number of users actually need it. The
     downside is `pip download --no-binary :all:` and reproducible-build flows break.
- **musllinux wheels are not built.** Alpine, distroless musl base images, and many lightweight CI runners fall back
  to sdist as a result. Adding a `musllinux_1_2` matrix entry to the maturin job is the cheapest fix and is documented
  in the maturin-action README.
- **The `sase` publish workflow's smoke test is a live-PyPI integration test, not a hermetic test.** It pip-installs
  the just-built `sase` wheel and lets PyPI resolve `sase-core-rs`. If `sase-core-rs` has a regression, every `sase`
  release smoke goes red even when `sase` itself is fine. For first public release, also run a *hermetic* smoke that
  installs `sase-core-rs` from a frozen URL/digest pin so the failure mode "core regressed on PyPI" is distinguishable
  from "this `sase` build is bad".
- **PyPI does not let you delete a release in a way that lets you re-upload.** The only safe correction for a broken
  release is `pypi yank` (release stays installable for existing pins, hidden from new resolutions) plus a fresh patch
  version. Plan to publish `0.2.0rc1` to PyPI first, exercise the install paths from a clean machine, then promote to
  `0.2.0`. The RC route gives you a real "abort and ship 0.2.0rc2" option that the final release does not.
- **PyPI name ownership for `sase` and `sase-github` is already claimed.** Both projects had `0.1.0` uploads on
  2026-02-23. Before any further work, confirm the publishing identity for those projects matches the intended
  `sase-org` GitHub org. If a different account uploaded those, the public release is blocked on either getting that
  account back or filing a [PEP 541](https://peps.python.org/pep-0541/) name-transfer request, which is slow.
- **There is no in-tree way to ask "which plugins did SASE just discover?".** `src/sase/main/plugin_discovery.py`
  exposes `discover_plugin_resources(group)` but no `sase plugin list` CLI surface. First-public users who run
  `uv tool install sase --with sase-github` and then can't see GitHub features will have no quick diagnostic. Adding
  a `sase plugin list` command (groups: `sase_llm`, `sase_vcs`, `sase_workspace`, plus any others) is a small
  ergonomics change that should ship with `0.2.0`.
- **`sase --version` is worth standardizing.** A first-line bug-report aid is `sase --version` printing
  `sase 0.2.0 (sase-core-rs 0.1.1, python 3.12.x, platform <triple>)`. Right now `sase core health` is the canonical
  health probe, which is correct for "is the Rust extension loadable?" but verbose for "what version did the user
  install?".
- **`sase` pyproject metadata is sparse compared to `sase-core-rs`.** Today's `pyproject.toml` has no `description`,
  `readme`, `authors`, `keywords`, `classifiers`, or `project.urls`. PyPI's project page will look bare and search
  ranking for "agentic", "TUI", "ChangeSpec" etc. will be zero. Closing this gap is a pre-publish chore, not a
  research item.
- **Pre-1.0 SemVer carve-out should be communicated.** Under SemVer, `0.x.y` versions can break at any minor bump.
  Both `sase` and `sase-core-rs` are pre-1.0; the dependency constraint `sase-core-rs>=0.1.1,<0.2.0` already encodes
  this, and plugins should mirror it (`sase>=0.2,<0.3`). Document this contract in CHANGELOG / README so users don't
  expect Cargo-style compatibility from `0.x`.

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
- PyO3 features: `abi3-py312` (single wheel covers CPython 3.12 / 3.13 / 3.14 per platform; free-threaded `t`
  builds are out of scope and would need a separate version-specific matrix).
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

`../retired Mercurial plugin` and `../retired chat plugin` are probably not first-public-release packages:

- `retired Mercurial plugin` includes Mercurial provider support, Google-specific helper scripts, and a `jetski` LLM provider. The
  package name is broad, but the implementation appears tied to internal workflows.
- `retired chat plugin` shells out to a `gchat` binary and its README references an internal release path.

Recommendation: keep these off the public install quickstart unless they are intentionally public and audited. If they
remain useful for internal users, publish them to a private index or document source installs separately.

## Registry State Checked

Checked with `https://pypi.org/pypi/<package>/json` on 2026-05-07:

| Package        | PyPI status | Current public latest | Notes                                                                 |
| -------------- | ----------- | --------------------- | --------------------------------------------------------------------- |
| `sase`         | 200         | `0.1.0`               | Uploaded 2026-02-23; metadata predates required `sase-core-rs`.       |
| `sase-core-rs` | 404         | none                  | Must be published before current `sase` can be publicly installable.  |
| `sase-github`  | 200         | `0.1.0`               | Uploaded 2026-02-23; dependency lower bound is too loose for current. |
| `retired Mercurial plugin`  | 404         | none                  | Do not publish publicly before audit.                                 |
| `sase-telegram`| 404         | none                  | Public candidate after dependency bound and publish workflow.         |
| `retired chat plugin`   | 404         | none                  | Do not publish publicly before audit.                                 |

PyPI's file-reuse rule makes this operationally important: deleting and recreating a release does not allow the same
filename to be uploaded again. Any fixed public package needs a new version.

## Wheel Matrix and Platform Coverage

The platforms that get a binary wheel directly determine the install UX, because anything else falls back to sdist
and an sdist of a Rust extension requires a full Rust + CPython-headers build environment.

| Platform                       | Currently built? | Recommended for `0.2.0` | Notes                                                              |
| ------------------------------ | ---------------- | ----------------------- | ------------------------------------------------------------------ |
| Linux x86_64 (manylinux 2_28)  | Yes              | Yes                     | Covers most laptops, CI, and cloud VMs.                            |
| Linux aarch64 (manylinux 2_28) | Yes              | Yes                     | Apple Silicon Linux VMs, Graviton, Raspberry Pi 64-bit.            |
| Linux x86_64 (musllinux_1_2)   | No               | **Add**                 | Alpine, distroless, lightweight CI runners.                        |
| Linux aarch64 (musllinux_1_2)  | No               | Optional                | Less common; add if user demand appears.                           |
| macOS universal2               | Yes              | Yes                     | Covers Intel and Apple Silicon Macs from one build.                |
| macOS arm64-only               | No               | Optional                | Slimmer wheel; universal2 already covers it.                       |
| Windows x86_64                 | Yes              | Yes                     | Covers most Windows users.                                         |
| Windows ARM64                  | No               | Defer                   | Small audience; add if asked.                                      |
| Free-threaded CPython (`t`)    | No (abi3 floor)  | Defer                   | abi3 wheels are refused by `t` builds; needs a separate matrix.    |
| sdist                          | Yes              | Reconsider              | Useful for packagers; lethal for naïve `pip install` on no-wheel. |

If the sdist stays, the README on PyPI and the `sase core health --json` failure message must both name the required
toolchain (Rust >= 1.78, CPython 3.12+ headers, a working linker) so users can self-diagnose. If the sdist is removed,
explicitly document that source builds are done by checking out the GitHub repo rather than via `pip install
--no-binary :all:`.

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

### 1b. TestPyPI Dry Run

Before the production tags, rehearse the whole sequence end-to-end on TestPyPI:

```bash
# In sase-core, push a temporary tag like v0.1.1rc1 with a workflow variant
# pointing at https://test.pypi.org/legacy/.
# Then in sase, push v0.2.0rc1 the same way.
```

Install from a clean machine with the test index:

```bash
uv venv --python 3.12 /tmp/testpypi
uv pip install --python /tmp/testpypi/bin/python \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  "sase==0.2.0rc1"
/tmp/testpypi/bin/sase core health
/tmp/testpypi/bin/sase --version
```

TestPyPI uses a separate account, separate Trusted Publishing config, and a separate quota. The full rehearsal catches
metadata regressions, wheel-tag typos, missing READMEs, and missing classifiers without burning a real version.

### 1c. Publish `0.2.0rc1` to PyPI

Once TestPyPI is clean, ship a release-candidate to mainline PyPI before the final `0.2.0`. This gives a real abort
window: if `0.2.0rc1` fails on a real user's machine, you can yank it and ship `0.2.0rc2` without burning the `0.2.0`
slot.

```bash
git tag -a v0.2.0rc1 -m "Release sase 0.2.0rc1"
git push origin v0.2.0rc1
```

When the RC has been live for a few days without incident, promote with `v0.2.0`.

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

## Yank and Rollback Playbook

PyPI does not allow re-uploading a deleted version. The corrections available are:

- **Yank** (`pypi yank`): the release stays installable for any pin/lockfile that already names it, but resolvers
  treat it as unavailable for new installs and dependents. Use this when a release is broken but not malicious.
- **Delete**: removes the project version entirely. Filenames cannot be re-uploaded, so any user-visible reference to
  that version becomes a permanent gap. Reserve for accidental private/credential leaks.
- **Patch release**: the only forward path. After yanking a broken `0.2.0`, ship `0.2.1` with the fix.

If the broken release is `sase` and the dependency on `sase-core-rs` is the cause, the patch release usually goes on
`sase-core-rs` (`0.1.2`) and `sase`'s constraint resolves to it without a `sase` re-release. If the dependency
constraint is too narrow to absorb the patch (e.g. `sase-core-rs==0.1.1` was pinned), `sase` also needs a patch.

A short, written rollback runbook in the repo (e.g. `docs/release_rollback.md`) is worth more than any tooling: the
person executing it under pressure may be a different person from the one who set the pipeline up.

## Pre-Publish Blockers

Before tagging anything publicly, confirm:

1. **PyPI ownership of `sase` and `sase-github`.** Both projects exist with `0.1.0` from 2026-02-23. The publishing
   identity must match `sase-org`; if not, follow [PEP 541](https://peps.python.org/pep-0541/).
2. **A maintainer-owned PyPI organization or maintainer set with 2FA enforced.** PyPI requires 2FA for any account
   that uploads, and Trusted Publishing requires the GitHub repo and environment to be pre-registered on the project.
3. **`sase` pyproject metadata** (description, readme, authors, keywords, classifiers, project.urls) is filled in to
   at least the level of `sase-core-rs`'s pyproject. Without this, the PyPI project page is bare.
4. **`sase --version`** produces a single-line version string suitable for bug reports.
5. **`sase plugin list`** (or equivalent) exposes discovered entry-point plugins. Without it, users have no
   first-line diagnostic when plugins silently fail to load.
6. **CHANGELOG entry for `0.2.0`** that documents pre-1.0 SemVer policy and breaking changes since `0.1.0`.
7. **License files committed in every package** — `LICENSE` for MIT-only packages, plus `LICENSE-APACHE` for
   `sase-core-rs` since it is dual-licensed `MIT OR Apache-2.0`.
8. **A single canonical install URL** in the README that points at a docs page (or PyPI project page) covering both
   `uv tool install` and `pipx`.

## CI And Release Gaps To Close

Highest priority:

- Publish `sase-core-rs` through Trusted Publishing instead of `PYPI_API_TOKEN`. This also enables PEP 740
  attestations, which arrive automatically with `pypa/gh-action-pypi-publish@release/v1` and `id-token: write`.
- Bump public versions away from already-uploaded `0.1.0`.
- Tighten plugin dependency lower bounds to `sase>=0.2,<0.3`.
- Add publish workflows for `sase-telegram` if it is public.
- Add post-publish install smoke jobs that install from PyPI, not only local artifacts.
- Add a top-level release checklist that encodes the package ordering.
- Add `concurrency:` blocks to all publish workflows so two simultaneous tag pushes can't race a half-uploaded
  release into the index.
- Use `skip-existing: true` on `pypa/gh-action-pypi-publish` so partial-failure retries stay idempotent.
- Add a `musllinux_1_2 x86_64` cell to the `sase-core-rs` matrix.
- Add a TestPyPI rehearsal job (manual `workflow_dispatch`) so dry-runs don't burn real version slots.

Medium priority:

- Add `project.urls`, authors/maintainers, classifiers, readme, and description to every public package. `sase`'s
  pyproject is currently the thinnest of the three.
- Decide license expression consistency: `sase-core-rs` uses `MIT OR Apache-2.0`; `sase` and plugins use `MIT`. If
  both license families are kept, ship `LICENSE` and `LICENSE-APACHE` files inside the `sase-core-rs` wheel/sdist.
- Add `--locked` to Rust release builds. Without it, a transitive crate yank between tag and publish can quietly
  pick a different dependency tree than what was tested.
- Generate GitHub releases with notes and artifacts for every tag (`gh release create vX.Y.Z dist/* --notes-file
  CHANGELOG-X.Y.Z.md`), so wheels are auditable independently of PyPI.
- Add a `sase plugin list` CLI command and `sase --version` formatting for first-line bug reports.
- Add a hermetic install smoke that pins `sase-core-rs` by URL/digest instead of resolving from PyPI, so "core
  regressed on PyPI" is distinguishable from "this `sase` build is bad".
- Consider a `sase[github]` or `sase[telegram]` extra only if SASE wants `pip install "sase[github]"` venv users.
  Extras are less useful for `uv tool`/`pipx` than explicit `--with`/`inject`, but can improve normal venv ergonomics.

Lower priority:

- musllinux aarch64 wheel. Add only if user demand surfaces.
- Free-threaded CPython wheels (separate, version-specific matrix; not abi3-compatible).
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
- `../retired Mercurial plugin/pyproject.toml`
- `../sase-telegram/pyproject.toml`
- `../retired chat plugin/pyproject.toml`
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
- PEP 740 (digital attestations on PyPI): https://peps.python.org/pep-0740/
- PEP 541 (PyPI project name disputes / transfers): https://peps.python.org/pep-0541/
- PEP 656 (musllinux platform tag): https://peps.python.org/pep-0656/
- PEP 703 (free-threaded CPython): https://peps.python.org/pep-0703/
- TestPyPI: https://test.pypi.org/ and https://packaging.python.org/en/latest/guides/using-testpypi/
- PyPI yank semantics (PEP 592): https://peps.python.org/pep-0592/
- PyPI 2FA requirements: https://blog.pypi.org/posts/2024-01-01-2fa-enforced/
- gh-action-pypi-publish (`skip-existing`, attestations): https://github.com/pypa/gh-action-pypi-publish
- GitHub Actions concurrency control: https://docs.github.com/en/actions/using-jobs/using-concurrency

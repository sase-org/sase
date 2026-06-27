# Uniform Development Install for SASE, `sase-core`, and Plugins

Date: 2026-06-27
Status: Consolidated research and recommendation

## Question

What should the standard development install look like for contributors working on
`sase`, `sase-core`, and first-party SASE plugins? In particular, should the
development executable be `sase-dev`, or should development versions be installed
behind the normal `sase` command?

This note consolidates two independent research passes:

- `sdd/research/202606/sase_development_runtime_install_research.md`
- `sdd/research/202606/uniform_dev_install_environment.md`

## Recommendation

Do **not** make `sase-dev` the default development executable.

The uniform development runtime should be a normal `sase` command backed by one
managed environment containing editable local packages:

- editable `sase`;
- editable or rebuilt local `sase-core-rs` from `sase-core/crates/sase_core_py`;
- editable first-party Python plugins such as `sase-github` and `sase-telegram`;
- `sase-nvim` configured to find the same `sase` command on `PATH`.

Make the canonical on-`PATH` development install a SASE-owned wrapper around
`uv tool install` for the tool named `sase`, for example:

```bash
uv tool install --force --python 3.12 --editable "$SASE_DIR" \
  --with-editable "$SASE_CORE_DIR/crates/sase_core_py" \
  --with-editable "$SASE_GITHUB_DIR" \
  --with-editable "$SASE_TELEGRAM_DIR"
```

Then handle script-providing plugins, currently `sase-telegram`, with
`--with-executables-from` after SASE verifies uv's receipt shape and updates its
receipt parser/renderer to preserve that intent across later plugin operations.
The local uv version here, `0.11.24`, supports the flag; uv's docs show package
names as the supported form:

```bash
uv tool install ... --with-executables-from sase-telegram
```

Keep repo-local `.venv` installs (`just install`, `uv run sase`) as the inner
test loop, but do not treat them as the canonical development executable.
Contributors and editor integrations should be able to run plain `sase` and know
it is the development runtime they just installed.

Keep `sase-dev` only as an optional future side-by-side/profile feature for
people who need stable and development SASE running concurrently. That is a
different problem from development installation.

## Why `sase-dev` Feels Wrong

The previous `sase-dev` direction mixes two separate needs:

1. **Development install:** "I am editing `sase`, `sase-core`, or a plugin; make
   my edits live in one runtime."
2. **Parallel runtime identity:** "I need stable `sase` and development
   `sase-dev` available at the same time, with isolated config, state, axe
   process discovery, workspaces, subprocess spawning, and Rust path parity."

The first need is solved by editable installs in one environment. The second
requires renamed launchers, profile-aware state, subprocess command rewriting,
and Python/Rust parity work. Making `sase-dev` the default contributor path
forces every developer to pay for the second problem before the first one is
solved.

There is also a packaging trap: a separate `sase-dev` distribution or command
does not satisfy plugins that depend on the `sase` distribution. Plugin
development can accidentally mix a development plugin with a released host
package unless the real `sase` distribution is installed editably into the same
environment.

## Verified Local Baseline

Checked in this workspace on 2026-06-27.

### `sase`

- `pyproject.toml` defines distribution `sase` version `0.5.0`.
- Runtime dependency: `sase-core-rs>=0.2.0,<0.3.0`.
- Human-facing console script: `sase = "sase.main.entry:main"`.
- There are several support scripts (`sase_git_commit`, chop scripts, etc.), but
  no `sase-dev` script.
- Built-in plugin entry point groups include `sase_llm`, `sase_vcs`, and
  `sase_workspace`.

### Current `just install`

`Justfile` already:

- creates `.venv`;
- discovers `sase-core` via `SASE_CORE_DIR`, `SASE_LINKED_REPO_SASE_CORE_DIR`,
  legacy sibling env vars, or `../sase-core`;
- runs `maturin develop --release` for `sase_core_rs` when the checkout and
  `cargo` are available;
- installs `sase` editable with `uv pip install --no-sources -e ".[dev]"`.

The important gap: `just install` does **not** install first-party plugins. A
plugin contributor can therefore test against a released `sase` without noticing.

### `sase-core`

`sase-core/crates/sase_core_py/pyproject.toml` uses maturin as the build backend
for distribution `sase-core-rs`, module `sase_core_rs`. The workspace package
version is `0.2.0`, matching the current `sase` dependency range.

Native Rust changes still need a rebuild unless an import hook is installed.
Editable Python packaging does not magically recompile native extensions.

### First-Party Plugins

`sase-github`:

- distribution `sase-github`;
- depends on `sase>=0.1.3`;
- registers `sase_vcs`, `sase_workspace`, `sase_config`, and `sase_xprompts`
  entry points;
- has a local `SASE_CORE_PATH` escape hatch, but this is not uniform with other
  plugin repos.

`sase-telegram`:

- distribution `sase-telegram`;
- depends on `sase>=0.1.0`;
- exposes scripts `sase_chop_tg_outbound` and `sase_chop_tg_inbound`;
- has only a local editable plugin install today.

`sase-nvim`:

- is not a Python package;
- shells out to `sase` for xprompt lists, schema paths, and the LSP fallback
  (`sase lsp`);
- therefore benefits from the development runtime being named `sase`, not
  `sase-dev`.

### Existing uv Tool Machinery

SASE already treats `uv tool install sase` as the canonical production topology:
one isolated tool environment named `sase`, with plugins injected into that same
environment.

The `src/sase/uv_tool` receipt layer already reconstructs editable primary and
editable injected packages from `uv-receipt.toml`:

- editable primary package renders as `--editable <path>`;
- editable plugin package renders as `--with-editable <path>`;
- duplicate editable plus bare plugin receipt rows are deduped with the editable
  row winning.

This is strong local evidence for a development install that remains receipt
owned and keeps the tool named `sase`.

The missing piece is executable-source preservation. `Requirement.with_args()`
currently models `--with` and `--with-editable`, but not
`--with-executables-from`. If the dev installer uses that flag for
`sase-telegram`, later `sase plugin install/update/uninstall` operations must
preserve it instead of reconstructing the tool environment without the linked
scripts.

## Modern Best-Practice Signals

Editable installs are the standard development mechanism for Python packages.
PEP 660 defines editable installs for `pyproject.toml` builds and explicitly
covers the key behavior SASE needs: source-tree imports while still installing
dependencies and console-script entry points.

Entry points are the portable metadata contract for both command wrappers and
plugin discovery. SASE plugin development should exercise installed distribution
metadata, not ad hoc `PYTHONPATH` paths or renamed binaries.

uv's tool environments are the right shape for SASE's production and development
runtime: persistent isolated virtual environments with executables linked onto
`PATH`. uv supports `--editable`, `--with-editable`, `--with`,
`--with-executables-from`, `--force`, and `--upgrade-package` for this flow.

uv workspaces are useful when packages live under one repository. SASE is a
polyrepo system with independently versioned linked repositories, so forcing a
workspace superproject is not the right first move. uv path sources and explicit
editable tool requirements fit the current topology better.

For PyO3/maturin packages, `maturin develop` remains a normal local development
command. Maturin also supports PEP 660 editable installs, and its import hook can
rebuild on import for contributors actively editing Rust. SASE should make Rust
refresh explicit rather than hiding native rebuild semantics behind the Python
editable story.

## Options Considered

### A. Keep only per-repo `.venv` installs

This is good for tests, but it is not enough. It misses plugins today, does not
match the production plugin topology, and leaves editor integrations or shell
scripts that call `sase` on `PATH` vulnerable to using a released install.

Verdict: keep as the inner test loop, not the canonical runtime install.

### B. Make `sase-dev` the development executable

This allows stable and development commands to coexist, but it tests the wrong
command path and creates runtime-identity work in subprocesses, docs, editor
integrations, plugin operations, config/state derivation, and Rust parity.

Verdict: useful only for a future side-by-side/profile feature.

### C. Install editable local sources into the uv tool named `sase`

This gives contributors a global `sase` command backed by local code, mirrors the
production one-tool-env-plus-plugins topology, and uses the existing uv receipt
machinery.

Verdict: best default for the development executable.

### D. Create a uv workspace or superproject

This could help integration CI later, but SASE's repos are separate linked
repositories, not packages inside one repository. A workspace also does not by
itself solve the on-`PATH` executable question.

Verdict: not the first implementation.

### E. Commit `[tool.uv.sources]` path-editable overrides

This is idiomatic uv for local path dependencies and may be useful as a
convenience layer. However, SASE's current install deliberately uses
`--no-sources` after prebuilding `sase-core-rs`, and `tool.uv.sources` is only
honored by uv-aware workflows.

Verdict: optional later; do not make it the core installer.

## Proposed Implementation

### 1. Add One Manifest-Driven Dev Installer

Implement one install engine, initially as `just install-dev-tool` or
`just dev-install`, and later expose the same behavior as `sase dev install`.

Inputs:

- local `sase` checkout;
- local `sase-core` checkout;
- known first-party plugins from SASE linked-repo configuration;
- optional `--plugin <path>` for third-party or experimental plugins.

Use a hybrid discovery policy:

- keep the first-party plugin set explicit in code/config so installs are
  predictable;
- resolve each known plugin through `SASE_LINKED_REPO_<NAME>_DIR`, linked-repo
  config, or sibling checkout conventions;
- skip absent plugins with a clear status line;
- allow explicit plugin paths to opt in additional packages.

### 2. Make uv Tool `sase` the Canonical Development Executable

The installer should create or replace the uv tool environment named `sase` with
editable local packages.

Short-term, if `uv tool install --with-editable <sase-core-rs path>` is not
reliable enough for the PyO3 extension on every supported platform, keep
`just rust-install-uv-tool` as a compatibility bridge. Long-term, prefer a
receipt-owned core install so `uv-receipt.toml` describes the full runtime.

Every run should finish with diagnostics:

```bash
sase version -v
sase core health
sase plugin list --offline
```

The status output should report source path, git ref, editable vs wheel status,
Python version, Rust core version/source, and which plugins were included.

### 3. Preserve Script-Providing Plugins

Before using `--with-executables-from` in the official installer:

- run a real uv receipt fixture for `sase-telegram`;
- extend `src/sase/uv_tool/receipt.py` and command rendering to preserve
  executable-source requirements;
- add tests proving `sase plugin install/update/uninstall` does not drop
  `sase_chop_tg_outbound` or `sase_chop_tg_inbound` from the linked tool
  executables.

If uv requires package names rather than paths for `--with-executables-from`,
the installer should still keep the package editable and pass the distribution
name only for executable exposure.

### 4. Keep `.venv` Installs Aligned

Extend repo-local `just install` so the inner test loop can also install present
first-party plugin checkouts editably into `.venv`. This is not the canonical
executable, but it keeps local tests close to the runtime.

Plugin repos should adopt the same contract:

- install local `sase-core-rs`;
- install local `sase`;
- install the plugin itself editably;
- offer the shared `sase` uv-tool dev installer for on-`PATH` integration.

Retire one-off patterns such as `SASE_CORE_PATH` once the shared installer
exists.

### 5. Provide Restore and Status Commands

Because the dev installer replaces the user's global `sase` tool environment,
make that explicit and reversible:

```bash
uv tool install --force --python 3.12 sase
```

or a wrapper such as:

```bash
sase dev restore-release
sase dev status
sase dev refresh-core
```

`sase dev status` should be cheap and should make mixed release/dev environments
obvious.

## Final Decision

Use a receipt-owned editable `uv tool install` for the tool named `sase` as the
uniform development executable for SASE and first-party plugin contributors.

Keep `.venv` installs for tests and fast local iteration, but align them with the
same package set. Do not introduce `sase-dev` as the default development command.
Reserve `sase-dev` for the separate side-by-side stable/dev runtime problem if
that remains valuable after the normal editable `sase` workflow is reliable.

## Sources

Internal:

- `pyproject.toml`
- `Justfile`
- `src/sase/uv_tool/receipt.py`
- `src/sase/uv_tool/commands.py`
- `src/sase/linked_repos.py`
- `tests/uv_tool/test_receipt.py`
- `tests/uv_tool/test_commands.py`
- linked `sase-core/crates/sase_core_py/pyproject.toml`
- linked `sase-core/crates/sase_core_py/Cargo.toml`
- linked `sase-github/pyproject.toml`
- linked `sase-github/Justfile`
- linked `sase-telegram/pyproject.toml`
- linked `sase-telegram/Justfile`
- linked `sase-nvim/lua/sase/lsp.lua`

External, accessed 2026-06-27:

- PEP 660 editable installs: https://peps.python.org/pep-0660/
- PyPA entry points: https://packaging.python.org/specifications/entry-points/
- PyPA `pyproject.toml` scripts/entry points:
  https://packaging.python.org/en/latest/specifications/pyproject-toml/
- uv tools: https://docs.astral.sh/uv/concepts/tools/
- uv dependency sources and editable path dependencies:
  https://docs.astral.sh/uv/concepts/projects/dependencies/
- uv workspaces: https://docs.astral.sh/uv/concepts/projects/workspaces/
- uv CLI reference: https://docs.astral.sh/uv/reference/cli/
- maturin local development: https://www.maturin.rs/local_development.html
- maturin import hook: https://www.maturin.rs/import_hook.html

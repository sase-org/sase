# Development Runtime Install Strategy for SASE and Plugins

Date: 2026-06-27
Status: Research and recommendation

## Question

What is the best way to install SASE when a developer wants development versions of the Python `sase` package, the Rust
`sase-core-rs` binding from `sase-core`, and one or more SASE plugin packages? In particular, should the development
runtime be exposed as a separate `sase-dev` executable, or should contributors use the normal `sase` executable backed by
editable development sources?

This note revisits the `sase-dev` direction from the narrower perspective of daily contributor and plugin development.
Side-by-side stable/dev usage is a related but different problem.

## Executive Summary

For contributor and plugin development, `sase-dev` should not be the default executable. The default development runtime
should install editable development sources into one managed `uv tool` environment and expose the normal `sase`
executable.

The recommended solution is a SASE-owned `just dev-install` or `sase dev install` flow that recreates the `uv tool`
environment for the tool named `sase` from a manifest of local source checkouts:

```bash
uv tool install --force --python 3.12 --editable "$SASE_DIR" \
  --with-editable "$SASE_CORE_DIR/crates/sase_core_py" \
  --with-editable "$SASE_GITHUB_DIR" \
  --with-editable "$SASE_TELEGRAM_DIR" \
  --with-executables-from "$SASE_TELEGRAM_DIR"
```

Exact argument support for `--with-executables-from` with local paths should be validated before implementation; if uv
requires distribution names there, the installer should still keep the package editable and separately request
executable exposure by package name. The important part is the model: one managed tool environment, one `sase` command,
source packages installed editably, and the uv receipt as the runtime source of truth.

Keep `sase-dev` only as an optional side-by-side comparison or profile wrapper after the core dev install works. It
should not be the canonical workflow for people developing SASE or SASE plugins.

## External Best-Practice Signals

### Editable installs are the standard development mechanism

PEP 660 is final and defines editable installs for `pyproject.toml` based builds. Its motivation is exactly source-tree
development without copying Python code into `site-packages`, while still installing dependencies and console-script
entry points. It also states that editable installs should behave like regular installs from the perspective of imports
and metadata such as `importlib.metadata`.

Source: https://peps.python.org/pep-0660/

The Python Packaging User Guide documents local source installs in development mode as:

```bash
python -m pip install -e <path>
```

Source: https://packaging.python.org/en/latest/tutorials/installing-packages/#installing-from-local-src-tree

Implication for SASE: development should not be modeled as a different distribution name or a different import package.
It should be modeled as the same distributions installed editably.

### Entry points are the packaging contract for commands and plugins

The PyPA entry-points specification defines `console_scripts` as install-time command wrappers and also describes entry
points as the standard way installed distributions advertise plugins for runtime discovery through metadata.

Source: https://packaging.python.org/en/latest/specifications/entry-points/

Implication for SASE: a plugin development install must exercise the same installed metadata that production plugin
discovery uses. Ad hoc `PYTHONPATH` or alternate executable names are weaker because they can bypass or obscure the
metadata path that real users run.

### Command-line tools should live in isolated tool environments

The Python Packaging User Guide recommends isolated environments for standalone command-line tools to avoid global
dependency conflicts.

Source: https://packaging.python.org/en/latest/guides/installing-stand-alone-command-line-tools/

uv's tool interface is the modern fit for SASE's current installer direction. The uv docs say `uv tool install` creates
a persistent isolated virtual environment and links executables onto `PATH`. They also warn that tool environments are
not intended to be mutated directly and recommend against direct `pip` operations inside them.

Source: https://docs.astral.sh/uv/concepts/tools/

Implication for SASE: use `uv tool install` or `uv tool upgrade` to recreate the tool environment. Avoid flows that
manually install plugins or Rust bindings into the uv tool venv behind uv's back, except as a short-term bridge while
moving the Rust binding into the receipt-owned install.

### uv already has the primitives SASE needs

`uv tool install` supports:

- `--editable` for the primary tool package.
- `--with-editable` for additional editable packages.
- `--with` for additional packages in the same tool environment.
- `--with-executables-from` for exposing executables from additional packages.
- `--force` for replacing an existing tool install.
- `--upgrade-package` for targeted package refreshes.

Source: https://docs.astral.sh/uv/reference/cli/#uv-tool-install

The uv tools docs also distinguish `--with` from `--with-executables-from`: `--with` adds dependencies but does not link
their executables, while `--with-executables-from` also installs those executables.

Source: https://docs.astral.sh/uv/concepts/tools/#installing-executables-from-additional-packages

Implication for SASE: entry-point-only plugins such as `sase-github` can be included as editable injected packages.
Script-providing plugins such as `sase-telegram` need explicit executable handling if their scripts should be available
on `PATH` from the shared SASE tool environment.

### Rust/PyO3 development is compatible with editable/source workflows

Maturin documents `maturin develop` as the local development command for building and installing Rust-backed Python
packages into a virtual environment. Maturin also supports PEP 660 editable installs when used as the build backend.

Source: https://www.maturin.rs/local_development.html

Implication for SASE: the long-term target should be `sase-core-rs` in the uv receipt as an editable/path package from
`sase-core/crates/sase_core_py`. Rust source changes still require rebuild/reinstall unless the chosen maturin editable
mode uses an import hook that rebuilds automatically. SASE should make that rebuild path explicit and reliable.

### uv workspaces are useful, but probably not the install surface

uv workspaces are intended for multiple related packages managed together with a shared lockfile. The docs explicitly
call out plugin systems and Rust/C extension packages as workspace-like use cases. They also say workspaces are best
for packages in a shared repository, while path dependencies are often preferable when packages need finer-grained
virtual-environment control.

Source: https://docs.astral.sh/uv/concepts/projects/workspaces/

Implication for SASE: a uv workspace may be useful later if the Python package set becomes a monorepo, but today's SASE
repos are separate linked repositories. A SASE-owned dev install manifest with explicit local paths is a better fit than
forcing every plugin repo into one uv workspace.

## Local Findings

### SASE package shape

Current `pyproject.toml` publishes:

- Distribution: `sase`
- Import package: `src/sase`
- Main console script: `sase = "sase.main.entry:main"`
- Runtime Rust dependency: `sase-core-rs>=0.2.0,<0.3.0`
- Plugin entry-point groups: `sase_llm`, `sase_vcs`, and `sase_workspace`

There is no `sase-dev` console script in the package metadata.

### Current SASE source install

The root `Justfile` already knows how to:

- create `.venv`;
- build/install `sase_core_rs` from a sibling `sase-core` checkout using `maturin develop --release`;
- install `sase` itself in editable mode with development dependencies;
- target the existing uv-tool venv through `just rust-install-uv-tool`.

The weak point is that `rust-install-uv-tool` mutates the uv tool environment directly with maturin. That works, but it
does not match uv's current guidance that tool environments should not be mutated directly. It also means the uv receipt
may not fully describe the actual dev runtime unless `sase-core-rs` is installed through `uv tool install
--with-editable`.

### Current plugin source installs are inconsistent

`sase-github`:

- depends on `sase>=0.1.3`;
- registers `sase_vcs`, `sase_workspace`, `sase_config`, and `sase_xprompts` entry points;
- has a `Justfile` escape hatch, `SASE_CORE_PATH=/path/to/sase`, to install an editable SASE checkout before installing
  the plugin in editable mode.

`sase-telegram`:

- depends on `sase>=0.1.0`;
- exposes scripts `sase_chop_tg_outbound` and `sase_chop_tg_inbound`;
- has a simple editable plugin install but no matching `SASE_CORE_PATH` pattern.

`sase-nvim`:

- is not a Python package;
- resolves the SASE LSP through `sase lsp`, `SASE_XPROMPT_LSP_CMD`, or `sase-xprompt-lsp`.

Implication: plugin developers can easily end up testing against a released `sase` while editing a plugin checkout.
The development install needs to make the local SASE checkout and local plugin checkout part of the same runtime by
default.

### SASE already models receipt-owned dev installs

The `src/sase/uv_tool` layer detects a managed `uv tool install sase` environment by checking the uv tool directory,
the running interpreter prefix, and `uv-receipt.toml`.

The receipt parser already preserves editable primary and injected packages. Its tests include a realistic development
receipt with:

- editable `sase`;
- editable `sase-core-rs`;
- editable `sase-github`;
- editable `sase-telegram`;
- duplicate bare plugin rows that uv may record.

The command builder reconstructs `uv tool install` commands from that receipt, preserving editable primary and plugin
requirements. This means SASE already has much of the machinery needed for a first-class dev runtime, as long as the
initial install records all local development packages in the receipt.

### Existing `sase-dev` research solves a different problem

The earlier `sdd/research/202606/sase_dev_install_strategy.md` and
`sdd/research/202606/sase_update_dev_consolidated.md` notes optimize for side-by-side stable and development runtimes.
That is valuable for preview-channel users and for comparing release behavior against development behavior.

For contributors and plugin authors, the primary goal is different: every normal command, subprocess, plugin
entry-point load, xprompt load, and Neovim LSP invocation should exercise the development runtime exactly as users will
invoke it after release. That argues for the normal command name `sase`, not `sase-dev`, as the default contributor
surface.

## Option Analysis

### Option A: Keep using per-repo `.venv` installs

Each repo keeps `just install`, and developers activate the right `.venv` or call `.venv/bin/sase`.

Pros:

- Simple and already mostly exists.
- Good for running each repo's tests.
- Does not overwrite a user's global `sase`.

Cons:

- Poor cross-repo integration story.
- Easy for plugin developers to accidentally test against released `sase`.
- Does not match SASE's own plugin/update code, which is built around `uv tool install sase`.
- Does not help external programs that call `sase` on `PATH`, including editor integrations and scripts.

Verdict: keep for repo test environments, but do not make it the uniform runtime install.

### Option B: Use `sase-dev` as the contributor executable

Install a development environment under a separate command name and tell contributors to run `sase-dev`.

Pros:

- Lets stable `sase` and development `sase-dev` coexist.
- Reduces fear of overwriting a user's stable command.
- Useful for release-vs-dev comparison.

Cons:

- Contributors stop testing the actual command name that users run.
- Internal subprocesses, docs, shell snippets, plugin READMEs, and editor integrations still naturally say `sase`.
- The dev executable becomes another runtime identity that has to be propagated through child processes.
- Plugin development still needs explicit policy for whether plugins are installed into stable `sase`, dev `sase-dev`,
  or both.
- A separate distribution named `sase-dev` would be especially risky because plugins depend on `sase` and could pull
  the released host package into the dev environment.

Verdict: useful optional wrapper later, but the wrong default for a uniform contributor and plugin-development workflow.

### Option C: Recreate the `sase` uv-tool environment from editable local sources

Provide one SASE-owned command or Justfile target that installs the development suite into the uv tool named `sase`:

- primary package `sase` from the local SASE checkout, editable;
- `sase-core-rs` from `sase-core/crates/sase_core_py`, editable/path source;
- selected first-party plugin packages, editable;
- script-provider plugins exposed with `--with-executables-from` when needed;
- all state visible through `uv-receipt.toml`, `sase version -v`, and `sase core health`.

Pros:

- Developers run the same `sase` command users run.
- Uses modern editable install mechanics instead of a renamed package.
- Keeps SASE's existing uv receipt parser and plugin installer relevant.
- Gives plugin authors one obvious answer: install your plugin into the development `sase` tool environment.
- Lets `sase plugin install/update` preserve editable dev packages because the receipt records them.
- Works for Neovim and other integrations that discover `sase` on `PATH`.

Cons:

- Replaces the user's stable `sase` command. This must be explicit and reversible.
- Requires careful handling of script-providing plugin packages.
- Requires validating the maturin/uv editable path for `sase-core-rs` across supported platforms.
- Needs a status/doctor surface so developers can tell whether they are running all-local sources or a mixed release/dev
  environment.

Verdict: best default for SASE and plugin contributors.

### Option D: Create a dev meta-project or uv workspace

Create a separate dev environment project that depends on local SASE, local `sase-core-rs`, and local plugins through
path/workspace sources.

Pros:

- Could give one lockfile for the whole development suite.
- Good for CI-style integration testing across package boundaries.
- uv workspaces explicitly support plugin-system and Rust/C-extension style package sets.

Cons:

- Today's repos are separate linked repositories, not one Python monorepo.
- It does not by itself install the global `sase` command.
- It adds a second dependency-management surface alongside the package metadata and uv tool receipt.

Verdict: useful later for integration CI, not the primary developer install.

## Recommended Solution

Make `sase` the contributor development executable.

Add a SASE-owned development installer that recreates the uv tool named `sase` from local editable packages. The first
version can be a `just dev-install` target in the SASE repo; once stable enough, expose the same engine as `sase dev
install` so plugin repos and existing SASE users can call it uniformly.

The installer should:

1. Discover or accept paths for the local SASE checkout, `sase-core`, and selected plugin checkouts.
2. Run `uv tool install --force --python 3.12 --editable <sase>` with `--with-editable` entries for `sase-core-rs` and
   editable plugins.
3. Use `--with-executables-from` for plugins whose scripts must be linked, especially `sase-telegram`.
4. Avoid direct `pip` or maturin mutation of the uv tool venv in the long-term path. Use maturin/`just rust-install`
   only as a temporary compatibility bridge if uv editable install of the PyO3 package is insufficient.
5. Leave the tool named `sase`, so `uv-receipt.toml`, `sase plugin install/update`, `sase version -v`, `sase core
   health`, editor integrations, and subprocesses all observe one coherent runtime.
6. Print and store a concise dev-runtime status: source paths, git refs, editable/wheel status, Python version, and
   whether each first-party plugin is included.
7. Provide `just dev-restore-release` or documented `uv tool install --force sase --python 3.12` to restore the released
   runtime.

Plugin repos should converge on this contract:

- `just install` remains a repo-local test environment.
- `just install-runtime` or `just dev-install` installs that plugin into the shared development `sase` uv-tool
  environment.
- Plugin READMEs should stop recommending ad hoc `SASE_CORE_PATH` variants and instead point to the shared SASE dev
  installer.

Keep `sase-dev` out of the default contributor path. If side-by-side stable/dev operation remains important, implement
it as a separate optional profile/wrapper after this workflow is reliable. That wrapper should be documented as a
release-comparison or preview-channel tool, not as the way SASE contributors and plugin authors develop the product.

## Implementation Notes

### Candidate command shape

For a full first-party source suite:

```bash
just dev-install \
  --sase-core ../sase-core \
  --plugin ../sase-github \
  --plugin ../sase-telegram
```

The target would render and execute something equivalent to:

```bash
uv tool install --force --python 3.12 --editable "$SASE_DIR" \
  --with-editable "$SASE_CORE_DIR/crates/sase_core_py" \
  --with-editable "$SASE_GITHUB_DIR" \
  --with-editable "$SASE_TELEGRAM_DIR" \
  --with-executables-from "$SASE_TELEGRAM_DIR"
```

If uv does not accept a local path in `--with-executables-from`, use the installed distribution name there after adding
the editable path:

```bash
uv tool install --force --python 3.12 --editable "$SASE_DIR" \
  --with-editable "$SASE_TELEGRAM_DIR" \
  --with-executables-from sase-telegram
```

The implementation should verify the actual uv receipt shape and update `src/sase/uv_tool/receipt.py` if needed so
script-source metadata is preserved during later plugin updates.

### Required validation

The install command should finish by running:

```bash
sase version -v
sase core health
sase plugin list --offline
```

Expected state:

- `sase` is editable from the local checkout.
- `sase-core-rs` is loadable and comes from the local `sase-core` source or a clearly reported wheel fallback.
- first-party plugins are listed as installed and editable.
- script-providing plugins expose required scripts, or SASE reports why they are intentionally not linked.

### Update behavior

For day-to-day source changes:

- Python code changes in editable packages should take effect without reinstalling.
- `pyproject.toml` changes, entry-point changes, dependency changes, and Rust changes require rerunning the dev
  installer.
- A targeted `sase dev refresh-core` may be useful if Rust rebuilds remain slower or more failure-prone than pure Python
  editable refreshes.

### Relationship to `sase update` and plugin operations

The normal `sase update` command should continue to mean "update the current uv-tool `sase` environment." In a
development receipt, it should preserve editable sources when reconstructing the install command, or warn before doing
anything that would replace local editables with index packages.

`sase plugin install` should continue to operate on the current `sase` uv-tool environment. For development, add an
explicit local-source path:

```bash
sase plugin install --editable ../sase-my-plugin
```

or:

```bash
sase dev install --plugin ../sase-my-plugin
```

This avoids the current inconsistency where a plugin repo may install itself into a private `.venv` while the real
`sase` command still sees only released packages.

## Decision

Use a receipt-owned editable `uv tool install` for the tool named `sase` as the uniform development runtime for SASE and
SASE plugin contributors.

Do not make `sase-dev` the default development executable. It solves side-by-side runtime comparison, but it weakens the
developer feedback loop for the normal command path, plugin metadata, editor integrations, and subprocess behavior.

The best next step is to implement and document `just dev-install` in the SASE repo, then update first-party plugin
repos to call the same installer for runtime integration. Once that is stable, consider `sase dev install/status/update`
as the user-facing command group and reserve `sase-dev` for an optional preview/profile wrapper.

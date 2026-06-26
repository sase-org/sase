# `sase update --dev` and the `sase-dev` Runtime

Date: 2026-06-26
Status: Research

## Question

After the `sase-58` epic lands, should SASE add a `--dev` option to `sase update` that installs the `sase-dev`
development version of SASE, and should that become the recommended way to install the development version? If yes, what
are viable implementation options?

## Short Answer

Installing the development runtime as `sase-dev` is the right product direction. Making `sase update --dev` the primary
front door is only right if it manages a separate `sase-dev` runtime. It should not mutate the stable `sase` uv tool
environment in place.

The better public shape is:

```bash
sase dev install
sase dev update
sase-dev version
```

Then, if the single-command convenience is still wanted, `sase update -d|--dev` can be a thin alias for
`sase dev update --install`. That preserves the user's mental model that `sase update` updates the stable tool, while
still giving existing stable users a one-command bridge to the development runtime.

## Local Baseline

The `sase-58` plan currently defines:

- `sase update` as `uv tool upgrade sase`, updating the uv-installed `sase` tool environment and all injected plugins
  together.
- strict detection of a uv-tool install by checking `uv`, `uv tool dir`, `sys.prefix`, and `uv-receipt.toml`.
- plugin install/update flows that read the uv receipt and reconstruct the full `--with` set because `uv tool install
  --with X` replaces the injected set rather than appending to it.
- no dev-channel behavior yet.

The local workspace currently has:

- distribution name `sase`, import package `sase`, version `0.5.0`;
- console script `sase = "sase.main.entry:main"`;
- runtime version inventory with `HOST_DISTRIBUTION_NAME = "sase"`;
- plugin discovery that treats most `sase-*` distributions as plugins except `sase-core-rs`;
- root parser `prog="sase"`;
- several internal subprocess call sites that still shell out to literal `["sase", ...]`.

Prior research in `sdd/research/202606/sase_dev_install_strategy.md` already concluded that `sase-dev` is the right
command shape, but not as a renamed full SASE distribution. It recommended a repo-owned dev installer, a thin
`sase-dev` launcher, current-runtime subprocess helpers, and profile-aware state/config/workspace roots.

## External Baseline

Relevant uv behavior:

- `uv tool install` creates a persistent isolated tool environment and links every executable provided by the package.
- `uv tool install` accepts package names, version constraints, local paths, and git URLs as the package argument.
- `uv tool install` supports `-e|--editable` for the primary package and `--with-editable` for injected packages.
- `uv tool install` supports `-w|--with` and `--with-executables-from` for additional packages.
- `uv tool upgrade` updates installed tools while preserving the version constraints and settings used during install.
- `uv tool run`/`uvx` has `--from` for packages whose command name differs from the package name, but local
  `uv tool install --help` for uv `0.11.24` has no persistent-install `--from` option.

Checked PyPI on 2026-06-26:

- `sase` latest: `0.5.0`
- `sase-core-rs` latest: `0.2.0`
- `sase-github` latest: `0.1.2`
- `sase-telegram` latest: `0.1.3`
- `https://pypi.org/pypi/sase-dev/json`: `404`

Pipx is the notable Python-tool precedent for parallel command names: its `install --suffix` option creates suffixed
virtual-environment and executable names. That is useful evidence for the product need, but SASE's documented install
path is uv, and pipx does not solve SASE's runtime identity, subprocess, or state isolation problems.

## Critique of `sase update --dev`

### What is good about it

- It gives existing stable users a discoverable command to reach the development runtime.
- It lets SASE hide uv details, receipt parsing, plugin preservation, Rust-core checks, and PATH guidance.
- It can reuse most of the `sase-58` uv-tool detection, command-building, dry-run, JSON, and rendering machinery.
- It keeps development-channel install policy inside SASE rather than scattering docs around `uv`, `pipx`, aliases, and
  shell snippets.

### What is risky

1. **The verb is overloaded.** `sase update` naturally means "update the current SASE runtime." Installing a different
   runtime named `sase-dev` is closer to `install`, `dev install`, or `channel switch`.

2. **In-place dev installs would destroy the stable command.** If `--dev` re-runs `uv tool install
   git+https://github.com/sase-org/sase@master`, the linked executable is still `sase`, not `sase-dev`. That changes the
   user's stable tool into a dev tool and undermines the whole point of parallel stable/dev usage.

3. **It bootstraps from stable.** A user would need a new-enough stable `sase` before they can run the recommended dev
   installer. That is fine as a bridge for existing users, but awkward as the canonical installation story.

4. **`sase-dev` is not just packaging.** It needs runtime identity. Help text, child `sase` subprocesses, axe re-exec,
   process discovery, state roots, config roots, workspace roots, and Rust path derivation must know they are operating
   as `sase-dev`.

5. **"dev" is ambiguous.** It could mean GitHub `master`, a local editable checkout, a TestPyPI build, a PyPI
   pre-release, or a full `sase-dev` package. The command must record and display the source it manages.

6. **Rust core can break source installs.** A git install of SASE only works when the required `sase-core-rs` range is
   already published. Local development often needs a sibling `sase-core` checkout built into the same venv.

7. **Plugins add compatibility risk.** The dev runtime may run stable plugins, dev plugins, or editable plugins. The
   installer needs an explicit policy, not accidental resolver behavior.

8. **Rollback needs a real story.** If users can enter dev mode, they need `sase dev uninstall`, `sase dev update`, and
   a clean way to keep or discard dev state. An in-place `sase update --dev` also needs a `--stable` escape hatch.

## Design Principles

- Keep `sase` and `sase-dev` as separate executables.
- Keep the distribution/import identity as `sase` unless a future preview-channel package is deliberately designed.
- Do not rely on a full `sase-dev` distribution for the first implementation.
- Make the dev runtime profile-aware by default: `SASE_PROFILE=dev`, profiled state/config/workspace roots, and explicit
  env overrides for shared-state testing.
- Make internal subprocesses use the active runtime, not literal `sase`.
- Record the dev runtime's source: git URL/ref, local path, PyPI pre-release, TestPyPI index, plugins, Rust-core source,
  and install/update timestamp.
- Support `--dry-run` before changing anything.
- If adding `--dev`, follow CLI rules: give it a short alias such as `-d`, keep help excellent, and keep options sorted.

## Implementation Options

### Option A: In-place `sase update -d|--dev`

`sase update --dev` would detect the current uv-tool install, read its receipt, and rebuild the current `sase` tool
environment from a dev source:

```bash
uv tool install git+https://github.com/sase-org/sase@master --with ... --force
```

For local development, it could support:

```bash
uv tool install -e /path/to/sase --with-editable /path/to/plugin
```

Pros:

- small extension of the `sase-58` engine;
- simple command surface;
- easy to dry-run and render;
- no new launcher or profile machinery required for a minimal version.

Cons:

- does not produce `sase-dev`;
- overwrites the stable `sase` runtime;
- makes rollback a second in-place channel switch;
- does not solve hard-coded child subprocesses or state sharing;
- makes "recommended dev install" destructive to the stable setup.

Verdict: acceptable only as an advanced channel-switch/debug mode, not as the recommended dev install.

### Option B: `sase update --dev` installs a parallel `sase-dev` runtime

Keep the user's current `sase` environment intact. The stable command acts as an installer/updater for a separate dev
runtime:

1. Create or reuse a dedicated venv, e.g. `~/.local/share/sase-dev/venv`.
2. Install SASE into that venv from a recorded source:
   - default: `git+https://github.com/sase-org/sase@master`;
   - local contributor mode: `--path /path/to/sase --editable`;
   - future preview mode: PyPI/TestPyPI pre-release.
3. Install a compatible `sase-core-rs`, building from a sibling/local checkout when requested.
4. Install selected plugins into that same dev venv.
5. Write a thin `sase-dev` launcher into the uv/pipx-style user bin directory.
6. Launcher sets `SASE_CLI_NAME=sase-dev`, `SASE_CLI_EXECUTABLE=<launcher>`, and `SASE_PROFILE=dev`, then execs the dev
   venv's Python module.

Pros:

- preserves stable `sase`;
- gives the desired `sase-dev` command;
- can be invoked from a stable install;
- can share renderer, dry-run, JSON, and error handling with `sase update`;
- allows local editable and remote git modes.

Cons:

- `update --dev` still reads oddly for first install;
- requires runtime identity/profile work before it is safe to recommend;
- needs a dev-runtime manifest and uninstall/repair/status path;
- more logic than pure `uv tool upgrade`.

Verdict: viable if SASE keeps the `--dev` plan, but it should be implemented as a dev-runtime manager, not as a uv-tool
channel switch.

### Option C: Add `sase dev install/update/status/uninstall`

Add a dedicated command group for the dev runtime:

```bash
sase dev install
sase dev update
sase dev status
sase dev uninstall
```

`sase update -d|--dev` can then be an alias for `sase dev update --install`.

Pros:

- clearest user model;
- leaves `sase update` focused on the current stable runtime;
- creates natural homes for status, repair, uninstall, source switching, and plugin policy;
- scales beyond one boolean flag if SASE later adds preview/canary/local channels.

Cons:

- new top-level CLI surface;
- more help/docs/tests than one flag;
- needs the same runtime identity/profile work as Option B.

Verdict: best product and maintenance shape.

### Option D: PyPI/TestPyPI pre-release channel for the `sase` distribution

Publish dev builds as PEP 440 pre-releases of the existing `sase` package, for example:

```text
0.6.0.dev20260626
```

Then `sase update --dev` can run a uv command with `--prerelease allow` and perhaps a different index:

```bash
uv tool install "sase>=0.6.0.dev0,<0.6.0" --prerelease allow
```

Pros:

- tests the same distribution/import package identity that will eventually ship;
- avoids git/source builds on user machines;
- lets uv handle resolution from package indexes;
- fits a future public preview channel.

Cons:

- still installs the `sase` executable unless combined with a wrapper;
- requires reliable automated dev publishing for `sase`, `sase-core-rs`, and plugins;
- PyPI artifacts are immutable, so every dev upload is permanent;
- TestPyPI adds index/auth/documentation complexity;
- not a good replacement for local editable contributor installs.

Verdict: a good future preview-channel option, not the first answer for `sase-dev`.

### Option E: Tiny `sase-dev` wrapper package

Publish a small `sase-dev` package that exposes only a `sase-dev` script and depends on a dev/pre-release `sase`. The
wrapper sets dev profile env vars and delegates to `sase.main.entry`.

Pros:

- clean `uv tool install sase-dev` UX;
- separate uv tool identity;
- avoids duplicate top-level import packages if it is truly only a wrapper.

Cons:

- needs an actual dev/pre-release `sase` stream first;
- must avoid being classified as a plugin by SASE's `sase-*` plugin heuristics;
- plugin dependency ranges can accidentally pull stable `sase` if the dev dependency policy is weak;
- still requires runtime identity/profile fixes.

Verdict: plausible later, after local `sase-dev` runtime support and pre-release publishing exist.

### Option F: pipx suffix escape hatch

For personal use, pipx can install suffixed environments and executables:

```bash
pipx install --suffix=-dev git+https://github.com/sase-org/sase@master
```

Pros:

- existing tool supports parallel executable names;
- useful for quick experiments.

Cons:

- SASE has standardized public install/update design on uv;
- pipx does not solve SASE's child subprocess, axe, config, state, or Rust-core issues;
- adds a second installer support matrix.

Verdict: document as an unsupported escape hatch at most.

## Recommended Approach

Do not make in-place `sase update --dev` the recommended development install path.

Implement a first-class dev-runtime manager after `sase-58`:

1. Land the prerequisites from `sase_dev_install_strategy.md`: current-runtime executable helper, dynamic parser prog,
   profile-aware Python paths, Rust path parity, profile-aware axe/process handling, and migration away from literal
   `["sase", ...]` subprocesses.
2. Add a small `src/sase/dev_runtime/` engine that can create, update, inspect, and uninstall a dedicated dev venv plus
   `sase-dev` launcher.
3. Add `sase dev install`, `sase dev update`, `sase dev status`, and `sase dev uninstall`.
4. Make `sase update -d|--dev` a convenience alias for `sase dev update --install`, with output that clearly says it is
   managing a separate `sase-dev` runtime.
5. Default the first supported source to either:
   - `--path <checkout> --editable` for contributors, with local `sase-core` build support; or
   - `git+https://github.com/sase-org/sase@master` for non-contributor dev-channel users, only when the required
     `sase-core-rs` range is already published and install-smoke is green.
6. Treat PyPI/TestPyPI pre-releases and a tiny `sase-dev` wrapper package as future preview-channel work, not the MVP.

This keeps the stable `sase update` behavior from `sase-58` simple and trustworthy, gives users the desired
`sase-dev` command, and avoids pretending that a dev channel is only a package-manager flag. The core design point is
that `sase-dev` is a runtime identity with its own launcher and default profile, not merely a different version of the
same `sase` executable.

## Sources

Internal:

- `sdd/epics/202606/sase_update_and_plugin_install.md`
- `sdd/research/202606/sase_dev_install_strategy.md`
- `sdd/research/202606/sase_curl_install_script_consolidated.md`
- `sdd/research/202606/direct_master_pypi_releases_consolidated.md`
- `pyproject.toml`
- `README.md`
- `Justfile`
- `src/sase/main/parser.py`
- `src/sase/main/entry.py`
- `src/sase/main/parser_plugin.py`
- `src/sase/main/plugin_handler.py`
- `src/sase/version/_models.py`
- `src/sase/version/_plugins.py`

External:

- uv tools guide: https://docs.astral.sh/uv/guides/tools/
- uv tool concepts: https://docs.astral.sh/uv/concepts/tools/
- uv CLI reference: https://docs.astral.sh/uv/reference/cli/
- uv installation/self-update docs: https://docs.astral.sh/uv/getting-started/installation/
- pipx CLI reference: https://pipx.pypa.io/stable/reference/cli/
- PEP 440 / version specifiers: https://peps.python.org/pep-0440/
- PyPI JSON endpoints checked on 2026-06-26:
  - https://pypi.org/pypi/sase/json
  - https://pypi.org/pypi/sase-dev/json
  - https://pypi.org/pypi/sase-core-rs/json
  - https://pypi.org/pypi/sase-github/json
  - https://pypi.org/pypi/sase-telegram/json

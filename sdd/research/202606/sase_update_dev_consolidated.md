# `sase update --dev` and the `sase-dev` Install Path

Date: 2026-06-26
Status: Consolidated research

## Question

After the `sase-58` epic lands, should SASE add a `--dev` option to `sase update` that installs the `sase-dev`
development version of SASE, and should that become the recommended way to install the development version? What are the
reasonable implementation alternatives, and which approach should SASE take?

This note consolidates and supersedes:

- `sdd/research/202606/sase_update_dev_option_critique.md`
- `sdd/research/202606/sase_update_dev_flag_critique.md`

## Short Answer

The plan is right about the goal, but wrong about the primary public surface.

`sase-dev` should mean a separate development runtime and command installed beside stable `sase`. `sase update --dev`
should not be the recommended way to install that runtime, because:

1. A `sase` subcommand cannot bootstrap a fresh machine.
2. `sase-58` defines `sase update` as "upgrade the current uv-tool `sase` install," not "provision another runtime."
3. An in-place dev switch overwrites stable `sase` and loses the side-by-side story.
4. There is no published dev channel or `sase-dev` package today.
5. Git/source installs can break when Python `master` needs an unreleased `sase-core-rs`.

Recommended shape:

```bash
sase dev install
sase dev update
sase dev status
sase dev uninstall
```

For existing stable users, `sase update -d|--dev` can be a convenience alias for `sase dev update --install`, but its
output should say clearly that it is managing a separate `sase-dev` runtime. The bootstrap path should remain something
that works without an existing SASE install: `just install-sase-dev` for contributors, and possibly a future curl
installer `--dev` for non-contributor users.

## Verified Baseline

### `sase-58`

As of this check, bead `sase-58` is still open, with all four child phases in progress. Its epic plan is nevertheless
specific about the intended contract:

- `sase update` delegates to `uv tool upgrade sase`.
- The command targets users who installed SASE via `uv tool install sase`.
- Detection is strict: the running interpreter's `sys.prefix` must be the uv tool directory's `sase` environment and
  that environment must contain `uv-receipt.toml`.
- Running from a source checkout venv is intentionally rejected.
- The uv receipt is the source of truth for the primary package and injected plugins.
- `uv tool install --with X` replaces the injected set, so plugin-preserving install/update flows must reconstruct the
  full `--with` set from the receipt.

That is a good contract for stable self-update. It is not automatically a good contract for installing another command.

### Current SASE Packaging

Local and PyPI facts checked on 2026-06-26:

- `pyproject.toml` publishes distribution `sase`, version `0.5.0`.
- The import package is `sase`.
- The public console script is `sase = "sase.main.entry:main"`.
- The required Rust extension is `sase-core-rs>=0.2.0,<0.3.0`; PyPI has `sase-core-rs==0.2.0`.
- PyPI has `sase==0.5.0`, `sase-github==0.1.2`, and `sase-telegram==0.1.3`.
- `https://pypi.org/pypi/sase-dev/json` returns `404`.
- `Justfile` has `install` flows that build a sibling local `sase-core` checkout into the dev venv when present, but
  there is no `install-sase-dev` target yet.

Prior research in `sdd/research/202606/sase_dev_install_strategy.md` already chose `sase-dev` to mean a parallel,
profile-isolated runtime, not a renamed full `sase-dev` Python distribution.

### uv Facts

Local uv is `0.11.24`.

Important correction from the intermediate notes: persistent `uv tool install` does **not** have `--from` in local
`uv 0.11.24`, and the current official uv tool guide distinguishes the two surfaces:

- `uvx` / `uv tool run` uses `--from` when the command name differs from the package or when requesting alternate
  sources.
- Persistent `uv tool install` takes the package or source as the positional `<PACKAGE>`, e.g.
  `uv tool install git+https://github.com/httpie/cli`.
- `uv tool install` creates a persistent isolated tool environment and links every executable provided by the package.
- If a tool was previously installed, re-installing generally replaces the existing tool environment.
- `uv tool upgrade <tool>` respects the constraints/source recorded at install time.

Implication: a git-source install of SASE is mechanically possible as:

```bash
uv tool install git+https://github.com/sase-org/sase@master
```

But that still installs the `sase` distribution and links the executables it provides. It does not create a separate
`sase-dev` command unless the installed package or an added wrapper provides one, and it will tend to replace the user's
existing uv-tool `sase` environment.

## Critique of the Plan

### What is good about `sase update --dev`

- It is discoverable for users who already have stable SASE installed.
- It lets SASE hide uv details, plugin receipt reconstruction, Rust-core checks, and PATH guidance.
- It can reuse some of the `sase-58` rendering, dry-run, JSON, and error-handling conventions.
- It gives a natural bridge from stable usage into development usage.

### What is risky

1. **It is not a bootstrap installer.** A fresh machine has no `sase` command yet. `sase update --dev` can be a bridge
   for existing users, not the recommended install path for everyone.

2. **It overloads `update`.** `sase-58` promises that `sase update` updates the current uv-tool SASE environment. If
   `--dev` creates `~/.local/bin/sase-dev`, it is really a dev-runtime install/update command. If it re-points the
   current uv tool to git `master`, it is a channel switch. Those are different products.

3. **In-place switching destroys side-by-side use.** A uv tool named `sase` is keyed as `sase`; re-installing from git
   or a pre-release still produces the `sase` command. That overwrites stable SASE unless SASE creates a separate venv
   and launcher or publishes a wrapper package.

4. **`sase-dev` is a runtime identity, not only a version.** The dev command needs help text, child subprocesses, axe
   re-exec, process discovery, state paths, config paths, workspace paths, and Rust path derivation to preserve the
   active runtime and profile. Current code still has literal `["sase", ...]` subprocesses and `prog="sase"` in the
   parser.

5. **The dev source is undefined.** "Dev" could mean git `master`, a local editable checkout, TestPyPI `.devN` builds,
   PyPI pre-releases, or a published `sase-dev` wrapper. The command must record and display the source it manages.

6. **Git-source installs can be Rust-incompatible.** A git install of Python `master` resolves `sase-core-rs` from the
   package index unless extra local build logic is added. That can fail whenever Python `master` depends on unreleased
   Rust-core API. The existing `just install` source flow avoids this by building a sibling `../sase-core` checkout when
   present.

7. **Plugins need explicit policy.** The dev runtime may use stable plugins, dev plugins, or editable plugin checkouts.
   Accidental resolver behavior is not enough, especially if plugin dependency ranges pull stable `sase` into a dev
   environment.

8. **Rollback and uninstall need homes.** Users need `status`, `repair`, `update`, and `uninstall` operations for dev.
   A single boolean on `sase update` has nowhere natural to put that lifecycle.

## Implementation Options

### Option A: In-place `sase update -d|--dev`

Rebuild the current uv-tool `sase` environment from a dev source:

```bash
uv tool install git+https://github.com/sase-org/sase@master --force --with ...
```

or, for a local checkout:

```bash
uv tool install -e /path/to/sase --force --with-editable ...
```

Pros:

- Smallest extension to the `sase-58` engine.
- Can reuse receipt parsing, full `--with` reconstruction, dry-run, JSON, and rendering.
- Clear as an advanced channel-switch/debug feature.

Cons:

- Does not install `sase-dev`.
- Replaces stable `sase` in place.
- Shares stable state/config/workspaces unless the user manually overrides env vars.
- Still has the Rust-core mismatch for git/PyPI installs.
- Needs a `--stable` escape hatch and real-uv verification that moving git refs refresh correctly.

Verdict: acceptable only as an advanced channel switch after the dev source is defined. Not the recommended dev install.

### Option B: `sase update --dev` Provisions a Separate `sase-dev`

Stable `sase` would create or update a dedicated dev venv, install SASE from a recorded source, install compatible Rust
core and plugins, then write a `sase-dev` launcher into the user's bin directory.

Pros:

- Preserves stable `sase`.
- Produces the desired `sase-dev` command.
- Gives existing stable users one discoverable bridge.
- Can reuse some `sase-58` UI conventions.

Cons:

- It is not really `uv tool upgrade sase`; it is a separate dev-runtime manager.
- Needs runtime identity/profile work before it is safe to recommend.
- Needs manifest, status, repair, uninstall, source-switching, and plugin policy.
- Reads oddly as a first install surface.

Verdict: viable as a convenience alias, but it should delegate to a real `sase dev` command group rather than hiding a
new lifecycle behind `update`.

### Option C: Dedicated `sase dev` Command Group

Add:

```bash
sase dev install
sase dev update
sase dev status
sase dev uninstall
```

Back it with a small `src/sase/dev_runtime/` engine that manages:

- a dedicated venv, e.g. `~/.local/share/sase-dev/venv`;
- a manifest recording source type, git ref/path/index, plugin set, Rust-core source, and install/update timestamps;
- a `~/.local/bin/sase-dev` launcher;
- default `SASE_PROFILE=dev`;
- explicit shared-state escape hatches via existing env overrides;
- dry-run and JSON output.

Pros:

- Best user model: install/update/status/uninstall are named directly.
- Keeps `sase update` focused on the current stable runtime.
- Creates natural homes for rollback, repair, source selection, and plugin policy.
- Matches prior `sase-dev` runtime research.
- Scales to local editable mode, git `master`, and future pre-release channels.

Cons:

- New CLI surface.
- Requires runtime identity/profile work before broad recommendation.
- More tests and docs than one flag.

Verdict: best product and maintenance shape.

### Option D: Bootstrap Surface Outside SASE

For users without SASE installed, use a bootstrap-capable path:

```bash
git clone https://github.com/sase-org/sase
cd sase
just install-sase-dev
```

and possibly, after the curl installer exists:

```bash
curl --proto '=https' --tlsv1.2 -LsSf https://sase.sh/install.sh | sh -s -- --dev
```

Pros:

- Solves the bootstrap paradox honestly.
- Can build or inject local `sase-core-rs`.
- Keeps contributor/source install separate from stable uv-tool self-update.

Cons:

- `just install-sase-dev` does not exist yet.
- The curl installer research currently says the script should not become the contributor/source install path, so a dev
  flag there would need a deliberately narrow public-preview contract.

Verdict: required for first install. Pair it with Option C.

### Option E: Real Pre-release Channel

Publish `.devN`, timestamped dev, or `rcN` builds for `sase`, `sase-core-rs`, and any first-party plugins to TestPyPI or
PyPI. Then SASE can install or switch to a pre-release source with `--prerelease allow` and the appropriate index.

Pros:

- Reproducible, index-backed dev versions.
- Avoids building from git/source on user machines.
- Cleaner long-term semantics for "dev channel."

Cons:

- Requires release-pipeline work first.
- Python and Rust packages must publish compatible dev builds in lockstep.
- Still produces `sase`, not `sase-dev`, unless paired with a wrapper/launcher.
- PyPI/TestPyPI policy and auth add operational surface.

Verdict: good future preview channel, not the MVP.

### Option F: Tiny `sase-dev` Wrapper Package

Publish a package named `sase-dev` that exposes only a `sase-dev` script and depends on a dev/pre-release `sase`.

Pros:

- Clean `uv tool install sase-dev` UX.
- Avoids two full distributions providing the same top-level `sase` package.

Cons:

- Needs a real dev/pre-release `sase` channel first.
- Must not be misclassified by SASE's `sase-*` plugin heuristics.
- Plugin dependency policy must avoid pulling stable `sase` into the dev runtime.
- Still needs profile/runtime fixes.

Verdict: plausible later, after Option C and a pre-release channel exist.

### Option G: pipx Suffix Escape Hatch

For personal experimentation:

```bash
pipx install --suffix=-dev git+https://github.com/sase-org/sase@master
```

Pros:

- Existing tool can create suffixed executable names.

Cons:

- SASE's public install/update story is uv.
- Does not solve child subprocesses, axe, config/state isolation, or Rust-core source builds.
- Adds another support matrix.

Verdict: unsupported escape hatch at most.

## Recommended Approach

Do not make `sase update --dev` the recommended development install path.

Implement `sase-dev` as a first-class dev runtime, with a direct lifecycle command and a bootstrap path:

1. **Define what "dev" means first.** For the MVP, use local editable checkouts for contributors and optionally git
   `master` for non-contributor preview users, with an explicit Rust-core caveat. Long term, prefer a real `.devN` or
   `rcN` pre-release channel. Reserve `sase-dev` to mean the parallel runtime/command; call the in-place source "the
   dev channel."

2. **Land the `sase-dev` prerequisites from prior research.** Add a current-runtime executable helper, make parser help
   use the active command name, migrate literal `["sase", ...]` subprocesses and axe re-exec paths, and add profile-aware
   state/config/workspace paths in Python and Rust.

3. **Add `sase dev install/update/status/uninstall`.** Manage a dedicated venv, `sase-dev` launcher, manifest, Rust-core
   source, plugin policy, dry-run, and uninstall/repair behavior. Default the launcher to `SASE_PROFILE=dev`.

4. **Make `sase update -d|--dev` optional sugar, not the primary contract.** For existing stable users, it can delegate
   to `sase dev update --install` and print that it installed or updated the separate `sase-dev` runtime. Do not silently
   re-point stable `sase` unless the user chose an explicit future channel-switch command.

5. **Keep in-place channel switching separate.** If SASE later wants `sase update --channel dev` or `sase update --dev`
   to re-point the current uv-tool environment, implement it as an advanced mode with `--stable`, receipt-preserving
   plugin reconstruction, and real-uv tests around git branch refresh behavior.

6. **Provide a real bootstrap path.** `just install-sase-dev` should be the contributor path. A curl installer `--dev`
   may become the non-contributor preview path only after its contract is intentionally updated beyond the current
   stable-install wrapper design.

This keeps `sase-58`'s stable update behavior simple, preserves side-by-side stable/dev usage, and avoids presenting a
package-manager flag as if it solved runtime identity, state isolation, Rust-core compatibility, and rollback.

## Sources

Internal:

- `sase bead show sase-58`
- `sdd/epics/202606/sase_update_and_plugin_install.md`
- `sdd/research/202606/sase_dev_install_strategy.md`
- `sdd/research/202606/sase_curl_install_script_consolidated.md`
- `sdd/research/202606/direct_master_pypi_releases_consolidated.md`
- `pyproject.toml`
- `README.md`
- `Justfile`
- `src/sase/main/parser.py`
- `src/sase/workflows/commit/precommit_hooks.py`
- `src/sase/ace/restore.py`
- `src/sase/axe/run_agent_exec_plan_sdd.py`
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`

External:

- uv tools guide: https://docs.astral.sh/uv/guides/tools/
- uv CLI reference: https://docs.astral.sh/uv/reference/cli/
- uv install docs: https://docs.astral.sh/uv/getting-started/installation/
- PyPI JSON endpoints checked 2026-06-26:
  - https://pypi.org/pypi/sase/json
  - https://pypi.org/pypi/sase-dev/json
  - https://pypi.org/pypi/sase-core-rs/json
  - https://pypi.org/pypi/sase-github/json
  - https://pypi.org/pypi/sase-telegram/json

# `sase-dev` Parallel Install Research

Date: 2026-06-25

## Question

Should SASE support installing the development build under a different command name, such as `sase-dev`, so one machine
can keep both the latest stable release and the current development version? If yes, what implementation shape should
SASE use?

## Short Answer

Yes, this is the right user-facing shape: keep `sase` as the stable public command and provide a separate `sase-dev`
command for local or preview builds. But it should not be implemented as only another `[project.scripts]` entry in the
main `sase` package.

The problem has two layers:

- **Packaging coexistence:** the stable release and the development build need separate executable names and separate
  Python environments.
- **Runtime self-reference:** a process launched as `sase-dev` must keep using the development runtime when it starts
  axe, lumberjacks, commit helpers, bead updates, or `sase commit` subprocesses.

Today SASE still has several hard-coded assumptions that the command is literally `sase`. A `sase-dev` binary without
fixing those paths would look correct at the shell prompt but could silently call the stable `sase` for internal work.

## Current Ground Truth

### Package and release shape

Verified locally:

- `pyproject.toml` declares `[project] name = "sase"` and `version = "0.5.0"`.
- The primary console script is `sase = "sase.main.entry:main"`.
- There are many additional console scripts, including `sase_chop_*`, `sase_git_commit`, `sase_git_fix`, and
  `sase_xcmd`.
- README's normal user install path is `uv tool install sase --python 3.12`.
- `src/sase/__init__.py` also reports `__version__ = "0.5.0"`.

Verified externally:

- PyPI currently has `sase==0.5.0`.
- `https://pypi.org/pypi/sase-dev/json` returned no package record in this check, so the name appears unclaimed on PyPI
  as of this date.

### uv behavior

The uv tool model is a good fit for stable SASE installs, but it does not directly solve "install the same distribution
twice under two executable names."

Relevant uv facts:

- `uv tool install` creates a persistent isolated tool environment and links executables onto the user's PATH.
- `uv tool install` installs all executables provided by the target package.
- Reinstalling an already-installed tool generally replaces that tool environment.
- Tool environments live under the uv tools directory; linked executables live under the uv tool bin directory.
- `uv tool run` supports `--from` for "command name differs from package source" use cases, but local `uv tool install`
  does not expose an equivalent `--from` option.

Implication: if the `sase` distribution simply adds a `sase-dev` script, a stable `uv tool install sase` will also link
`sase-dev` once that release includes the script. Installing the development package as `sase` will still target the
same uv tool identity and can replace the stable `sase` environment.

### pipx behavior

pipx has a feature uv does not: `pipx install --suffix SUFFIX` appends a suffix to both the venv and executable names.
That can create a `sase-dev` command from the same `sase` distribution, for example with a `-dev` suffix.

This is a real alternative, but adopting it as the primary SASE path would introduce a second tool manager into docs and
automation that currently standardize on uv. It also does not by itself fix SASE subprocesses that call `sase` by name.

### Internal command-name assumptions

The following local paths matter before a rename is safe:

- `src/sase/main/parser.py` hard-codes `prog="sase"` and compact help examples such as `sase doctor`.
- `src/sase/axe/run_agent_exec_plan_sdd.py` shells out to `["sase", "commit", ...]`.
- `src/sase/workflows/commit/precommit_hooks.py` shells out to `["sase", "bead", ...]`.
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py` shells out to `["sase", "bead", "update", ...]`.
- `src/sase/ace/restore.py` shells out to `["sase", "commit", ...]`.
- `src/sase/axe/orchestrator.py` searches for `Path(sys.executable).parent / "sase"` and then `shutil.which("sase")`
  before spawning lumberjacks.
- `src/sase/axe/_process_start.py` searches for `sase` in the current Python bin, PATH, and `~/.local/bin/sase`, and
  canonicalizes axe startup out of ephemeral workspaces toward that stable command.
- `Justfile` has `rust-install-uv-tool` hard-coded to `$(uv tool dir)/sase`.
- `docs/rust_backend.md` documents that same `$(uv tool dir)/sase` target.

Some paths are already robust. For example, `sase ace --tmux` re-execs with `sys.executable -m sase`, which keeps the
current Python environment instead of resolving `sase` on PATH.

### State and config coexistence

Two commands do not automatically mean two independent SASE worlds.

- Runtime state defaults to `~/.sase`, with `SASE_HOME` available to override it.
- The axe daemon, PID file, lifecycle lock, lumberjack state, logs, agent index, notifications, project files, chats,
  plans, and artifacts all live under that state root.
- User config defaults to `~/.config/sase/sase.yml` plus `~/.config/sase/sase_*.yml`. There is no equivalent documented
  `SASE_CONFIG_DIR` override today.

Implication: `sase` and `sase-dev` can share state usefully for "try the dev runtime on my normal projects." They cannot
safely run independent axe daemons against the same `SASE_HOME`. Users who want true isolation need to launch dev with
`SASE_HOME=~/.sase-dev`, and config isolation would need either overlay discipline or a future config-dir override.

## Options

### Option A: Shell alias or `uvx --from` only

Example:

```bash
alias sase-dev='uvx --from git+https://github.com/sase-org/sase@master sase'
```

Pros:

- No code changes.
- Useful for one-off smoke tests.

Cons:

- Not a persistent install.
- Slower and less predictable for daily use.
- Does not create a real `sase-dev` runtime for subprocesses or axe.
- Does not solve local Rust core development.

Verdict: good troubleshooting trick, not product support.

### Option B: Add `sase-dev = "sase.main.entry:main"` to the main package

Pros:

- Very small code change.
- Works in ordinary venvs where users install one build and want two command spellings.

Cons:

- Stable `uv tool install sase` would also install `sase-dev`, so the name would not reliably mean "development build."
- Installing development SASE with uv would still target the `sase` tool package and risk replacing the stable tool
  environment.
- Internal subprocesses that call `sase` could still hit the stable binary on PATH.

Verdict: insufficient by itself. It creates an alias, not a parallel install story.

### Option C: Document pipx `--suffix=-dev`

Example:

```bash
pipx install --suffix=-dev git+https://github.com/sase-org/sase.git@master
sase-dev version
```

Pros:

- pipx natively supports suffixed venvs and executable names.
- No need to publish a second package.
- Can install from PyPI, git, or a local editable path.

Cons:

- SASE's public install story currently standardizes on uv, not pipx.
- Existing Justfile and docs target uv tool paths for Rust core updates.
- Internal `["sase", ...]` subprocesses still need a current-executable resolver.

Verdict: viable escape hatch, but not the primary SASE-supported path unless the project is willing to document pipx as
a first-class install manager.

### Option D: Publish a separate full `sase-dev` distribution

This would build the same `src/sase` import package but with distribution metadata `Name: sase-dev` and a `sase-dev`
console script.

Pros:

- Fits uv cleanly: `uv tool install sase` and `uv tool install sase-dev` would be separate tool environments.
- Makes the install command easy to explain.
- Reserves a PyPI name for the preview channel.

Cons:

- It creates a second public package and release stream.
- `sase version` currently treats `sase` as the host distribution name; this would need runtime host-distribution
  detection.
- Plugin discovery currently treats most `sase-*` distributions as plugins. `sase-dev` would need to be excluded from
  plugin classification.
- First-party plugins likely depend on `sase`. Installing `sase-github` into a `sase-dev` environment could pull the
  stable `sase` distribution into the same venv unless plugin dependencies are changed or constrained. Two distributions
  providing the same top-level `sase` package in one environment is a high-risk shape.

Verdict: attractive for a public preview channel, but too heavy and too risky as the first implementation.

### Option E: Publish a tiny `sase-dev` wrapper distribution

This package would provide only a `sase-dev` console script and depend on some development build of `sase`.

Pros:

- Avoids duplicating the `sase` import package under two distribution names.
- Keeps plugin dependencies pointed at a real `sase` host distribution.
- Could be uv-friendly if the dependency points at a versioned dev/pre-release of `sase`.

Cons:

- It still needs a development release stream for `sase` itself, such as `.devN` or pre-release wheels.
- If the wrapper depends on a git URL, PyPI publication is not a good fit.
- The wrapper adds another package to maintain before the core runtime-name problem is fixed.

Verdict: a reasonable future preview-channel design, but it depends on establishing dev/pre-release publishing first.

### Option F: Repo-owned `sase-dev` venv installer plus runtime executable resolver

This keeps the stable install exactly as-is and adds a SASE-owned dev install path:

```bash
uv tool install sase --python 3.12
just install-sase-dev
sase version
sase-dev version
```

The dev installer would:

1. Create or reuse a dedicated venv such as `~/.local/share/sase-dev/venv`.
2. Install this checkout into that venv, normally editable for local development.
3. Build/install `sase_core_rs` into that same venv when a sibling `sase-core` checkout and Rust toolchain are present.
4. Write `~/.local/bin/sase-dev` as a tiny wrapper that prepends the dev venv's `bin` directory to PATH and execs:

   ```bash
   python -m sase "$@"
   ```

5. Optionally accept `SASE_DEV_HOME=...` or document `SASE_HOME=~/.sase-dev sase-dev ...` for isolated state.

In parallel, SASE should add a runtime helper that resolves "the current SASE command" and replace hard-coded
`["sase", ...]` subprocesses with it.

Pros:

- Does not change the stable package or public release flow.
- Does not require uv to support a second tool identity for the same distribution.
- Avoids a second PyPI package until there is a real preview-channel policy.
- Lets local Rust core development target the dev venv explicitly.
- The wrapper can make legacy `sase` subprocess calls resolve to the dev venv while the codebase is migrated, because
  it can put the dev venv's `bin` directory first on PATH.

Cons:

- It is a project-specific installer instead of a pure packaging feature.
- Needs careful docs so users understand shared state vs isolated `SASE_HOME`.
- Still requires code cleanup for correctness, especially axe canonicalization and commit/bead subprocesses.

Verdict: best first implementation.

## Implementation Notes

### Runtime executable helper

Add a small helper, probably under `src/sase/main/` or `src/sase/core/`, that returns argv for the active runtime:

- If an env var such as `SASE_CLI_EXECUTABLE` is set, use it.
- Else if `sys.argv[0]` names an existing executable and is not a test placeholder, use that path.
- Else use `[sys.executable, "-m", "sase"]`.

On entry, set:

- `SASE_CLI_NAME` to `Path(sys.argv[0]).name` when available.
- `SASE_CLI_EXECUTABLE` to the resolved launcher path for child processes.

Then migrate internal subprocesses from:

```python
["sase", "commit", ...]
```

to:

```python
[*sase_cli_argv(), "commit", ...]
```

For axe, canonicalization should prefer `~/.local/bin/<SASE_CLI_NAME>` when the current command is `sase-dev`, not
always `~/.local/bin/sase`.

### Parser polish

Change the root parser `prog` and compact help examples to use the active CLI name. That makes `sase-dev --help` teach
`sase-dev doctor`, not `sase doctor`. This is polish, but it also makes support reports less confusing.

### Dev install target

Add a target such as:

```bash
just install-sase-dev
```

with optional variables:

- `sase_dev_venv := env_var_or_default("SASE_DEV_VENV", "~/.local/share/sase-dev/venv")`
- `sase_dev_bin := env_var_or_default("SASE_DEV_BIN", "~/.local/bin/sase-dev")`

It should reuse the existing `rust-install VENV` target rather than duplicating Rust build logic.

Also generalize the current uv-only Rust helper:

- Keep `just rust-install-uv-tool` for compatibility.
- Add `just rust-install-tool TOOL=sase` or document `just rust-install ~/.local/share/sase-dev/venv`.

### Docs and support commands

Document the difference explicitly:

```bash
uv tool install sase --python 3.12
just install-sase-dev

sase version
sase-dev version
sase doctor
sase-dev doctor
```

For isolated testing:

```bash
SASE_HOME=~/.sase-dev sase-dev doctor
SASE_HOME=~/.sase-dev sase-dev ace
```

For normal "try the dev runtime against my real projects," shared `~/.sase` is acceptable, but users should not run both
stable and dev axe daemons against the same `SASE_HOME`.

## Sources

- Local: `pyproject.toml`, `src/sase/main/parser.py`, `src/sase/axe/_process_start.py`,
  `src/sase/axe/orchestrator.py`, `src/sase/axe/run_agent_exec_plan_sdd.py`,
  `src/sase/workflows/commit/precommit_hooks.py`, `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`,
  `src/sase/ace/restore.py`, `Justfile`, `docs/rust_backend.md`, `docs/configuration.md`.
- uv tools guide: https://docs.astral.sh/uv/guides/tools/
- uv tools concept docs: https://docs.astral.sh/uv/concepts/tools/
- uv CLI reference: https://docs.astral.sh/uv/reference/cli/
- PyPA `pyproject.toml` guide: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
- pipx CLI reference: https://pipx.pypa.io/stable/reference/cli/
- pipx comparison docs: https://pipx.pypa.io/stable/explanation/comparisons/
- PyPI `sase` JSON: https://pypi.org/pypi/sase/json
- PyPI `sase-dev` JSON check: https://pypi.org/pypi/sase-dev/json

## Recommended Solution

Implement `sase-dev` as a first-class development runtime, but start with a repo-owned dev venv installer rather than a
second PyPI distribution.

The first implementation should include four pieces:

1. Add a current-executable helper and use it for all internal SASE subprocesses, especially commit, bead, axe daemon,
   and lumberjack paths.
2. Add `just install-sase-dev` to create a dedicated dev venv, install this checkout there, install local
   `sase_core_rs` into that venv when available, and write `~/.local/bin/sase-dev`.
3. Make parser/help and axe canonicalization respect the active command name so `sase-dev` stays in the dev runtime.
4. Document shared-state behavior clearly: `sase-dev` uses the normal `~/.sase` state unless the user sets
   `SASE_HOME=~/.sase-dev`; only one axe daemon should own a given state root.

After that path is stable, reconsider a published `sase-dev` wrapper or dev/pre-release channel. A full `sase-dev`
distribution should wait until plugin dependency behavior and runtime inventory support are designed, because otherwise
it risks installing two distributions that both provide the `sase` import package in the same environment.

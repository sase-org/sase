# `sase-dev` Parallel Install Strategy

Date: 2026-06-25
Status: Consolidated research

## Question

Should SASE support installing the development build under a different command name, such as `sase-dev`, so one machine
can keep both the latest release and the current development version? If yes, what implementation shape should SASE use?

This note consolidates the two prior research files:

- `sdd/research/202606/sase_dev_parallel_install.md`
- `sdd/research/202606/sase_dev_parallel_installs.md`

## Short Answer

Yes, `sase-dev` is the right user-facing command shape. It is not enough to rename the Python distribution or add one
more console script.

The real problem has three parts:

1. The stable release and dev checkout need different commands on `PATH`.
2. Any SASE subprocess launched from `sase-dev` must keep using the dev runtime, not whichever `sase` appears first on
   `PATH`.
3. True parallel operation needs isolated state, config, workspaces, daemon locks, and process discovery.

The recommended implementation is:

- Keep the distribution name, import package, entry-point groups, and Rust extension identity as `sase`.
- Add a repo-owned `sase-dev` installer that creates a dedicated dev venv and writes a thin `sase-dev` launcher.
- Add a current-runtime executable helper and migrate internal `["sase", ...]` subprocesses and axe re-exec paths to it.
- Add a first-class profile/path mechanism, e.g. `SASE_PROFILE=dev`, so `sase-dev` can default to isolated state while
  still allowing explicit shared-state overrides.

## Verified Baseline

### Packaging and install

- `pyproject.toml` declares distribution `name = "sase"`, version `0.5.0`, import package `src/sase`, and the required
  Rust wheel dependency `sase-core-rs>=0.2.0,<0.3.0`.
- `[project.scripts]` exposes `sase = "sase.main.entry:main"` plus helper scripts such as `sase_git_commit`,
  `sase_chop_*`, and `sase_xcmd`.
- The README's normal install path is `uv tool install sase --python 3.12`.
- uv tools are already isolated venvs. uv's docs say `uv tool install` creates a persistent isolated environment and
  links all executables provided by the package. The local `uv tool install --help` has no `--from` option, while
  `uv tool run --help` does.

Implication: stable and dev installs do not need different Python import names. The collisions are the linked command
name and shared runtime state outside the venv.

### Runtime state and config

Current defaults:

| Concern | Current path | Override today |
|---|---|---|
| SASE state root | `~/.sase` from `src/sase/core/paths.py` | `SASE_HOME` |
| User config | `~/.config/sase` from `src/sase/config/core.py` | none |
| Managed workspace root | platform state dir with a `sase` segment | `SASE_WORKSPACE_ROOT` |
| Axe lock, PIDs, logs, indexes | under `SASE_HOME` | via `SASE_HOME` |

`SASE_HOME` already isolates most state, including axe locks, PID files, notifications, chats, plans, artifacts, agent
indexes, and project records. It does not isolate `~/.config/sase`, and it does not by itself fix executables that
resolve literal `sase`.

The Rust side needs special care. `sase_gateway::default_sase_home()` honors `SASE_HOME`, but the Rust xprompt catalog
uses `HOME` to derive both `~/.config/sase` and `~/.sase/projects`. That means a profile implementation must update or
parameterize the Rust catalog path inputs too; gateway parity alone is not enough.

### Current hard-coded command assumptions

These are the important local call sites to fix before `sase-dev` is reliable:

- `src/sase/main/parser.py` hard-codes `prog="sase"`.
- `src/sase/workflows/commit/precommit_hooks.py` shells out to `["sase", "bead", ...]`.
- `src/sase/ace/restore.py` shells out to `["sase", "commit", ...]`.
- `src/sase/axe/run_agent_exec_plan_sdd.py` shells out to `["sase", "commit", ...]`.
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py` shells out to `["sase", "bead", "update", ...]`.
- `src/sase/axe/_process_start.py` and `src/sase/axe/orchestrator.py` resolve literal `sase` for daemon/lumberjack
  startup.
- `src/sase/axe/_process_stop.py` and `src/sase/agent/names/_common.py` use broad command-line checks containing
  `"sase"`, so process discovery is not scoped to one runtime/profile.

Some paths are already robust: `sase ace --tmux` and validation checks use `sys.executable -m sase`, which keeps the
current Python environment.

### Why a literal `sase-dev` distribution is risky

Publishing or building a full second distribution named `sase-dev` is attractive because uv would treat it as a separate
tool identity. It is a poor first implementation:

- `src/sase/version/_models.py` treats `sase` as the host distribution.
- `src/sase/version/_plugins.py` classifies most `sase-*` distributions as plugins except `sase-core-rs`, so `sase-dev`
  would need a special exclusion or runtime host-distribution detection.
- First-party plugins depend on `sase`; installing them into a `sase-dev` environment could pull the stable `sase`
  distribution into the same venv unless dependency policy changes.
- Two distributions that provide the same top-level `sase` package in one environment are high-risk.
- If the dev build is renamed at build time, it becomes easier to test a renamed artifact rather than the exact package
  that will ship.

As of this check, `https://pypi.org/pypi/sase-dev/json` returned 404, but PyPI name availability should not drive the
first implementation.

## Options

### Option A: Alias or `uvx --from`

Example:

```bash
alias sase-dev='uvx --from git+https://github.com/sase-org/sase@master sase'
```

This is useful for one-off smoke tests. It is not a persistent install, does not solve local Rust extension development,
and does not fix internal subprocesses that call `sase`.

Verdict: troubleshooting trick only.

### Option B: Add `sase-dev = "sase.main.entry:main"` to the main package

This is small but misleading. Once a stable release includes that script, `uv tool install sase` would also expose a
`sase-dev` command from the stable environment because uv links all package executables. Installing the checkout as the
same `sase` tool can also replace the stable uv tool environment.

Verdict: creates an alias, not a parallel install story.

### Option C: Use pipx `--suffix=-dev`

pipx supports a suffix for venv and executable names, so it can create `sase-dev` from the same distribution. Its docs
mark the suffix feature as experimental. More importantly, SASE's current install and Rust-helper docs standardize on uv,
and pipx does not fix SASE's internal `sase` subprocesses.

Verdict: viable escape hatch, not the primary supported path unless SASE adopts pipx as a first-class installer too.

### Option D: Publish a full `sase-dev` distribution

This makes `uv tool install sase-dev` clean, and might be appropriate later for a public preview channel. It requires
host-distribution detection, plugin classification changes, plugin dependency policy changes, and careful handling of
duplicate top-level package providers.

Verdict: too much blast radius for the first implementation.

### Option E: Tiny published `sase-dev` wrapper package

A small package could expose only a `sase-dev` script and depend on a dev/pre-release `sase`. This avoids duplicating the
import package but requires an actual dev release stream first.

Verdict: reasonable future preview-channel design after local dev support is solid.

### Option F: Repo-owned `sase-dev` installer plus profile-aware runtime identity

Add a target such as:

```bash
just install-sase-dev
```

It would:

1. Create or reuse a dedicated venv, e.g. `~/.local/share/sase-dev/venv`.
2. Install this checkout into that venv, normally editable.
3. Reuse `just rust-install <venv>` so a sibling `sase-core` checkout is installed into the same dev venv.
4. Write `~/.local/bin/sase-dev` as a thin launcher.
5. Set runtime identity/profile env vars before execing the dev venv's Python module.

Launcher sketch:

```sh
#!/bin/sh
venv="${SASE_DEV_VENV:-$HOME/.local/share/sase-dev/venv}"
export SASE_CLI_NAME="${SASE_CLI_NAME:-sase-dev}"
export SASE_CLI_EXECUTABLE="${SASE_CLI_EXECUTABLE:-$HOME/.local/bin/sase-dev}"
export SASE_PROFILE="${SASE_PROFILE:-dev}"
export PATH="$venv/bin:$PATH"
exec "$venv/bin/python" -m sase "$@"
```

The wrapper should not be the only fix. SASE should also expose a small current-runtime helper, for example
`sase_cli_argv()`, that returns:

1. `SASE_CLI_EXECUTABLE` when set.
2. The current venv-local executable matching `SASE_CLI_NAME`.
3. A fallback of `[sys.executable, "-m", "sase"]`.

Then internal subprocesses should use `[*sase_cli_argv(), ...]` instead of `["sase", ...]`. Axe canonicalization should
prefer the active runtime and profile, not always `~/.local/bin/sase`.

Verdict: best first implementation.

## Profile and Path Design

`sase-dev` as a command name does not automatically isolate state. The safer default is to make the dev launcher set
`SASE_PROFILE=dev` and let explicit overrides opt back into sharing.

Suggested path rules:

- `SASE_HOME` wins when set.
- Else no profile keeps today's `~/.sase`.
- Else `SASE_PROFILE=dev` maps state to `~/.sase-dev`.
- Add `SASE_CONFIG_DIR`; when unset, use `~/.config/sase` without a profile and `~/.config/sase-dev` with a profile.
- `SASE_WORKSPACE_ROOT` wins when set.
- Else profile the platform default workspace segment: `sase` or `sase-dev`.
- Include `SASE_PROFILE`, `SASE_CLI_NAME`, and `SASE_CLI_EXECUTABLE` in spawned SASE child processes.

This preserves today's behavior by default while making `sase-dev` safe for simultaneous stable/dev axe use. Users who
intentionally want to test the dev runtime against normal state can do so by setting explicit state/config overrides.

Rust parity requirement:

- Update `sase_gateway::default_sase_home()` or pass a computed state root so it understands the same profile rules.
- Update the Rust xprompt catalog to stop deriving config and project paths only from `HOME`; it should receive or derive
  the same state/config roots as Python.
- Add parity tests for default, explicit `SASE_HOME`, explicit `SASE_CONFIG_DIR`, and `SASE_PROFILE=dev`.

## Implementation Rollout

1. Add a Python current-runtime helper and replace internal `["sase", ...]` subprocesses in commit, bead, restore, axe,
   and related paths.
2. Make parser/help use the active CLI name, so `sase-dev --help` prints `sase-dev`, not `sase`.
3. Add `just install-sase-dev` and the wrapper in `~/.local/bin/sase-dev`; reuse the existing `rust-install <venv>`
   target rather than duplicating Rust build logic.
4. Add profile-aware path helpers in Python for state, config, and workspace roots; keep explicit env vars as the highest
   precedence.
5. Mirror the path contract in `sase-core` and add cross-language parity tests.
6. Make axe process detection and stop/start behavior profile-aware. Do not document simultaneous stable and dev axe
   daemons until this lands.
7. Document three modes:
   - Stable release: `uv tool install sase --python 3.12`.
   - Local dev install: `just install-sase-dev`.
   - Shared-state testing: explicit `SASE_HOME` / `SASE_CONFIG_DIR` overrides for advanced use.

## Source References

- Local package/install: `pyproject.toml`, `README.md`, `Justfile`, `docs/rust_backend.md`.
- Local state/config/workspace paths: `src/sase/core/paths.py`, `src/sase/config/core.py`,
  `src/sase/workspace_provider/store.py`.
- Runtime executable and subprocess call sites: `src/sase/axe/_process_start.py`, `src/sase/axe/orchestrator.py`,
  `src/sase/axe/_process_stop.py`, `src/sase/agent/names/_common.py`, `src/sase/workflows/commit/precommit_hooks.py`,
  `src/sase/ace/restore.py`, `src/sase/axe/run_agent_exec_plan_sdd.py`,
  `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`.
- Plugin/version classification: `src/sase/version/_models.py`, `src/sase/version/_plugins.py`.
- Rust path behavior: `/home/bryan/projects/github/sase-org/sase-core/crates/sase_gateway/src/routes.rs`,
  `/home/bryan/projects/github/sase-org/sase-core/crates/sase_core/src/xprompt_catalog.rs`.
- uv tools docs: https://docs.astral.sh/uv/concepts/tools/ and https://docs.astral.sh/uv/reference/cli/#uv-tool-install.
- pipx suffix docs: https://pipx.pypa.io/stable/docs/#pipx-install.

## Recommended Solution

Implement `sase-dev` as a first-class local development runtime, not as a renamed SASE distribution.

The first supported version should ship a repo-owned `just install-sase-dev` that installs the checkout into a dedicated
venv, installs local `sase_core_rs` into that venv when available, and writes a `~/.local/bin/sase-dev` launcher. That
launcher should set the active CLI identity and default to `SASE_PROFILE=dev`.

In the same change set, add a current-runtime executable helper and migrate internal `sase` subprocesses and axe
re-exec paths to it. Then add profile-aware state/config/workspace path derivation in both Python and the Rust core. This
keeps the shipped artifact identity stable, avoids plugin misclassification, works with the existing uv release install,
and gives Bryan a safe daily setup with `sase` for release behavior and `sase-dev` for development behavior.

# Parallel Installs: Running a Dev Build Alongside the Release (`sase` + `sase-dev`)

**Date:** 2026-06-25
**Status:** Research / recommendation
**Author:** research agent

## TL;DR

The goal — "have the latest release *and* a development build installed at the
same time" — is a good and reasonable goal. But **literally renaming the
distribution/binary to `sase-dev` is the wrong way to get there.** The canonical
install path is already environment-isolated (`uv tool install sase` gives each
install its own venv), so the Python package name, import name, and console
script never actually collide between two installs. Renaming the distribution
would instead create a *new* problem: the plugin/version subsystem classifies
any `sase-`-prefixed distribution as a plugin (`HOST_DISTRIBUTION_NAME = "sase"`),
so a `sase-dev` distribution would be mis-detected as a plugin of itself.

The problem really decomposes into two orthogonal pieces:

1. **The command name on `PATH`** — both installs want to be `sase`.
2. **Runtime-state isolation** — both installs write to `~/.sase`,
   `~/.config/sase`, the shared workspace root, the same daemon lock, the same
   SQLite indexes, and the same PID/process namespace.

`SASE_HOME` already solves most of (2) for `~/.sase`-rooted state, but there are
real gaps: `~/.config/sase` has no override (and is hardcoded in **both** Python
and the Rust core), the workspace root is only overridable on Linux, the axe
daemon re-execs whichever `sase` it finds on `PATH`, and process detection
matches the substring `"sase"`.

**Recommendation:** Add a single first-class **instance/profile switch**
(`SASE_PROFILE`, default empty = today's behavior) that uniformly suffixes every
state/config/workspace path and scopes the daemon + process detection, mirrored
across the Python ⇄ Rust-core boundary. Expose the dev build as `sase-dev`
through a thin wrapper/symlink that sets `SASE_PROFILE=dev`. This keeps the dev
artifact **byte-identical to the release** (you test the real thing, not a
renamed fork), has a small, well-contained blast radius, and is future-proof
(`SASE_PROFILE=staging`, per-experiment sandboxes, CI isolation, etc.).

---

## 1. Problem statement

The user wants to run two SASE installs concurrently:

- `sase` → the latest published release (`uv tool install sase`).
- `sase-dev` → a development build (local editable checkout).

…without the two stomping on each other's state, daemons, or workspaces, and
ideally with an ergonomic separate command name for the dev build.

**Non-goals:** publishing a second `sase-dev` distribution to PyPI; supporting
arbitrary N simultaneous installs in a *single* venv; sandboxing for security.

---

## 2. How `sase` is installed and where its state lives today

### 2.1 Packaging & install (factual baseline)

- Build backend: **hatchling**; distribution name `sase`; import package `sase`
  (`src/sase/`); version is static (`pyproject.toml` `version` +
  `src/sase/__init__.py __version__`, kept in sync by release-please).
- Canonical install is an **isolated per-tool venv**:
  `uv tool install sase --python 3.12` (`README.md:28`). `pip install sase` and
  plain venvs are also supported.
- `[project.scripts]` (`pyproject.toml:91-112`) defines the `sase` entry point
  (`sase = "sase.main.entry:main"`) plus ~20 `sase_*` helper scripts
  (`sase_bug`, `sase_git_commit`, `sase_chop_*`, `sase_xcmd`, …).
- Plugin entry-point groups (`pyproject.toml:114-127`): `sase_llm`, `sase_vcs`,
  `sase_workspace` (+ `sase_config`, `sase_plugin_manifest`, `sase_xprompts`
  enumerated in `src/sase/plugins/inventory.py:15-28`). Plugins are **separate
  distributions** auto-discovered by entry-point group, not by being installed
  in any particular way.
- The Rust backend `sase-core-rs` is a **separate published wheel**
  (`pyproject.toml:47`, `sase-core-rs>=0.2.0,<0.3.0`), imported as the module
  `sase_core_rs` (`src/sase/core/rust.py:24`). For dev it is built from the
  sibling `../sase-core` checkout via `just rust-install`. **No standalone Rust
  binary** named `sase` exists — the CLI is the Python console script.

**Key consequence:** because `uv tool` / editable venvs isolate the Python
environment, the import package name, the console-script *definitions*, and the
entry-point group names **do not collide** between two installs. They live in
different `site-packages`. Only two things leak across the boundary: the
**exposed command name** on `PATH`, and the **runtime state** under the user's
home directory.

### 2.2 Where runtime state lives

| Concern | Path / source | Env override? |
|---|---|---|
| State root | `~/.sase` (`src/sase/core/paths.py:45-47`) | ✅ `SASE_HOME` |
| Config dir | `~/.config/sase` (`src/sase/config/core.py:24`) | ❌ none |
| Workspace root | platform dirs w/ hardcoded `sase` segment (`src/sase/workspace_provider/store.py:177-198`) | ⚠️ `SASE_WORKSPACE_ROOT` (Linux path honors `XDG_STATE_HOME`; macOS/Windows segments hardcoded) |
| Temp dir | system default | ✅ `SASE_TMPDIR` |
| SQLite: notifications index | `~/.sase/notifications/index.sqlite` | via `SASE_HOME` |
| SQLite: agent artifact index | `~/.sase/agent_artifact_index.sqlite` | via `SASE_HOME` |
| Agent name registry | `~/.sase/agent_name_registry.json` | via `SASE_HOME` |
| Axe daemon lock | `~/.sase/axe/orchestrator.lock` (`fcntl.flock`) | via `SASE_HOME` |
| Axe PID / lumberjack PIDs / logs / chop state | `~/.sase/axe/**` | via `SASE_HOME` |

So `SASE_HOME` already isolates everything rooted at `~/.sase` (locks, PIDs,
SQLite, registries, logs). The **un-isolated** pieces are:

1. **`~/.config/sase`** — hardcoded, no override. Also hardcoded in the Rust
   core (`crates/sase_core/src/xprompt_catalog.rs:1454` returns
   `~/.config/sase/{rel}`; config-parity tests assume the same).
2. **Workspace root on macOS/Windows** — `SASE_WORKSPACE_ROOT` overrides on all
   platforms, but the *default* segment `sase` is hardcoded per-platform.
3. **Axe daemon binary self-resolution** — `_resolve_sase_executable`
   (`src/sase/axe/_process_start.py:217-247`) and
   `Orchestrator._find_sase_executable` (`src/sase/axe/orchestrator.py:43-59`)
   prefer `~/.local/bin/sase` / `shutil.which("sase")`. Under a dev install
   these would re-exec the **release** binary for long-lived daemons.
4. **Process detection by name** — `"sase" not in command`
   (`src/sase/axe/_process_stop.py:339`) and the agent-PID guard
   (`src/sase/agent/names/_common.py:96`) match the substring `"sase"`, so one
   install's `axe stop` / scans see the other install's processes.

### 2.3 Cross-language boundary (important)

Per `memory/rust_core_backend_boundary.md`, state/config path resolution is
backend logic that must match across frontends. Today:

- **Parity exists** for `SASE_HOME`: Rust `default_sase_home()`
  (`crates/sase_gateway/src/routes.rs:473-482`) reads `SASE_HOME` then falls
  back to `~/.sase`.
- **No parity / no override** for the config dir: Rust hardcodes
  `~/.config/sase` and `~/.sase/projects` in `xprompt_catalog.rs`.

Any profile/instance mechanism therefore has to be implemented (or at least
honored) in **both** repos to avoid drift.

---

## 3. Collision inventory & blast radius of a literal rename

If we instead chose to literally rename the distribution + binary to `sase-dev`,
the following would all need to change or break (this is why we *don't*
recommend it):

- `prog="sase"` in the arg parser (`src/sase/main/parser.py:379`).
- All ~20 `[project.scripts]` names, plus `sase_xcmd` referenced by the default
  `x:` xprompt (`src/sase/default_config.yml:549`).
- Hardcoded self-invocations that shell out to `sase`/`-m sase`:
  `precommit_hooks.py:94,99` (`sase bead close/sync`), `restore.py:218`
  (`sase commit`), `ace_tmux.py:123` (`-m sase`), `run_agent_exec_plan_sdd.py:53`
  (`sase commit`), `_git_commit_dispatch.py:214` (`sase bead update`),
  `validate_handler.py:51` (`-m sase`). These break silently under a rename.
- Plugin/version subsystem: `HOST_DISTRIBUTION_NAME = "sase"`
  (`src/sase/version/_models.py:10`) and
  `is_sase_plugin_distribution_name()` (`src/sase/version/_plugins.py:209-213`)
  classify any `sase-`-prefixed dist (except `sase-core-rs`) as a **plugin** — a
  `sase-dev` distribution would be mis-detected as a plugin of itself.
- Rust module name `sase_core_rs` (`src/sase/core/rust.py:24`), entry-point group
  names, import package `src/sase` → `src/sase_dev`, coverage config, build
  targets.
- Semantic divergence risk: you'd be testing a *renamed fork*, not the artifact
  you actually ship.

---

## 4. Alternative approaches

### Approach A — Instance/profile env switch + thin `sase-dev` launcher  ★ recommended

Introduce one switch, `SASE_PROFILE` (default empty ⇒ exactly today's paths).
When set to e.g. `dev`, every state/config/workspace path gets a uniform
`-dev` suffix and the daemon + process namespace are scoped to it:

- `sase_home()` → `~/.sase-dev` (explicit `SASE_HOME` still wins).
- config dir → `~/.config/sase-dev`.
- workspace root default segment → `sase-dev` (all platforms).
- daemon lock/PID/logs follow `~/.sase-dev/axe/**` automatically.

Expose the dev build as a command:

```sh
# wrapper or symlink; sets the profile, then execs the dev venv's own binary
sase-dev() { SASE_PROFILE=dev exec "$HOME/.venvs/sase-dev/bin/sase" "$@"; }
```

(or `uv tool install` the release as usual and keep the dev build in a plain
editable venv — `just install` already produces one in the checkout's `.venv`.)

**Required supporting fixes (also needed by most other approaches):**

- Add a single `profile_suffix()` / `app_dir_name()` helper in
  `src/sase/core/paths.py` and route `config/core.py` + `workspace_provider/store.py`
  through it; add a `SASE_CONFIG_DIR` (or profile-derived) override.
- Mirror the same derivation in the Rust core (`default_sase_home`, the
  `~/.config/sase` references in `xprompt_catalog.rs`) and update bindings/wire +
  config-parity tests so Python and Rust agree.
- Fix daemon self-resolution (`_process_start.py`, `orchestrator.py`) to prefer
  `sys.argv[0]` / the current venv's own `bin/sase` over `~/.local/bin/sase` and
  `which("sase")`, so the dev daemon re-execs the dev binary.
- Make process detection profile-aware: match on the resolved executable path or
  a profile marker (e.g. an env var stamped on spawned processes) rather than the
  bare substring `"sase"`.

**Pros:** smallest, most contained code change; dev artifact byte-identical to
release; one switch isolates *everything* (no path can be missed); no
plugin-misdetection; works cross-platform; future-proof (staging, CI, per-branch
sandboxes). **Cons:** dev command is a wrapper/symlink rather than a "real"
installed binary; requires the Rust-core parity change; daemon/process-scoping
needs care.

### Approach B — Literal distribution + binary rename to `sase-dev`

Rename `[project] name`, all scripts, `prog=`, import package, entry-point
groups, Rust module, and parameterize every hardcoded `["sase", …]`.

**Pros:** `sase-dev` is a first-class binary; could even coexist in one venv.
**Cons:** the full blast radius in §3; plugin/version mis-detection; you ship and
test a *renamed* artifact (divergence); high ongoing maintenance (every new
`sase` self-invocation must be parameterized forever). Not recommended.

### Approach C — `SASE_HOME`-only alias (minimal, leaky)

`sase-dev` alias that sets only `SASE_HOME=~/.sase-dev`.

**Pros:** zero code change today. **Cons:** leaves `~/.config/sase` shared,
workspace root shared on non-Linux, daemon re-execs the wrong binary, and process
scans cross-contaminate. Acceptable only as a stopgap, and the config sharing in
particular is a real footgun if dev changes the config schema.

### Approach D — Container / devcontainer isolation

Run the dev build in a container with its own `HOME`.

**Pros:** total isolation, no code change. **Cons:** fights SASE's host-integrated
model (tmux respawn, host workspace clones, host PATH agents); heavyweight for an
everyday dev/release split. Not a fit.

### Approach E — Build-time name templating

Rewrite the name at build time (sed/hatch hook) to produce a `sase-dev` wheel.

**Cons:** all of Approach B's runtime problems plus brittle build machinery.
Reject.

---

## 5. Recommended solution

**Adopt Approach A: a first-class `SASE_PROFILE` instance switch, plus a thin
`sase-dev` launcher, with the supporting isolation fixes — mirrored across the
Python ⇄ Rust-core boundary.**

Rationale:

1. **It matches reality.** The install path is already venv-isolated, so the only
   genuine collisions are the PATH command name and runtime state. Approach A
   targets exactly those and nothing else.
2. **No identity churn, no divergence.** The package, import name, console
   scripts, entry-point groups, and Rust module all stay `sase`. The dev build is
   the *same artifact* as the release — you test what you ship. It also sidesteps
   the `HOST_DISTRIBUTION_NAME`/plugin mis-detection trap entirely.
3. **One switch, total isolation.** A single profile-derived suffix means no
   state path can be accidentally missed (the failure mode of the `SASE_HOME`-only
   alias). It composes with the existing `SASE_HOME` / `SASE_WORKSPACE_ROOT`
   overrides rather than replacing them.
4. **Small, well-bounded change.** Concentrated in `core/paths.py`,
   `config/core.py`, `workspace_provider/store.py`, the two axe binary/process
   modules, and the matching Rust resolvers — versus the repo-wide rename of
   Approach B.
5. **Future-proof.** The same mechanism yields `SASE_PROFILE=staging`, isolated
   CI runs, and per-experiment sandboxes for free.

**Suggested rollout order:**

1. Land the `SASE_PROFILE` derivation in Python (paths/config/workspace) with
   default-empty = no behavior change, plus tests.
2. Mirror it in `../sase-core` (`default_sase_home`, `xprompt_catalog` config
   dir) + bindings + config-parity tests.
3. Scope the axe daemon: prefer the venv-local binary for re-exec; make process
   detection profile-aware.
4. Document the `sase-dev` wrapper/symlink recipe and add a `just` recipe to
   install the dev build into a dedicated venv.

**Open questions for the user:**

- **Config sharing:** should `~/.config/sase` be isolated per profile (safest,
  the default above) or shared so keymaps/xprompts carry across both installs?
  A profile could opt into sharing via an explicit `SASE_CONFIG_DIR`.
- **Command surface:** is a `sase-dev` wrapper/symlink acceptable, or do you want
  a genuine second installed entry point (which nudges toward a narrower variant
  of Approach B for the binary name only)?
- **Scope of "dev":** just your local editable checkout, or also pre-release
  builds installed from git refs?

---

## Appendix — key source references

- `pyproject.toml:6,7,47,91-127` — name, version, `sase-core-rs` dep, scripts,
  entry-point groups.
- `README.md:28` — `uv tool install sase` (isolated-venv install).
- `src/sase/core/paths.py:45-47` — `sase_home()` / `SASE_HOME`.
- `src/sase/config/core.py:24` — hardcoded `~/.config/sase`, no override.
- `src/sase/workspace_provider/store.py:25,177-198` — `SASE_WORKSPACE_ROOT`,
  per-platform `sase` segments.
- `src/sase/axe/_process_start.py:217-247`, `src/sase/axe/orchestrator.py:43-59`
  — daemon binary self-resolution.
- `src/sase/axe/_process_stop.py:339`, `src/sase/agent/names/_common.py:96` —
  process detection by `"sase"` substring.
- `src/sase/version/_models.py:10-13`, `src/sase/version/_plugins.py:193-213` —
  `HOST_DISTRIBUTION_NAME`, plugin classification by `sase-` prefix.
- `src/sase/main/parser.py:379` — `prog="sase"`.
- Self-invocations: `src/sase/workflows/commit/precommit_hooks.py:94,99`,
  `src/sase/ace/restore.py:218`, `src/sase/main/ace_tmux.py:123`,
  `src/sase/axe/run_agent_exec_plan_sdd.py:53`,
  `src/sase/vcs_provider/plugins/_git_commit_dispatch.py:214`,
  `src/sase/main/validate_handler.py:51`.
- Rust core (`../sase-core`): `crates/sase_gateway/src/routes.rs:473-482`
  (`default_sase_home` honors `SASE_HOME`);
  `crates/sase_core/src/xprompt_catalog.rs:1454,1588` (hardcoded
  `~/.config/sase`, `~/.sase/projects`); `crates/sase_core/tests/config_parity.rs`
  (config-dir assumptions).

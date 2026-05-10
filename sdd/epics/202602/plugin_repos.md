---
bead_id: sase-dx8
status: done
---

# Plan: Extract VCS Plugins into Separate Repos

## Context

The sase monolith bundles all VCS providers (GitHub, bare-git, Mercurial), their xprompts, scripts, and config together.
This prevents per-team/per-company customization and forces users to install Mercurial tooling even if they only use
GitHub. This plan extracts VCS functionality into two plugin packages (`sase-github`, `retired Mercurial plugin`) that contribute VCS
hooks, xprompts, scripts, and config defaults via entry points.

**PyPI name availability**: `sase`, `sase-github`, `retired Mercurial plugin` are all available (confirmed via PyPI API).

## Directory Convention

Each phase is executed by a distinct `claude` instance. These instances run in directories like
`~/projects/github/bbugyi200/sase_<N>/` (not the real `~/projects/github/bbugyi200/sase/`). When a phase makes changes
to sase core, the agent should modify files in whatever `sase_<N>` directory it was started in. Plugin repos
(`sase-github`, `retired Mercurial plugin`) are at their canonical paths (`~/projects/github/bbugyi200/sase-github/`, etc.).

## What Stays in Core vs What Moves

| Resource                                                                                              | Destination     | Rationale                                                           |
| ----------------------------------------------------------------------------------------------------- | --------------- | ------------------------------------------------------------------- |
| `_hookspec.py`, `_plugin_manager.py`, `_registry.py`, `_base.py`, `_command_runner.py`, `_types.py`   | **Core**        | Plugin API surface                                                  |
| `_git_common.py` (GitCommon mixin)                                                                    | **Core**        | Shared by BareGitPlugin (core) and GitHubPlugin (sase-github)       |
| `BareGitPlugin`                                                                                       | **Core**        | Simple default for non-hosted git                                   |
| `GitHubPlugin`                                                                                        | **sase-github** | GitHub-specific (gh CLI for PRs)                                    |
| `HgPlugin`                                                                                            | **retired Mercurial plugin** | Mercurial-specific                                                  |
| `gh.yml`, `pr.yml`, `new_pr_desc.yml`                                                                 | **sase-github** | GitHub xprompts                                                     |
| `hg.yml`, `cl.yml`, `propose.yml`                                                                     | **retired Mercurial plugin** | Mercurial xprompts                                                  |
| `git.yml`, `commit.yml`, `sync.yml`, `mentor.md`, `fix_hook.md`, etc.                                 | **Core**        | VCS-agnostic or bare-git                                            |
| All `sase_hg_*` shell scripts, `sase_cl_workflow`, `sase_propose_workflow`, metahook scripts          | **retired Mercurial plugin** | Mercurial scripts                                                   |
| `gh_setup.py`, `hg_setup.py`, `git_setup.py`, `pr_create_changespec.py`, `new_pr_desc_get_context.py` | **Core**        | Deep sase imports; xprompts reference them as `from sase.scripts.*` |
| `sase_chop_*`, `sase_commit_workflow`, `sase_split_*`, `sase_json_workflow`                           | **Core**        | VCS-agnostic                                                        |
| `cldd.md`, `crs.md`                                                                                   | **retired Mercurial plugin** | CL/critique-specific (Mercurial workflow)                           |

---

## Phase 1: Plugin Discovery Infrastructure

**Goal**: Add entry-point-based plugin discovery to sase core so external packages can contribute xprompts, config
defaults, and VCS providers. Refactor the VCS registry to use generic entry-point-based dispatch.

### 1a. Create shared plugin discovery module

**Create `src/sase/plugin_discovery.py`**:

- `discover_plugin_resources(group: str) -> list[ModuleType]` — loads entry points for a group, returns imported modules
- `is_plugin_disabled(group_suffix: str) -> bool` — checks `SASE_DISABLE_PLUGINS` and
  `SASE_DISABLE_PLUGIN_{XPROMPTS,CONFIG,VCS}` env vars
- Uses `importlib.metadata.entry_points(group=group)` and `importlib.resources.files(module)`

### 1b. Add xprompt plugin discovery

**Modify `src/sase/xprompt/loader.py`**:

- Add `_load_xprompts_from_plugins() -> dict[str, XPrompt]` — scans `sase_xprompts` entry point group, uses
  `importlib.resources.files(module).joinpath("xprompts")` to find `.md` files
- Insert into `get_all_xprompts()` at priority 7 (between config and internal)

**Modify `src/sase/xprompt/workflow_loader.py`**:

- Add `_load_workflows_from_plugins() -> dict[str, Workflow]` — same pattern for `.yml`/`.yaml` files
- Insert into `get_all_workflows()` at same priority level

New priority order:

```
1-4: Filesystem (CWD, home) — unchanged
5:   Project-specific — unchanged
6:   Config (sase.yml) — unchanged
7:   Plugin packages (via sase_xprompts entry points) — NEW
8:   Internal sase package (was 7) — bumped
```

### 1c. Add config plugin discovery

**Modify `src/sase/config.py`**:

- Add `_load_plugin_configs() -> list[dict[str, Any]]` — scans `sase_config` entry point group, loads
  `default_config.yml` from each plugin package
- Insert into `load_merged_config()` merge chain between sase defaults and user config (list concatenation semantics)

New merge chain:

```
1. sase default_config.yml (bundled)
2. Plugin default_config.yml files (sorted by EP name) — NEW
3. ~/.config/sase/sase.yml (user, lists replace)
4. ~/.config/sase/sase_*.yml overlays (lists concatenate)
```

### 1d. Refactor VCS registry to use generic entry-point discovery

**Modify `src/sase/vcs_provider/_registry.py`**:

- Replace the three `_create_{github,hg,bare_git}_plugin_provider()` functions with a single generic approach:

```python
def _create_provider_for(vcs_name: str) -> VCSPluginManager:
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    plugin_class = _find_plugin_class(vcs_name)
    if plugin_class is None:
        raise VCSProviderNotFoundError(
            f"No VCS plugin for '{vcs_name}'. Install the plugin package "
            f"(e.g., pip install sase-{vcs_name.replace('_', '-')})"
        )
    pm.register(plugin_class())
    return VCSPluginManager(pm)

def _find_plugin_class(vcs_name: str) -> type | None:
    from importlib.metadata import entry_points
    for ep in entry_points(group="sase_vcs"):
        if ep.name == vcs_name:
            return ep.load()
    return None
```

- `get_vcs_provider()` becomes: resolve name → `_create_provider_for(vcs_name)`

### 1e. Tests

**Create `tests/test_plugin_discovery.py`**:

- Test plugin xprompt discovery with mocked entry points
- Test plugin config merging
- Test env var disable mechanism
- Test priority ordering (plugin loses to user, wins over internal)
- Test VCS registry with mocked entry points

### Verification

```bash
just check  # All existing tests still pass
# No behavioral regression — no plugin packages installed yet, so discovery finds nothing
```

### Key files

- `src/sase/plugin_discovery.py` (new)
- `src/sase/xprompt/loader.py` (modify `get_all_xprompts`)
- `src/sase/xprompt/workflow_loader.py` (modify `get_all_workflows`)
- `src/sase/config.py` (modify `load_merged_config`)
- `src/sase/vcs_provider/_registry.py` (refactor to generic entry-point dispatch)
- `tests/test_plugin_discovery.py` (new)

---

## Phase 2: Create sase-github Plugin Package

**Goal**: Create `~/projects/github/bbugyi200/sase-github/` with GitHubPlugin, GitHub xprompts, and proper entry points.
Remove moved files from sase core. Create initial git commit.

### Package structure

```
sase-github/
  .github/workflows/
    ci.yml
    publish.yml
  src/sase_github/
    __init__.py          # exports GitHubPlugin, hookimpl
    plugin.py            # GitHubPlugin (moved from core)
    xprompts/
      gh.yml             # moved from core xprompts/
      pr.yml             # moved from core xprompts/
      new_pr_desc.yml    # moved from core xprompts/
  tests/
    __init__.py
    conftest.py
    test_github_plugin.py  # adapted from core tests
  pyproject.toml
  Justfile
  LICENSE
  CLAUDE.md
```

### pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sase-github"
version = "0.1.0"
description = "GitHub VCS plugin for sase"
requires-python = ">=3.12"
license = "MIT"
dependencies = ["sase>=0.1.0"]

[project.entry-points."sase_vcs"]
github = "sase_github.plugin:GitHubPlugin"

[project.entry-points."sase_xprompts"]
sase_github = "sase_github"

[tool.hatch.build.targets.wheel]
packages = ["src/sase_github"]
```

### plugin.py imports

```python
from sase.vcs_provider._hookspec import hookimpl
from sase.vcs_provider.plugins._git_common import GitCommon
```

GitCommon stays in core — sase-github imports from the `sase` dependency.

### Changes to sase core

- Delete `src/sase/vcs_provider/plugins/github.py`
- Delete `xprompts/gh.yml`, `xprompts/pr.yml`, `xprompts/new_pr_desc.yml`
- Remove `github` entry from `[project.entry-points."sase_vcs"]` in pyproject.toml
- Move/adapt `tests/test_vcs_provider_github_plugin.py` to sase-github (update imports)
- Run `just install` to refresh entry points after pyproject.toml changes

### Verification

```bash
# In sase core (without sase-github installed):
just check  # Passes; github plugin not available

# Install sase-github:
pip install -e ~/projects/github/bbugyi200/sase-github/

# Verify plugin works:
# - #gh, #pr, #new_pr_desc xprompts are available
# - SASE_VCS_PROVIDER=github works
```

### Key files

- `~/projects/github/bbugyi200/sase-github/` (new repo)
- `src/sase/vcs_provider/plugins/github.py` (delete)
- `xprompts/gh.yml`, `xprompts/pr.yml`, `xprompts/new_pr_desc.yml` (delete)
- `pyproject.toml` (remove github entry point)

---

## Phase 3: Create retired Mercurial plugin Plugin Package

**Goal**: Create `~/projects/github/bbugyi200/retired Mercurial plugin/` with HgPlugin, Mercurial xprompts, all hg shell scripts,
config defaults, and entry points. Remove moved files from sase core. Create initial git commit.

### Package structure

```
retired Mercurial plugin/
  .github/workflows/
    ci.yml
    publish.yml
  src/sase_hg/
    __init__.py
    plugin.py              # HgPlugin (moved from core)
    default_config.yml     # Hg-specific config (metahook definitions)
    xprompts/
      hg.yml               # moved
      cl.yml               # moved
      propose.yml          # moved
      cldd.md              # moved
      crs.md               # moved
    scripts/
      __init__.py          # Shell script dispatch (same _exec_script pattern)
      sase_hg_amend        # moved (15 sase_hg_* scripts)
      sase_hg_archive
      sase_hg_branch_bug
      sase_hg_clean
      sase_hg_get_workspace
      sase_hg_lint
      sase_hg_patch
      sase_hg_presubmit
      sase_hg_prune
      sase_hg_rebase
      sase_hg_rename
      sase_hg_reword
      sase_hg_sync
      sase_hg_unamend
      sase_hg_update
      sase_hg_upload
      sase_hg_rewind
      sase_cl_workflow
      sase_propose_workflow
      sase_metahook_scuba
      sase_metahook_hg_presubmit_tap
  tests/
    __init__.py
    conftest.py
    test_hg_plugin.py
  pyproject.toml
  Justfile
  LICENSE
  CLAUDE.md
```

### pyproject.toml

```toml
[project]
name = "retired Mercurial plugin"
version = "0.1.0"
description = "Mercurial/Fig VCS plugin for sase"
requires-python = ">=3.12"
license = "MIT"
dependencies = ["sase>=0.1.0"]

[project.scripts]
sase_hg_amend = "sase_hg.scripts:sase_hg_amend"
# ... all 15 sase_hg_* scripts + sase_cl_workflow, sase_propose_workflow,
#     sase_metahook_scuba, sase_metahook_hg_presubmit_tap, sase_hg_rewind

[project.entry-points."sase_vcs"]
hg = "sase_hg.plugin:HgPlugin"

[project.entry-points."sase_xprompts"]
sase_hg = "sase_hg"

[project.entry-points."sase_config"]
sase_hg = "sase_hg"
```

### Changes to sase core

- Delete `src/sase/vcs_provider/plugins/hg.py`
- Delete `xprompts/hg.yml`, `xprompts/cl.yml`, `xprompts/propose.yml`, `xprompts/cldd.md`, `xprompts/crs.md`
- Delete all `sase_hg_*` shell scripts from `src/sase/scripts/`
- Delete `sase_cl_workflow`, `sase_propose_workflow`, `sase_metahook_scuba`, `sase_metahook_hg_presubmit_tap` from
  `src/sase/scripts/`
- Remove all corresponding entries from `[project.scripts]` and `[project.entry-points."sase_vcs"]` in pyproject.toml
- Remove wrapper functions from `src/sase/scripts/__init__.py`
- Move/adapt hg test files to retired Mercurial plugin
- Run `just install` to refresh

### Verification

```bash
# In sase core (without retired Mercurial plugin installed):
just check  # Passes; hg plugin not available

# Install retired Mercurial plugin:
pip install -e ~/projects/github/bbugyi200/retired Mercurial plugin/

# Verify:
# - #hg, #cl, #propose xprompts are available
# - SASE_VCS_PROVIDER=hg works
# - sase_hg_* commands are on PATH
```

### Key files

- `~/projects/github/bbugyi200/retired Mercurial plugin/` (new repo)
- `src/sase/vcs_provider/plugins/hg.py` (delete)
- `src/sase/scripts/sase_hg_*` (delete ~20 files)
- `src/sase/scripts/__init__.py` (remove ~20 wrapper functions)
- `xprompts/hg.yml`, `xprompts/cl.yml`, `xprompts/propose.yml`, `xprompts/cldd.md`, `xprompts/crs.md` (delete)
- `pyproject.toml` (remove hg entries from scripts and entry-points)

---

## Phase 4: GitHub Actions Publish Workflows

**Goal**: Add PyPI publishing workflows to all three repos, triggered on tag push.

### Add to all three repos: `.github/workflows/publish.yml`

```yaml
name: Publish to PyPI
on:
  push:
    tags: ["v*"]
permissions:
  contents: read
  id-token: write # for trusted publishing
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv python install 3.12
      - name: Build package
        run: uv run --no-project python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
  publish:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
```

### Repos to update

- The sase core repo (the `sase_<N>` dir the agent is running in): `.github/workflows/publish.yml` (new file)
- `~/projects/github/bbugyi200/sase-github/.github/workflows/publish.yml` (already created in Phase 2 skeleton,
  finalize)
- `~/projects/github/bbugyi200/retired Mercurial plugin/.github/workflows/publish.yml` (already created in Phase 3 skeleton,
  finalize)

### Also add CI workflows to plugin repos

Both sase-github and retired Mercurial plugin need `.github/workflows/ci.yml` with lint + test jobs (simpler than sase core's CI
since they have fewer tests and no beads dependency).

### Verification

- Validate workflow YAML syntax
- Verify tag patterns match expected release flow

---

## Phase 5: Integration Testing & User Setup

**Goal**: Verify the full plugin lifecycle end-to-end. Provide user migration instructions.

### Integration tests in sase core

**Update `tests/test_plugin_discovery.py`** (or create `tests/test_plugin_integration.py`):

- Test xprompt discovery with both plugins installed
- Test config merging with plugin defaults
- Test VCS provider resolution for all three providers (bare_git built-in, github from sase-github, hg from retired Mercurial plugin)
- Test graceful error when plugin not installed
- Test `SASE_DISABLE_PLUGINS` env var

### Verification

```bash
# Full end-to-end (run from the sase_<N> dir the agent is in):
just install
pip install -e ~/projects/github/bbugyi200/sase-github/
pip install -e ~/projects/github/bbugyi200/retired Mercurial plugin/

just check  # All tests pass

# Verify xprompts from all sources appear
# Verify VCS auto-detection still works
# Verify uninstalling a plugin removes its xprompts/VCS support cleanly
```

### User setup instructions

After migration, users need to install the plugin packages for their VCS:

```bash
# Core (always needed):
pip install sase

# For GitHub-hosted repos (most users):
pip install sase-github

# For Mercurial/Fig workspaces (Google-internal):
pip install retired Mercurial plugin

# Bare-git support is built into sase core (no extra install).
# Both plugins can be installed simultaneously.
```

If using `uv` or a requirements file:

```
sase>=0.1.0
sase-github>=0.1.0   # if using GitHub
retired Mercurial plugin>=0.1.0       # if using Mercurial
```

To verify installation:

```bash
python -c "from importlib.metadata import entry_points; print([ep.name for ep in entry_points(group='sase_vcs')])"
# Should show: ['bare_git', 'github', 'hg'] (depending on installed plugins)
```

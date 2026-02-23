---
bead_id: sase-cjj
status: done
---

# Plan: Migrate VCS Provider to Pluggy Plugin Architecture

## Context

The current VCS provider system uses a hand-rolled ABC + dict-based registry pattern in `src/sase/vcs_provider/`. A
single `_GitProvider` class handles both GitHub and bare-git repos via runtime `_is_bare_remote()` checks. The goal is
to migrate to a `pluggy`-based plugin architecture that cleanly separates three providers (GitHub, bare git, hg/fig),
supports eventual user-created plugins, and uses the hg/fig provider as the fully-implemented reference.

## Architecture Overview

```
Caller  -->  get_vcs_provider(cwd)  -->  VCSPluginManager(VCSProvider)
                                              |
                                              v
                                         pluggy.PluginManager
                                              |
                                    +---------+---------+
                                    |         |         |
                                 HgPlugin  GitHubPlugin  BareGitPlugin
```

- **VCSHookSpec**: Class with `@hookspec(firstresult=True)` methods for all ~35 VCS operations (prefixed `vcs_*` to
  namespace them).
- **VCSPluginManager**: Inherits from `VCSProvider` ABC, delegates each method to `self._pm.hook.vcs_*()`. Returns
  `NotImplementedError` when pluggy returns `None`. This preserves the `provider.method()` calling convention used by
  50+ call sites.
- **Plugin classes**: Plain classes with `@hookimpl` decorators. Inherit from a shared `CommandRunner` mixin (extracted
  from the duplicate `_run`/`_run_shell`/`_to_result` helpers).
- **Detection**: `detect_vcs()` returns `"github"` | `"bare_git"` | `"hg"` | `None`. New `detect_vcs_family()` collapses
  `"github"`/`"bare_git"` to `"git"` for backward compat.
- **Entry points**: Built-in plugins registered via `[project.entry-points."sase_vcs"]` in pyproject.toml, so external
  plugins use the same mechanism.

## Phase 1: Plugin Infrastructure

**Goal**: Add pluggy plumbing alongside the existing system. No behavior changes. All existing tests pass.

### Create new files

- `src/sase/vcs_provider/_hookspec.py`
  - `hookspec = pluggy.HookspecMarker("sase_vcs")`
  - `hookimpl = pluggy.HookimplMarker("sase_vcs")`
  - `class VCSHookSpec` with `@hookspec(firstresult=True)` for every VCS operation, mirroring `_base.py` method
    signatures with `vcs_` prefix (e.g., `vcs_checkout`, `vcs_diff`, etc.)

- `src/sase/vcs_provider/_command_runner.py`
  - Extract `CommandRunner` class from the identical `_run()`, `_run_shell()`, `_to_result()` helpers shared by
    `_git.py` and `_hg.py`
  - Also include the `_run_streaming()` method from `_hg.py`

- `src/sase/vcs_provider/_plugin_manager.py`
  - `class VCSPluginManager(VCSProvider)` that wraps a `pluggy.PluginManager`
  - Each `VCSProvider` method delegates to the corresponding `self._pm.hook.vcs_*()` call
  - Returns `NotImplementedError` for hooks where pluggy returns `None`
  - Methods with non-trivial defaults (`resolve_revision` returns input, `prepare_description_for_reword` returns input)
    provide those defaults when hook returns `None`

- `tests/test_vcs_provider_hookspec.py` - Verify hookspec methods exist with correct signatures
- `tests/test_vcs_provider_plugin_manager.py` - Verify delegation to mock plugins, `NotImplementedError` behavior

### Modify existing files

- `pyproject.toml` - Add `pluggy` to `dependencies`

### Verification

- `just check` passes (all existing tests + new infra tests)

---

## Phase 2: Hg/Fig Plugin (Full Reference Implementation)

**Goal**: Convert `_HgProvider` into a pluggy plugin. Wire it into the new system so hg repos use the plugin path. Old
`_hg.py` becomes a thin backward-compat shim.

### Create new files

- `src/sase/vcs_provider/plugins/__init__.py`
- `src/sase/vcs_provider/plugins/hg.py`
  - `class HgPlugin(CommandRunner)` with `@hookimpl` on ALL methods
  - Exact same logic as `_HgProvider`, just with `@hookimpl` decorators and `vcs_` method names
  - This is the canonical "fully implemented" plugin example

### Modify existing files

- `src/sase/vcs_provider/_registry.py`
  - When `_resolve_vcs_name()` returns `"hg"`, create a `pluggy.PluginManager`, register `HgPlugin`, wrap in
    `VCSPluginManager`, return it
  - Keep the old dict-based path as fallback for git (not migrated yet)
- `src/sase/vcs_provider/_hg.py`
  - Convert to thin shim: `class _HgProvider(HgPlugin, VCSProvider)` that adapts method names, OR keep as-is for now and
    only route through plugin path via registry change

### Update tests

- Update `tests/test_vcs_provider_contract.py` hg parametrization to route through plugin
- Add `tests/test_vcs_provider_hg_plugin.py` for plugin-specific tests
- Existing hg tests in `tests/test_vcs_provider.py` should still pass

### Verification

- `just check` passes
- Hg provider works identically through the pluggy path

---

## Phase 3: Split Git into GitHub + Bare Git Plugins

**Goal**: Split `_GitProvider` into two plugins. Update detection to distinguish GitHub from bare git. Migrate callers
of `detect_vcs()` that compare against `"git"`.

### Create new files

- `src/sase/vcs_provider/plugins/github.py`
  - `class GitHubPlugin(CommandRunner)` with `@hookimpl` on implemented methods
  - Contains: all core git methods + GitHub-specific methods (`mail` with `gh pr create`, `get_cl_number` via
    `gh pr view`, `get_change_url` via `gh pr view`)
  - Can leave some methods unimplemented (no `@hookimpl`) for now

- `src/sase/vcs_provider/plugins/bare_git.py`
  - `class BareGitPlugin(CommandRunner)` with `@hookimpl` on implemented methods
  - Contains: core git methods + bare-git variants (`mail` does `git push` only, `get_cl_number`/`get_change_url` return
    `(True, None)`)
  - Permanently leaves many methods unimplemented

- `src/sase/vcs_provider/plugins/_git_common.py` (optional)
  - Shared git helper methods if significant duplication exists between the two plugins
  - e.g., `_get_default_branch()` logic used by both `sync_workspace` and `get_default_parent_revision`

### Modify existing files

- `src/sase/vcs_provider/_registry.py`
  - `detect_vcs(cwd)` now returns `"github"` | `"bare_git"` | `"hg"` | `None`
  - Add `_classify_git_repo(git_root)` helper: checks origin URL to determine `"github"` vs `"bare_git"`
  - Add `detect_vcs_family(cwd)` that collapses `"github"`/`"bare_git"` to `"git"`
  - `get_vcs_provider()` now routes all three providers through pluggy
  - Remove old `_ensure_providers_loaded()` and `_PROVIDERS` dict

- `src/sase/vcs_provider/__init__.py`
  - Export `detect_vcs_family`
  - Remove `register_provider` from `__all__`

- Migrate callers of `detect_vcs()` that check `== "git"` to use `detect_vcs_family()`:
  - `src/sase/commit_workflow/workflow.py`
  - `src/sase/ace/mail_ops.py`
  - `src/sase/status_state_machine/transitions.py`
  - Any other callers found via `grep detect_vcs`

### Update tests

- `tests/test_vcs_provider_contract.py` - Parametrize over 3 providers
- Add `tests/test_vcs_provider_github_plugin.py`
- Add `tests/test_vcs_provider_bare_git_plugin.py`
- Add/update detection tests for the 3-value system

### Verification

- `just check` passes
- GitHub repos detected as `"github"`, bare-git repos as `"bare_git"`, hg repos as `"hg"`
- All 50+ call sites work correctly

---

## Phase 4: Cleanup + Entry Points

**Goal**: Remove legacy code, wire up entry points, finalize public API.

### Modify existing files

- `pyproject.toml` - Add `[project.entry-points."sase_vcs"]` section:
  ```toml
  [project.entry-points."sase_vcs"]
  github = "sase.vcs_provider.plugins.github:GitHubPlugin"
  bare_git = "sase.vcs_provider.plugins.bare_git:BareGitPlugin"
  hg = "sase.vcs_provider.plugins.hg:HgPlugin"
  ```
- `src/sase/vcs_provider/_registry.py`
  - Add `pm.load_setuptools_entrypoints("sase_vcs")` for external plugin discovery
  - Remove any remaining legacy registration code
- `src/sase/vcs_provider/__init__.py` - Clean up exports

### Delete files

- `src/sase/vcs_provider/_git.py` (replaced by `plugins/github.py` + `plugins/bare_git.py`)
- `src/sase/vcs_provider/_hg.py` (replaced by `plugins/hg.py`)

### Keep files

- `src/sase/vcs_provider/_base.py` - Keep `VCSProvider` ABC for type annotations across 50+ call sites

### Update tests

- Remove tests that test old `register_provider` mechanism
- Update any remaining tests with old import paths
- Add entry-point discovery tests

### Verification

- `just check` passes
- `just test-tox` passes across Python 3.12, 3.13, 3.14
- No references to old `_git.py` or `_hg.py` remain (except in git history)

## Key Files Reference

| File                                  | Role                                                |
| ------------------------------------- | --------------------------------------------------- |
| `src/sase/vcs_provider/_base.py`      | ABC that 50+ callers type-annotate against          |
| `src/sase/vcs_provider/_registry.py`  | Factory + detection; most complex migration target  |
| `src/sase/vcs_provider/_git.py`       | Must be split into GitHub + bare git plugins        |
| `src/sase/vcs_provider/_hg.py`        | Reference implementation for full plugin conversion |
| `src/sase/vcs_provider/__init__.py`   | Public API surface                                  |
| `tests/test_vcs_provider_contract.py` | Cross-provider contract tests                       |
| `tests/test_vcs_provider.py`          | Core unit tests (553 lines)                         |

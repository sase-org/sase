---
bead_id: sase-rz8
status: done
---

# VCS Abstraction Migration Plan

## Context

The sase core codebase has a well-designed VCS **operations** plugin system (checkout, diff, commit, etc.) via pluggy.
However, a second layer of VCS-specific logic -- **workspace management** -- is hardcoded into core modules. This
includes project type detection, ref resolution, workspace setup, submission logic, and display labels. The goal is to
abstract all of this into plugins so that new VCS integrations (GitLab, Facebook internal VCS, etc.) can be added
without modifying sase's core.

**Scale of work**: 29 VCS-specific import occurrences across 23 core files, plus 4 xprompt workflows in plugin repos
referencing core scripts. ~1,300 lines of VCS-specific code in core to migrate or abstract.

---

## Phase 1: Create Workspace Provider Plugin Interface + Extract Generic Utilities

**Goal**: Define the new `sase_workspace` pluggy hook specification, create the plugin manager/registry, and extract
generic (non-VCS-specific) utilities into a new `workspace_utils.py` module. No consumer code changes yet -- old import
paths continue to work via re-exports.

### New files to create

1. **`src/sase/workspace_provider/__init__.py`** -- Public API: `detect_workflow_type`, `get_change_label`,
   `resolve_ref`, `submit_changespec`
2. **`src/sase/workspace_provider/_hookspec.py`** -- Pluggy hookspecs (follow pattern of `vcs_provider/_hookspec.py`):
   - `ws_detect_workflow_type(project_file) -> str | None`
   - `ws_get_change_label(project_file) -> str | None`
   - `ws_resolve_ref(ref, workflow_type) -> ResolvedRef | None`
   - `ws_submit(changespec_file, changespec_name, project_basename, console) -> tuple[bool, str | None] | None`
   - `ws_setup_workflow(ref, workflow_type, n, release) -> dict[str, str] | None`
   - Also define `ResolvedRef` dataclass (project_file, project_name, primary_workspace_dir, checkout_target, extra
     dict)
3. **`src/sase/workspace_provider/_plugin_manager.py`** -- Wraps pluggy PM, delegates to hooks
4. **`src/sase/workspace_provider/_registry.py`** -- Loads ALL `sase_workspace` entry points (unlike `sase_vcs` which
   loads one); provides `detect_workflow_type()`, `get_change_label()`, `resolve_ref()`, `submit_changespec()` with
   fallback to legacy code during transition
5. **`src/sase/workspace_provider/plugins/__init__.py`** -- Empty
6. **`src/sase/workspace_provider/plugins/bare_git_workspace.py`** -- Bare-git workspace plugin implementing ws hooks
   for workflow type "git", using logic from `git_workspace.py` and the bare-git parts of `git_submit.py`
7. **`src/sase/workspace_utils.py`** -- Generic utilities extracted from `gh_workspace.py`:
   - `parse_workspace_dir()`, `set_workspace_dir()` (project file utilities, not VCS-specific)
   - `get_default_branch()`, `ensure_git_clone()`, `_get_git_clone_dir()` (generic git utilities)
   - `detect_vcs_type_for_project()`, `get_cl_field_label()` (legacy compat, will eventually delegate to plugins)
8. **`tests/test_workspace_provider_hookspec.py`** -- Tests for new hookspec
9. **`tests/test_workspace_utils.py`** -- Tests for extracted utilities

### Files to modify

- **`src/sase/gh_workspace.py`** -- Keep all functions but make them re-exports from `workspace_utils.py` for backward
  compat. GitHub-specific functions (`_clone_gh_repo`, `resolve_gh_ref`) stay here temporarily.
- **`pyproject.toml`** -- Add `[project.entry-points."sase_workspace"]` with
  `bare_git = "sase.workspace_provider.plugins.bare_git_workspace:BareGitWorkspacePlugin"`

### Verification

```bash
just check  # All lint + test must pass
python -c "from sase.workspace_provider import detect_workflow_type"
python -c "from sase.workspace_utils import parse_workspace_dir, ensure_git_clone"
# All existing imports from sase.gh_workspace still work
```

---

## Phase 2: Migrate GitHub-Specific Code to sase-github + Update Core Consumers

**Goal**: Move all GitHub-specific workspace code from core to sase-github, and update all ~20 core files to use the new
plugin-agnostic interfaces.

### Files to create (in ../sase-github/)

1. **`../sase-github/src/sase_github/workspace_plugin.py`** -- `GitHubWorkspacePlugin` implementing ws hooks:
   - `ws_detect_workflow_type` returns `"gh"` for remote-hosted git repos
   - `ws_get_change_label` returns `"PR"` for `"gh"` projects
   - `ws_resolve_ref` handles GitHub ref resolution (logic from `resolve_gh_ref`, `_clone_gh_repo`)
   - `ws_submit` handles PR submission (logic from `_check_existing_pr`, `_submit_via_pr_merge`)
2. **`../sase-github/src/sase_github/config.py`** -- `get_github_username()` (moved from `sase/github_config.py`)
3. **`../sase-github/src/sase_github/scripts/__init__.py`**
4. **`../sase-github/src/sase_github/scripts/gh_setup.py`** -- Moved from `sase/scripts/gh_setup.py`
5. **`../sase-github/src/sase_github/scripts/pr_create_changespec.py`** -- Moved from core
6. **`../sase-github/src/sase_github/scripts/new_pr_desc_get_context.py`** -- Moved from core

### Files to modify (in ../sase-github/)

- **`../sase-github/pyproject.toml`** -- Add `sase_workspace` entry point:
  `github = "sase_github.workspace_plugin:GitHubWorkspacePlugin"`
- **`../sase-github/src/sase_github/xprompts/gh.yml`** -- Change `from sase.scripts.gh_setup import main` to
  `from sase_github.scripts.gh_setup import main`
- **`../sase-github/src/sase_github/xprompts/pr.yml`** -- Change `from sase.scripts.pr_create_changespec import main` to
  `from sase_github.scripts.pr_create_changespec import main`
- **`../sase-github/src/sase_github/xprompts/new_pr_desc.yml`** -- Change
  `from sase.scripts.new_pr_desc_get_context import main` to
  `from sase_github.scripts.new_pr_desc_get_context import main`

### Files to modify (in sase core) -- update consumers

**Group A** -- `get_cl_field_label` -> `workspace_provider.get_change_label`:

- `src/sase/ace/display.py` (line 11)
- `src/sase/ace/tui/actions/clipboard.py` (line 15)
- `src/sase/ace/tui/widgets/changespec_detail.py` (line 9)
- `src/sase/status_state_machine/field_updates.py` (line 11)
- `src/sase/workspace_changespec.py` (line 8)

**Group B** -- `detect_workflow_type_for_project` -> `workspace_provider.detect_workflow_type`:

- `src/sase/ace/tui/actions/base.py` (line 85)
- `src/sase/ace/tui/actions/agent_workflow/_entry_points.py` (line 25)
- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` (line 172)
- `src/sase/axe_crs_runner.py` (line 71)
- `src/sase/axe_fix_hook_runner.py` (line 112)
- `src/sase/mentor_workflow.py` (line 153)

**Group C** -- `detect_vcs_type_for_project` / `ensure_git_clone` / `parse_workspace_dir` -> `workspace_utils`:

- `src/sase/ace/tui/widgets/file_panel/_diff.py` (line 7)
- `src/sase/ace/scheduler/workflows_runner/starter.py` (lines 135-138)
- `src/sase/running_field.py` (line 553)

**Group D** -- submission dispatch:

- `src/sase/ace/tui/actions/base.py` (line 89) -- Replace `from sase.git_submit import submit_git_changespec` with
  `from sase.workspace_provider import submit_changespec`; remove hardcoded `vcs_type in ("git", "gh")` check

**Group E** -- other cleanup:

- `src/sase/git_workspace.py` (line 18) -- Change imports from `sase.gh_workspace` to `sase.workspace_utils`
- `src/sase/git_submit.py` (lines 15-19) -- Change imports; reduce to bare-git-only + `_finalize_submission()`

### Files to delete (from core)

- `src/sase/scripts/gh_setup.py` (moved to sase-github)
- `src/sase/scripts/pr_create_changespec.py` (moved to sase-github)
- `src/sase/scripts/new_pr_desc_get_context.py` (moved to sase-github)

### Key implementation details

- `_finalize_submission()` from `git_submit.py` (rename ChangeSpec + transition to Submitted) must stay in core (e.g.,
  `workspace_utils.py` or `submission_utils.py`) because both GitHub and bare-git submission call it.
- `src/sase/github_config.py` becomes a backward-compat wrapper:
  `try: from sase_github.config import get_github_username; except ImportError: <inline fallback>`
- The `gh_workspace.py` module keeps re-exports from `workspace_utils` for any remaining consumers. The GitHub-specific
  functions (`_clone_gh_repo`, `resolve_gh_ref`, `_ResolvedGhRef`) are removed.
- Update `tests/test_gh_workspace.py` -- tests for generic utilities stay (with updated imports); tests for
  GitHub-specific functions (resolve_gh_ref) should move to sase-github.
- Update `tests/test_git_submit.py` -- update import paths, add test for new `submit_changespec` dispatch.

### Verification

```bash
just check
cd ../sase-github && just check
# Verify no core code imports from sase.scripts.gh_setup, sase.scripts.pr_create_changespec,
#   or sase.scripts.new_pr_desc_get_context
# Verify all consumer files import from sase.workspace_provider or sase.workspace_utils
```

---

## Phase 3: Migrate hg-Specific Code to retired Mercurial plugin + Refactor Ref Resolution

**Goal**: Move hg-specific setup script to retired Mercurial plugin, create HgWorkspacePlugin, and refactor the TUI ref resolution
system to be less hardcoded.

### Files to create (in ../retired Mercurial plugin/)

1. **`../retired Mercurial plugin/src/sase_hg/workspace_plugin.py`** -- `HgWorkspacePlugin` implementing ws hooks:
   - `ws_detect_workflow_type` returns `"hg"` for hg projects
   - `ws_get_change_label` returns `"CL"` for hg projects
   - `ws_resolve_ref` handles hg ref resolution (logic from `_resolve_hg_from_prompt` in `_ref_resolution.py`)
   - `ws_setup_workflow` handles hg setup (logic from `hg_setup.py`)
2. **`../retired Mercurial plugin/src/sase_hg/scripts/__init__.py`**
3. **`../retired Mercurial plugin/src/sase_hg/scripts/hg_setup.py`** -- Moved from `sase/scripts/hg_setup.py`

### Files to modify (in ../retired Mercurial plugin/)

- **`../retired Mercurial plugin/pyproject.toml`** -- Add `sase_workspace` entry point:
  `hg = "sase_hg.workspace_plugin:HgWorkspacePlugin"`
- **`../retired Mercurial plugin/src/sase_hg/xprompts/hg.yml`** -- Change `from sase.scripts.hg_setup import main` to
  `from sase_hg.scripts.hg_setup import main`

### Files to modify (in sase core)

- **`src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py`** -- Refactor: collapse the three
  `_resolve_{gh,git,hg}_from_prompt` methods into a single `_resolve_vcs_from_prompt()` that iterates over patterns and
  delegates resolution to `workspace_provider.resolve_ref()`. Keep the regex patterns in core for now (they match the
  xprompt trigger syntax `#gh:`, `#git:`, `#hg:` and are relatively stable), but resolution logic goes through plugins.
- **`src/sase/workspace_provider/_registry.py`** -- Ensure `detect_workflow_type()` falls back to `"hg"` when no plugin
  claims the project (matches current behavior where hg is the default).

### Files to delete (from core)

- `src/sase/scripts/hg_setup.py` (moved to retired Mercurial plugin)

### Verification

```bash
just check
cd ../retired Mercurial plugin && just check
# Verify no core code imports from sase.scripts.hg_setup
```

---

## Phase 4: Make VCS Classification Pluggable + Final Cleanup

**Goal**: Make `_classify_git_repo()` pluggable (so a GitLab plugin can claim repos with `git@gitlab.com` URLs), remove
deprecated wrapper modules, and run final verification.

### Files to modify

- **`src/sase/vcs_provider/_registry.py`** -- Refactor `_classify_git_repo()`:
  - Add a new hookspec `vcs_classify_repo(git_dir: str) -> str | None` to `VCSHookSpec`
  - `_classify_git_repo()` first tries registered plugins' `vcs_classify_repo` hooks (e.g., sase-github could claim
    repos with github.com URLs, sase-gitlab could claim repos with gitlab.com URLs)
  - Falls back to current logic: remote-hosted = "github", local path = "bare_git"
- **`src/sase/vcs_provider/_hookspec.py`** -- Add `vcs_classify_repo` hookspec
- **`src/sase/gh_workspace.py`** -- Reduce to minimal deprecated re-export wrapper, or delete entirely and fix any
  remaining imports
- **`src/sase/git_submit.py`** -- Reduce to minimal deprecated re-export wrapper, or delete entirely
- **`src/sase/github_config.py`** -- Reduce to minimal deprecated re-export wrapper, or delete entirely
- **Tests** -- Update mock paths in any tests still referencing old module paths. Move GitHub-specific tests to
  sase-github.

### Verification

```bash
just check
cd ../sase-github && just check
cd ../retired Mercurial plugin && just check
.venv/bin/sase ace --agent  # TUI loads correctly

# Verify the new plugin system works:
python -c "from sase.workspace_provider import detect_workflow_type, get_change_label, submit_changespec; print('ok')"
python -c "from sase.workspace_utils import parse_workspace_dir, ensure_git_clone; print('ok')"

# Verify no remaining direct imports of moved/deprecated modules (except re-export wrappers):
grep -r 'from sase.gh_workspace import' src/sase/ --include='*.py' | grep -v 'gh_workspace.py'  # should be empty
grep -r 'from sase.git_submit import' src/sase/ --include='*.py' | grep -v 'git_submit.py'  # should be empty
grep -r 'from sase.github_config import' src/sase/ --include='*.py' | grep -v 'github_config.py'  # should be empty
```

---

## Final Architecture After Migration

```
sase (core)
  workspace_provider/                    # NEW -- workspace plugin system
    _hookspec.py                         # WorkspaceHookSpec + ResolvedRef
    _plugin_manager.py                   # WorkspacePluginManager
    _registry.py                         # detect_workflow_type(), resolve_ref(), submit_changespec()
    plugins/
      bare_git_workspace.py              # BareGitWorkspacePlugin (workflow type "git")
  workspace_utils.py                     # NEW -- generic utilities (parse_workspace_dir, ensure_git_clone, etc.)
  vcs_provider/                          # UNCHANGED -- low-level operations layer
    _hookspec.py                         # + new vcs_classify_repo hook (Phase 4)
    _registry.py                         # _classify_git_repo() now calls vcs_classify_repo hook first
    plugins/
      bare_git.py                        # BareGitPlugin (stays in core)
      _git_common.py                     # GitCommon mixin (stays in core, shared by all git plugins)
  git_workspace.py                       # parse_bare_repo_dir, init_bare_git_project (bare-git core funcs)
  scripts/
    git_setup.py                         # Bare-git xprompt setup (stays in core)
  gh_workspace.py                        # DEPRECATED re-export wrapper (or deleted)
  git_submit.py                          # DEPRECATED re-export wrapper (or deleted)
  github_config.py                       # DEPRECATED re-export wrapper (or deleted)

sase-github (plugin)
  plugin.py                              # GitHubPlugin for VCS operations (UNCHANGED)
  workspace_plugin.py                    # NEW -- GitHubWorkspacePlugin
  config.py                              # NEW -- get_github_username()
  scripts/
    gh_setup.py                          # MOVED from core
    pr_create_changespec.py              # MOVED from core
    new_pr_desc_get_context.py           # MOVED from core

retired Mercurial plugin (plugin)
  plugin.py                              # HgPlugin for VCS operations (UNCHANGED)
  workspace_plugin.py                    # NEW -- HgWorkspacePlugin
  scripts/
    hg_setup.py                          # MOVED from core
```

## Key Design Decisions

1. **Separate `sase_workspace` pluggy project** (not extending `sase_vcs`): The VCS operations layer loads ONE plugin
   per instantiation; workspace detection needs to iterate ALL plugins. Different dispatch semantics warrant separation.
2. **`_git_common.py` stays in core**: It's pure git plumbing shared by all git-based VCS plugins. A GitLab plugin would
   inherit from it just like GitHub does.
3. **`bare_git` stays in core**: It's the default/fallback for local git repos. No external plugin needed.
4. **`hg` is the default fallback**: When no workspace plugin claims a project, it's assumed to be hg (matches current
   behavior).
5. **Ref patterns stay in core for now**: The `#gh:`, `#git:`, `#hg:` regex patterns are stable and match xprompt
   trigger syntax. Full plugin-contributed pattern registration is a future enhancement.
6. **Deprecated wrappers provide backward compat**: Old import paths (`sase.gh_workspace`, `sase.git_submit`) continue
   to work via re-exports, giving external code time to migrate.

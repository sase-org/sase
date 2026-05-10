---
bead_id: sase-svxv
status: done
---

# Plan: Make sase Core Fully VCS-Agnostic

## Context

The sase core codebase still contains hardcoded VCS-specific logic (GitHub URL patterns, Mercurial commands,
`"gh"`/`"git"`/`"hg"` string literals) despite having a well-designed plugin system. This means adding a new VCS
integration (e.g., sase-gitlab, Facebook internal VCS) currently requires changes to sase core. The goal is to make the
core fully VCS-agnostic so new integrations only require creating a new plugin repo.

## Key Decisions

- **Bare-git code stays in core** - `git.yml`, `git_workspace.py`, `git_setup.py`, `git_submit.py`, `BareGitPlugin`,
  `BareGitWorkspacePlugin` remain in sase core as the built-in default.
- **Error if unclassified** - When no plugin claims a git repo, raise an error instead of defaulting to `"github"`.
  Users must install the right plugin or configure explicitly.
- **Commit/amend workflows stay in core** - They already delegate to VCS hooks; the workflows themselves are
  VCS-agnostic orchestrators.

## Phase 1: Dynamic VCS Workflow Name Discovery

**Goal**: Replace all hardcoded `{"gh", "git", "hg"}` sets, regex patterns, display names, and per-VCS env var prefixes
with plugin-declared metadata.

### New abstractions

- `WorkflowMetadata` dataclass in `workspace_provider/_hookspec.py`:
  - `workflow_type: str` (e.g. "gh"), `ref_pattern: str` (regex), `display_name: str` (e.g. "GitHub"),
    `pre_allocated_env_prefix: str` (e.g. "SASE_GH")
- `ws_get_workflow_metadata()` hookspec (NOT firstresult - collects from all plugins)
- Metadata registry module in `workspace_provider/` with helpers: `get_workflow_names()`, `get_ref_patterns()`,
  `get_display_name()`, `get_vcs_tag_pattern()`

### Files to modify

**sase core:**

- `src/sase/workspace_provider/_hookspec.py` - Add `WorkflowMetadata` + `ws_get_workflow_metadata` hook
- `src/sase/workspace_provider/_plugin_manager.py` - Add `get_workflow_metadata()` delegation
- `src/sase/workspace_provider/_registry.py` - Add public `get_all_workflow_metadata()` (or new `_metadata_registry.py`)
- `src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py` - Replace hardcoded `_GH_REF_PATTERN`,
  `_GIT_REF_PATTERN`, `_HG_REF_PATTERN`, `_VCS_PATTERNS` (lines 7-15) and the three `_resolve_*_from_prompt()` methods
  (lines 21-49) with a single generic `_resolve_vcs_from_prompt(prompt, workflow_type)`. Replace
  `if workflow_type == "hg"` branch (line 83) with `ws_get_workspace_directory` hook call (from Phase 4, or inline
  delegation)
- `src/sase/main/query_handler/special_cases.py` - Replace `_VCS_WORKFLOW_NAMES = {"gh", "git", "hg"}` (line 14) with
  `get_workflow_names()`
- `src/sase/xprompt/_parsing.py` - Replace `_VCS_TAG_PATTERN = re.compile(r"^#(?:gh|git|hg)...")` (line 338) with
  dynamic pattern from `get_vcs_tag_pattern()`
- `src/sase/axe_run_agent_runner.py` - Replace `vcs_display_map = {"git": "GitHub", "hg": "Mercurial"}` (line 204) with
  `get_display_name()`
- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` - Replace separate `gh_ref`, `git_ref`, `hg_ref` params
  (lines 280-299) with single `vcs_ref: tuple[str, str] | None` (workflow_type, ref). Replace hardcoded
  `SASE_GH_PRE_ALLOCATED` / `SASE_GIT_PRE_ALLOCATED` / `SASE_HG_PRE_ALLOCATED` env var blocks (lines 340-351) with
  generic loop using `pre_allocated_env_prefix`

**Plugin repos:**

- `sase-github/src/sase_github/workspace_plugin.py` - Implement `ws_get_workflow_metadata` returning
  `WorkflowMetadata("gh", <regex>, "GitHub", "SASE_GH")`
- `retired Mercurial plugin/src/sase_hg/workspace_plugin.py` - Implement `ws_get_workflow_metadata` returning
  `WorkflowMetadata("hg", <regex>, "Mercurial", "SASE_HG")`
- `sase core bare_git_workspace.py` - Implement `ws_get_workflow_metadata` returning
  `WorkflowMetadata("git", <regex>, "Git (bare)", "SASE_GIT")`

---

## Phase 2: Dynamic VCS-Specific Check Scripts

**Goal**: Remove hardcoded CL/PR URL pattern matching and VCS-specific bash script generation from `checks_runner.py`.

### New hooks in `WorkspaceHookSpec`

- `ws_extract_change_identifier(cl_url: str) -> tuple[str, str] | None` - Parse CL/PR URLs
- `ws_generate_submitted_check_script(identifier: str) -> str | None` - Generate check script
- `ws_supports_reviewer_comments(cl_url: str) -> bool | None` - Query support
- `ws_generate_reviewer_comments_script(changespec_name: str) -> str | None` - Generate reviewer comments script

### Files to modify

**sase core:**

- `src/sase/workspace_provider/_hookspec.py` - Add 4 new hookspecs
- `src/sase/workspace_provider/_plugin_manager.py` - Add delegation methods
- `src/sase/workspace_provider/_registry.py` - Add public convenience functions
- `src/sase/ace/scheduler/checks_runner.py` - Replace `_extract_change_identifier()` hardcoded `http://cl/` and
  `github.com/.../pull/` patterns (lines 104-114) with hook call. Replace hardcoded `gh pr view` / `is_cl_submitted`
  scripts (lines 143-163) with hook call. Replace hardcoded git-skip for reviewer comments (lines 208-213) with hook
  call.

**Plugin repos:**

- `sase-github/src/sase_github/workspace_plugin.py` - Implement: extract `github.com/.../pull/<N>`, generate
  `gh pr view` script, return `False` for reviewer comments
- `retired Mercurial plugin/src/sase_hg/workspace_plugin.py` - Implement: extract `http://cl/<N>`, generate `is_cl_submitted` script,
  return `True` for reviewer comments, generate `critique_comments` script

---

## Phase 3: Remove Hardcoded Fallback Defaults

**Goal**: Eliminate `"github"` and `"hg"` hardcoded defaults from VCS/workspace registries.

### New hook

- `vcs_detect_repo_type(directory: str) -> str | None` in `VCSHookSpec` - Detect VCS from directory (not git-only)

### Files to modify

**sase core:**

- `src/sase/vcs_provider/_hookspec.py` - Add `vcs_detect_repo_type` hookspec
- `src/sase/vcs_provider/_registry.py`:
  - `detect_vcs()`: Replace hardcoded `.hg/` check (line 96) with `vcs_detect_repo_type` plugin call first
  - `_classify_by_url()`: Remove `"github"` fallback (lines 73, 76, 81). If no plugin classifies the repo and it's not
    bare_git, raise `VCSProviderNotFoundError` with a message suggesting the user install the appropriate plugin.
- `src/sase/workspace_provider/_registry.py`:
  - `detect_workflow_type()`: Replace `return "hg"` fallback (line 46) with error
  - `resolve_ref()`: Remove hardcoded `if workflow_type == "git"` fallback (lines 77-87) - `BareGitWorkspacePlugin`
    handles this
  - `submit_changespec()`: Remove hardcoded `from sase.git_submit import submit_git_changespec` fallback (lines 108-114)

**Plugin repos:**

- `retired Mercurial plugin/src/sase_hg/plugin.py` - Implement `vcs_detect_repo_type`: check for `.hg/` dir, return `"hg"`

---

## Phase 4: VCS-Agnostic Workspace Directory Resolution and Commit Formatting

**Goal**: Remove VCS-specific workspace directory logic and commit formatting branching.

### New hooks

- `ws_get_workspace_directory(workflow_type, workspace_num, project_name, primary_workspace_dir) -> str | None`
- `ws_format_commit_description(file_path, project, bug, fixed_bug) -> bool | None`

### Files to modify

**sase core:**

- `src/sase/workspace_provider/_hookspec.py` - Add 2 new hookspecs
- `src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py` - Replace `if workflow_type == "hg"` workspace dir
  branching (lines 83-92) with `ws_get_workspace_directory` hook
- `src/sase/commit_workflow/cl_formatting.py` - Replace `format_cl_description()` VCS branching (lines 28-41) with
  `ws_format_commit_description` hook. Remove `vcs_type` parameter.
- `src/sase/workspace_utils.py` - Deprecate `detect_vcs_type_for_project()` and `get_cl_field_label()`

**Plugin repos:**

- `sase-github` - Implement both hooks (git clone for workspace, simple prefix for formatting)
- `retired Mercurial plugin` - Implement both hooks (workspace_directory_for_num, full hg metadata tags)
- `bare_git_workspace.py` in core - Implement both hooks

---

## Phase 5: Cleanup - Docstrings, Legacy Removal, git.yml Migration

**Goal**: Clean up VCS-specific terminology and remove deprecated legacy code.

### Files to modify

- `src/sase/commit_workflow/workflow.py` - Fix "Mercurial" docstrings (line 1, 26)
- `src/sase/commit_workflow/__init__.py` - Fix "Mercurial" docstrings (lines 1, 20, 38)
- `src/sase/amend_workflow.py` - Fix "Mercurial" docstrings (lines 1, 27, 219)
- `src/sase/ace/restore.py` - Fix hg-specific comments (line 119)
- `src/sase/workspace_utils.py` - Remove deprecated functions or convert to thin wrappers
- Various files - Remove stale hg-specific comments

## Verification

After all phases, `grep -rn '"gh"\|"git"\|"hg"\|github\.com\|http://cl/' src/sase/` should show zero behavioral
VCS-specific code (only generic plugin references). A hypothetical `sase-gitlab` plugin implementing all hooks should
work with zero core changes. `just check` must pass.

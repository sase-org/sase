---
bead_id: sase-bhlk
status: done
---

# Plan: Extract All VCS-Specific Code from sase Core

## Context

The sase core has a well-designed plugin system (pluggy-based `sase_vcs` and `sase_workspace` hook groups), but several
modules still contain hard-coded git/hg logic that should be delegated to plugins. This prevents implementing new VCS
integrations (GitLab, Facebook's internal VCS, etc.) without modifying core.

**VCS-specific modules to eliminate from core:**

- `src/sase/git_utils.py` — direct git subprocess calls for diff generation
- `src/sase/git_submit.py` — bare-git submission workflow with direct git subprocess calls
- `src/sase/git_workspace.py` — bare-git workspace/project init with direct git subprocess calls
- `src/sase/ace/mail_ops.py` — branches on VCS type with separate `_prepare_mail_git`/`_prepare_mail_hg` functions
- `src/sase/ace/tui/widgets/file_panel/_diff.py` — branches on VCS type for diff fetching
- `src/sase/running_field.py:get_workspace_directory()` — checks `.git`, falls back to `sase_hg_get_workspace`
- `src/sase/workspace_provider/_registry.py:get_display_name_by_vcs_family()` — hard-coded `{"gh", "git"}` family set

**Acceptable VCS-aware code staying in core:**

- `ace/changespec/locking.py` — uses git for `~/.sase` data management (not project VCS)
- `vcs_provider/_registry.py:detect_vcs()` — `.git` marker detection is the base-case (non-git detected via plugins
  first)
- `vcs_provider/_registry.py:_classify_by_url()` — `git config` read for git repo classification fallback
- `workspace_utils.py:ensure_git_clone()/get_default_branch()` — shared git utilities used by multiple git-based plugins
  (bare_git + sase-github)

---

## Phase 1: Add VCS Diff Hooks + Implement in GitCommon

**Goal:** Add `vcs_diff_with_untracked` and `vcs_committed_diff` hooks so callers can get diffs without importing
git-specific modules. No callers changed yet — purely additive.

### Changes

| File                                           | Change                                                                                            |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `src/sase/vcs_provider/_hookspec.py`           | Add `vcs_diff_with_untracked(cwd, timeout)` and `vcs_committed_diff(cwd, timeout)` hookspecs      |
| `src/sase/vcs_provider/_base.py`               | Add `diff_with_untracked(cwd, timeout=10)` and `committed_diff(cwd, timeout=10)` abstract methods |
| `src/sase/vcs_provider/_plugin_manager.py`     | Add delegation methods for both new hooks                                                         |
| `src/sase/vcs_provider/plugins/_git_common.py` | Add `@hookimpl` methods with logic from `git_utils.py`                                            |

### Verification

- `just check` passes
- Existing `git_utils.py` still works (nothing removed yet)

---

## Phase 2: Migrate Diff Callers to VCS Hooks, Delete `git_utils.py`

**Goal:** Replace all `from sase.git_utils import ...` with VCS provider hook calls. Delete `git_utils.py`.

### Changes

| File                                                 | Change                                                                                                                                                                     |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/widgets/file_panel/_diff.py`       | Replace VCS-type branching (`if vcs_type == "git"` / `elif vcs_type == "hg"`) with `provider.diff_with_untracked()` / `provider.committed_diff()` via `get_vcs_provider()` |
| `src/sase/xprompt/workflow_executor_steps_prompt.py` | Replace `capture_git_diff()` → `capture_vcs_diff()` using `get_vcs_provider(os.getcwd())`                                                                                  |
| `src/sase/git_utils.py`                              | **DELETE**                                                                                                                                                                 |
| `tests/test_git_utils.py`                            | **DELETE** or migrate tests to hook-level tests                                                                                                                            |
| `../retired Mercurial plugin/src/sase_hg/plugin.py`               | Add `vcs_diff_with_untracked` and `vcs_committed_diff` hookimpls (hg equivalents)                                                                                          |

### Verification

- `just check` passes in sase and retired Mercurial plugin
- `grep -r "git_utils" src/` returns nothing
- File panel diffs work for git projects

---

## Phase 3: Add `ws_prepare_mail` Hook, Migrate `mail_ops.py`

**Goal:** Extract VCS-specific mail preparation into workspace plugins via a new `ws_prepare_mail` hook. Eliminate the
`detect_vcs_family` branching in `prepare_mail()`.

### New hook: `ws_prepare_mail`

Parameters: `changespec_name`, `changespec_parent`, `project_basename`, `project_file`, `target_dir`, `console` Returns:
`MailPrepResult`-compatible object or `None`

### Changes

| File                                                        | Change                                                                                                                                  |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/workspace_provider/_hookspec.py`                  | Add `ws_prepare_mail` hookspec                                                                                                          |
| `src/sase/workspace_provider/_plugin_manager.py`            | Add `prepare_mail` delegation                                                                                                           |
| `src/sase/workspace_provider/_registry.py`                  | Add `prepare_mail()` public function                                                                                                    |
| `src/sase/ace/mail_ops.py`                                  | `prepare_mail()` delegates to `ws_prepare_mail` hook; remove `_prepare_mail_git`, `_prepare_mail_hg`, `_modify_description_for_mailing` |
| `src/sase/workspace_provider/plugins/bare_git_workspace.py` | Add `ws_prepare_mail` hookimpl (logic from `_prepare_mail_git`)                                                                         |
| `../sase-github/src/sase_github/workspace_plugin.py`        | Add `ws_prepare_mail` hookimpl (same git mail prep)                                                                                     |
| `../retired Mercurial plugin/src/sase_hg/workspace_plugin.py`            | Add `ws_prepare_mail` hookimpl (logic from `_prepare_mail_hg` + `_modify_description_for_mailing`)                                      |

**VCS-agnostic helpers staying in `mail_ops.py`:** `_has_valid_parent()`, `_get_cl_description()`,
`_get_branch_number()`, `_run_findreviewers()`, `MailPrepResult`

### Verification

- `just check` passes in all 3 repos
- No `detect_vcs_family` calls remain in `mail_ops.py`
- Mail flow works for both git and hg projects

---

## Phase 4: Move `git_submit.py` Into Bare-Git Plugin

**Goal:** Move `_finalize_submission` to a core util, inline bare-git submission logic into the plugin, delete
`git_submit.py`.

### Changes

| File                                                        | Change                                                                                                              |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `src/sase/submission_utils.py`                              | **CREATE** — extract `finalize_submission()` from `_finalize_submission` (VCS-agnostic)                             |
| `src/sase/workspace_provider/plugins/bare_git_workspace.py` | Inline `submit_git_changespec` + `_submit_via_local_merge` logic into `ws_submit`                                   |
| `src/sase/git_submit.py`                                    | **DELETE**                                                                                                          |
| `tests/test_git_submit.py`                                  | **DELETE** or migrate to bare_git_workspace tests                                                                   |
| `../sase-github/src/sase_github/workspace_plugin.py`        | Change `from sase.git_submit import _finalize_submission` → `from sase.submission_utils import finalize_submission` |

### Verification

- `just check` passes
- `grep -r "git_submit" src/ ../sase-github/` returns nothing
- Submission works for bare-git and GitHub projects

---

## Phase 5: Move `git_workspace.py` Into Bare-Git Plugin

**Goal:** Move bare-git workspace management functions to the plugin, delete `git_workspace.py`.

### Key decisions

- `parse_bare_repo_dir()` → move to `src/sase/workspace_utils.py` (it's a `.gp` file field parser like
  `parse_workspace_dir`, used by both sase-github and bare_git)
- `_set_bare_repo_dir()`, `resolve_git_ref()`, `init_bare_git_project()`, `_ResolvedGitRef` → move to
  `bare_git_workspace.py`

### Changes

| File                                                        | Change                                                                                                               |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `src/sase/workspace_utils.py`                               | Add `parse_bare_repo_dir()` (moved from `git_workspace.py`)                                                          |
| `src/sase/workspace_provider/plugins/bare_git_workspace.py` | Move `_set_bare_repo_dir`, `resolve_git_ref`, `init_bare_git_project`, `_ResolvedGitRef`                             |
| `src/sase/git_workspace.py`                                 | **DELETE**                                                                                                           |
| `src/sase/scripts/git_setup.py`                             | Update imports to `bare_git_workspace`                                                                               |
| `src/sase/main/entry.py`                                    | Update `init-git` import to `bare_git_workspace`                                                                     |
| `tests/test_git_workspace.py`                               | **DELETE** or migrate                                                                                                |
| `../sase-github/src/sase_github/workspace_plugin.py`        | Change `from sase.git_workspace import parse_bare_repo_dir` → `from sase.workspace_utils import parse_bare_repo_dir` |

### Verification

- `just check` passes in all repos
- `grep -r "git_workspace" src/ ../sase-github/` returns nothing
- `sase init-git` and `#git:ref` workflows still work

---

## Phase 6: Data-Driven VCS Family Mapping + `running_field.py` Cleanup

**Goal:** Remove hard-coded VCS family sets; delegate `get_workspace_directory()` to existing hooks.

### 6A: Add `vcs_family` field to `WorkflowMetadata`

| File                                                        | Change                                                                                          |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `src/sase/workspace_provider/_hookspec.py`                  | Add `vcs_family: str = ""` to `WorkflowMetadata`                                                |
| `src/sase/workspace_provider/_registry.py`                  | Refactor `get_display_name_by_vcs_family()` to use `vcs_family` field instead of hard-coded set |
| `src/sase/workspace_provider/plugins/bare_git_workspace.py` | Add `vcs_family="git"` to metadata                                                              |
| `../sase-github/src/sase_github/workspace_plugin.py`        | Add `vcs_family="git"` to metadata                                                              |
| `../retired Mercurial plugin/src/sase_hg/workspace_plugin.py`            | Add `vcs_family="hg"` to metadata                                                               |

### 6B: Migrate `running_field.py:get_workspace_directory()`

Replace the `.git` check + `sase_hg_get_workspace` fallback with delegation to the existing `ws_get_workspace_directory`
hook.

| File                                             | Change                                                                                                                                  |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/running_field.py`                      | Rewrite `get_workspace_directory()` to call `workspace_provider.get_workspace_directory()` (the hook-based registry function)           |
| `../retired Mercurial plugin/src/sase_hg/workspace_plugin.py` | Update `ws_get_workspace_directory` to call `sase_hg_get_workspace` subprocess directly (avoid circular import through `running_field`) |

### Verification

- `just check` passes in all repos
- `get_workspace_directory("project", 1)` works for git and hg projects
- No hard-coded `{"gh", "git"}` family set remains

---

## Summary

| Deleted from core           | Phase |
| --------------------------- | ----- |
| `src/sase/git_utils.py`     | 2     |
| `src/sase/git_submit.py`    | 4     |
| `src/sase/git_workspace.py` | 5     |

| Created in core                | Phase |
| ------------------------------ | ----- |
| `src/sase/submission_utils.py` | 4     |

| New hooks                               | Phase |
| --------------------------------------- | ----- |
| `vcs_diff_with_untracked(cwd, timeout)` | 1     |
| `vcs_committed_diff(cwd, timeout)`      | 1     |
| `ws_prepare_mail(...)`                  | 3     |

| Modified dataclass                      | Phase |
| --------------------------------------- | ----- |
| `WorkflowMetadata` + `vcs_family` field | 6     |

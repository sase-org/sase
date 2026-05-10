---
create_time: 2026-03-29 15:02:19
status: done
prompt: sdd/prompts/202603/branch_naming_reform.md
---

# Branch Naming Reform and Immutable Branch Alias Support

## Problem

When a ChangeSpec transitions Draft→Ready, the `_N` suffix is stripped from its NAME (e.g., `sase_xprompt_snippets_1` →
`sase_xprompt_snippets`). The system then tries to rename the corresponding git branch, but two design flaws cause a
checkout failure:

1. **Underscore-to-hyphen conversion**: `changespec_name_to_branch()` strips the project prefix and converts all
   underscores to hyphens. So `sase_xprompt_snippets` becomes `xprompt-snippets`. But the actual branch on GitHub/origin
   is `sase_xprompt_snippets_1` (created using the ChangeSpec name directly via `git checkout -b`).

2. **No branch alias for GitHub**: For GitHub projects with open PRs, the branch can't be renamed without closing the
   PR. The code skips the remote push but still does a local rename in one AXE workspace. Other workspaces and the
   remote still have the old name, and `resolve_revision` can't find any matching branch.

**Error observed**:
`checkout failed: git checkout failed: error: pathspec 'xprompt-snippets' did not match any file(s) known to git`

## Design Constraints

1. **Branch names = ChangeSpec names**: The branch for ChangeSpec `sase_xprompt_snippets` must be named
   `sase_xprompt_snippets`. No prefix stripping, no hyphen conversion.
2. **No dashes in branch names**: Only underscores.
3. **GitHub immutable branches**: When a PR exists, the branch can't be renamed. The original branch name (with suffix)
   must be persisted and used for resolution.
4. **VCS-agnostic**: The branch alias mechanism must be available to any VCS provider, not just GitHub.
5. **retired Mercurial plugin unchanged**: The Mercurial provider's behavior must not change.

## Phase 1: Branch Naming Reform — Branch Names = ChangeSpec Names for Git

**Goal**: Eliminate the underscore-to-hyphen conversion and project prefix stripping for git providers, so branch names
match ChangeSpec names exactly.

### Design

Add two new VCS provider hooks that each provider implements to control its own branch naming convention:

- `derive_branch_name(changespec_name, project_basename) -> str` — derives the branch name for a suffix-stripped
  ChangeSpec (i.e., the "Ready" form).
- `derive_branch_name_with_suffix(changespec_name, project_basename) -> str` — derives the branch name preserving the
  `_N` suffix (i.e., the "Draft" form).

**Default implementation** (in base class): calls existing `changespec_name_to_branch()` / `_with_suffix()`. This
preserves Mercurial behavior without any changes to retired Mercurial plugin.

**GitCommon override**:

- `derive_branch_name`: calls `strip_reverted_suffix(changespec_name)` — just strips the suffix, no prefix strip, no
  hyphen conversion.
- `derive_branch_name_with_suffix`: returns `changespec_name` unchanged.

### Changes

| File                                  | Change                                                                                                                                                          |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `vcs_provider/_hookspec.py`           | Add `vcs_derive_branch_name()` and `vcs_derive_branch_name_with_suffix()` hookspecs                                                                             |
| `vcs_provider/_base.py`               | Add default implementations using existing `changespec_name_to_branch*()` functions                                                                             |
| `vcs_provider/_plugin_manager.py`     | Add delegation methods                                                                                                                                          |
| `vcs_provider/plugins/_git_common.py` | Override with identity-like behavior (strip suffix only)                                                                                                        |
| `status_state_machine/suffix.py`      | `handle_suffix_strip`: use `provider.derive_branch_name()` instead of `changespec_name_to_branch()`                                                             |
| `status_state_machine/suffix.py`      | `handle_suffix_append`: use `provider.derive_branch_name_with_suffix()` instead of `changespec_name_to_branch_with_suffix()`                                    |
| `vcs_provider/plugins/_git_common.py` | `vcs_resolve_revision`: update candidate list to try ChangeSpec name directly (already first candidate), keep old hyphenated names as backward-compat fallbacks |
| `tests/`                              | Update `test_sase_utils.py` and `test_vcs_resolve_revision_fallback.py`                                                                                         |

### Backward Compatibility

`vcs_resolve_revision` must still find branches created with the old naming convention (hyphenated, prefix-stripped).
Keep the old candidates in the fallback list so existing branches continue to resolve. The candidate list becomes:

1. `changespec_name` (e.g., `sase_xprompt_snippets`) — **already first**
2. `derive_branch_name_with_suffix()` result (e.g., `sase_xprompt_snippets_1` when suffix present; same as #1 when not)
3. `derive_branch_name()` result (e.g., `sase_xprompt_snippets`)
4. Old `changespec_name_to_branch_with_suffix()` for backward compat (e.g., `xprompt-snippets_1`)
5. Old `changespec_name_to_branch()` for backward compat (e.g., `xprompt-snippets`)
6. Prefix-stripped with underscores (e.g., `xprompt_snippets`) — existing fallback

## Phase 2: Branch Alias Persistence for Immutable Branches

**Goal**: When a VCS provider cannot rename a branch (e.g., GitHub PR), persist the original branch name so
`resolve_revision` can find it.

### Design

**Branch map file**: `~/.sase/projects/<project_basename>/branch_map.json`

```json
{
  "sase_xprompt_snippets": "sase_xprompt_snippets_1"
}
```

This is a simple mapping from current ChangeSpec name → actual branch name. It is VCS-agnostic: any provider can write
to it when a branch can't be renamed.

**Why a separate file instead of a ChangeSpec field**:

- No ChangeSpec parser changes needed.
- `resolve_revision` can read it without changing its signature or requiring callers to pass extra data (there are 25+
  callers).
- Clean separation of concerns: the branch map is VCS metadata, not ChangeSpec metadata.

**New VCS provider hook**: `can_rename_branch(cwd) -> bool`

- Default: `True` (bare git and Mercurial can rename).
- GitHub overrides: `False` when a PR exists on the current branch. Use `gh pr view` to check, or simply return `False`
  unconditionally for simplicity (GitHub branches are always immutable once pushed with a PR).

### Changes

| File                                            | Change                                                                                                                                                                                                                              |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `vcs_provider/_hookspec.py`                     | Add `vcs_can_rename_branch()` hookspec                                                                                                                                                                                              |
| `vcs_provider/_base.py`                         | Add default `can_rename_branch()` returning `True`                                                                                                                                                                                  |
| `vcs_provider/_plugin_manager.py`               | Add delegation method                                                                                                                                                                                                               |
| `vcs_provider/plugins/_git_common.py`           | Override returning `True` (bare git can rename)                                                                                                                                                                                     |
| `../sase-github/src/sase_github/plugin.py`      | Override returning `False`                                                                                                                                                                                                          |
| `status_state_machine/suffix.py`                | `handle_suffix_strip`: check `can_rename_branch()`. If False, skip rename and write mapping to `branch_map.json`. Also skip the local rename (currently it still renames locally even for GitHub, causing workspace inconsistency). |
| `status_state_machine/suffix.py`                | `handle_suffix_append`: similar — if branch map entry exists, update the mapping key rather than renaming                                                                                                                           |
| `vcs_provider/plugins/_git_common.py`           | `vcs_resolve_revision`: read `branch_map.json` and try mapped branch as the very first candidate                                                                                                                                    |
| `core/branch_map.py` (new)                      | Utility module for reading/writing branch_map.json: `read_branch_map(project_basename) -> dict`, `write_branch_alias(project_basename, name, branch)`, `remove_branch_alias(project_basename, name)`                                |
| `ace/archive.py`                                | Clean up branch map entry when ChangeSpec is archived                                                                                                                                                                               |
| `ace/revert.py`                                 | Clean up branch map entry when ChangeSpec is reverted                                                                                                                                                                               |
| `workspace_provider/plugins/bare_git_submit.py` | Clean up branch map entry when ChangeSpec is submitted                                                                                                                                                                              |
| `tests/`                                        | Unit tests for branch_map module, integration tests for suffix strip/append with GitHub provider                                                                                                                                    |

### Flow: Suffix Strip on GitHub

1. `handle_suffix_strip("sase.gp", "sase_xprompt_snippets_1", "sase_xprompt_snippets")` is called.
2. NAME field updated: `sase_xprompt_snippets_1` → `sase_xprompt_snippets`.
3. Gets VCS provider. Calls `provider.can_rename_branch(workspace_dir)` → `False` (GitHub).
4. Skips both local and remote branch rename.
5. Writes `branch_map.json`: `{"sase_xprompt_snippets": "sase_xprompt_snippets_1"}`.
6. Later, `resolve_revision("sase_xprompt_snippets", "sase", cwd)`:
   - Reads `branch_map.json` → finds `sase_xprompt_snippets_1`.
   - Tries `sase_xprompt_snippets_1` as first candidate → found! Returns it.

### Flow: Suffix Append on GitHub (Ready → Draft)

1. `handle_suffix_append("sase.gp", "sase_xprompt_snippets", "sase_xprompt_snippets_2")` is called.
2. NAME field updated: `sase_xprompt_snippets` → `sase_xprompt_snippets_2`.
3. Gets VCS provider. Calls `provider.can_rename_branch(workspace_dir)` → `False`.
4. Skips rename. Reads existing branch_map: `{"sase_xprompt_snippets": "sase_xprompt_snippets_1"}`.
5. Removes old key, writes new: `{"sase_xprompt_snippets_2": "sase_xprompt_snippets_1"}`.
6. The actual branch on GitHub is still `sase_xprompt_snippets_1`. Resolution works via branch_map.

## Phase 3: End-to-End Validation and retired Mercurial plugin Compatibility

**Goal**: Verify the full system works across all VCS providers and clean up.

### Changes

| Task                                 | Details                                                                                            |
| ------------------------------------ | -------------------------------------------------------------------------------------------------- |
| Run `just check` in sase repo        | Lint, type-check, tests                                                                            |
| Run `just check` in sase-github repo | Verify plugin changes compile and pass                                                             |
| Run `just check` in retired Mercurial plugin repo | Verify NO changes needed and existing tests pass                                                   |
| Verify backward compat               | Existing branches with old hyphenated names should still resolve via fallback candidates           |
| Verify TUI checkout                  | ChangeSpec with BRANCH alias resolves and checks out correctly                                     |
| Clean up deprecated code             | Mark `changespec_name_to_branch()` / `_with_suffix()` as backward-compat-only (add docstring note) |

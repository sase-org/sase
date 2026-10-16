---
title: VCS provider API
description: Contributor contract for implementing and selecting VCS providers.
---

# VCS provider API

This page documents the provider hooks and classification interfaces.

## Plugin Architecture

VCS providers are implemented as [pluggy](https://pluggy.readthedocs.io/) plugins. The
core `sase` package only bundles the **BareGitPlugin** (for plain git repositories).
Additional VCS backends are installed as separate packages:

| Package       | Plugin          | Description                               |
| ------------- | --------------- | ----------------------------------------- |
| `sase` (core) | `BareGitPlugin` | Standard git operations (bundled)         |
| `sase-github` | `GitHubPlugin`  | Git + GitHub CLI (`gh`) for PR operations |

Install optional providers into the same managed SASE environment:

```bash
sase plugin install github   # GitHub PR support
```

Plugins register themselves via the `sase_vcs` entry point group. The plugin manager
loads all registered plugins and dispatches VCS operations through pluggy's
`firstresult=True` hook system — the first plugin that returns a non-`None` result wins.

### Hook Specification

All VCS operations are defined in `VCSHookSpec` (`src/sase/vcs_provider/_hookspec.py`).
Each method is prefixed with `vcs_`. Most operation hooks return
`tuple[bool, str | None]` (success flag and optional output); query and capability hooks
return typed values such as strings, lists, sets, booleans, or wire records. Plugins
implement only the hooks they support; unsupported operations return `None` and are
skipped.

The hooks are organized into several groups:

- **Core operations** — `vcs_checkout`, `vcs_diff`, `vcs_diff_revision`,
  `vcs_apply_patch`, `vcs_apply_patches`, `vcs_add_remove`, `vcs_clean_workspace`,
  `vcs_commit`, `vcs_amend`, `vcs_rename_branch`, `vcs_rebase`, `vcs_archive`,
  `vcs_prune`, `vcs_stash_and_clean`
- **Optional core** — `vcs_resolve_revision`, `vcs_revision_id`,
  `vcs_resolve_current_patch_head_ref`, `vcs_show_revision`, `vcs_diff_with_untracked`,
  `vcs_committed_diff`, `vcs_get_default_parent_revision`, `vcs_diff_name_status`,
  `vcs_diff_line_stats`, `vcs_log`, `vcs_file_at_revision`,
  `vcs_existing_branch_suffixes`
- **Remote timeline** — `vcs_resolve_remote_log_ref`, `vcs_fetch_remote`, and
  `vcs_partition_commits` (resolve, refresh, and compare the remote ref that
  `sase stitch list` uses to mark commits synced, unpushed, or remote-only)
- **Sync operations** — `vcs_sync_workspace`, `vcs_is_sync_in_progress`,
  `vcs_get_conflicted_files`, `vcs_continue_sync`, `vcs_abort_sync`
- **Commit dispatch** — `vcs_create_commit`, `vcs_create_proposal`,
  `vcs_create_pull_request` (the three commit workflow methods dispatched by
  `CommitWorkflow`), plus `vcs_finalize_commit` (replays idempotent post-commit work —
  bead amend, push-with-retry — when `sase stitch create --resume` finishes a workflow
  whose dispatch was interrupted by a merge conflict; plugins that cannot safely replay
  finalization can leave this unimplemented, and the workflow will only replay its
  tracking steps) and `vcs_supports_commit_excludes` (whether the provider honors
  `sase stitch create -x/--exclude`). See
  [Commit workflow orchestrator](commit-workflow-orchestrator.md#resume-after-conflict).
- **Issue-tracker operations** — `vcs_list_issues`, `vcs_get_issue`, `vcs_create_issue`,
  `vcs_update_issue`, `vcs_get_issue_url` (optional; implemented by providers with a
  native issue tracker)
- **VCS-agnostic operations** — `vcs_abandon_change`,
  `vcs_prepare_description_for_reword`, `vcs_normalize_bug_value`, `vcs_get_change_url`,
  `vcs_get_change_body`
- **Pull-request operations** — `vcs_list_pull_requests` (list existing pull requests;
  only implemented by providers with native PR support, such as `sase-github`)
- **Info and review hooks** — `vcs_reword`, `vcs_reword_add_tag`, `vcs_get_description`,
  `vcs_get_branch_name`, `vcs_get_pr_number`, `vcs_get_cl_number` (legacy alias of the
  PR number), `vcs_get_workspace_name`, `vcs_has_local_changes`, `vcs_get_bug_number`,
  `vcs_mail`, `vcs_fix`, `vcs_upload`, `vcs_find_reviewers`, `vcs_rewind`
- **Branch naming hooks** — `vcs_derive_branch_name`,
  `vcs_derive_branch_name_with_suffix` (compute branch names from Patch names),
  `vcs_can_rename_branch` (check if branch renaming is supported)
- **Classification hooks** — `vcs_detect_repo_type` (detect VCS markers like `.hg/` or
  `.git/`) and `vcs_classify_repo` (classify git repos by remote URL, e.g. GitHub vs
  bare)

### Disabling Plugins

The VCS provider registry loads provider entry points directly. It does not currently
consult the resource-plugin disable switches described in
[docs/reference/environment-variables.md](../reference/environment-variables.md#plugin-system).
Use `SASE_VCS_PROVIDER` or `vcs_provider.provider` to force a provider selection.

## Classification Hooks

VCS provider detection is pluggable via two classification hooks:

<a id="vcsdetectrepotype"></a>

### `vcs_detect_repo_type`

Checks for VCS markers in a directory (e.g., `.hg/`, `.git/`). Each plugin checks for
its own marker and returns the VCS type name (e.g., `"hg"`) or `None`. Used during
auto-detection when walking up the directory tree.

<a id="vcsclassifyrepo"></a>

### `vcs_classify_repo`

For git repositories, further classifies by examining the remote URL. For example, the
`sase-github` plugin claims repos whose remote host is in the configured GitHub host
set, returning `"github"` for `github.com` by default and for any hosts listed in
`github_hosts`. Unclaimed repos fall through to the `"bare_git"` provider. This allows
hosting-specific plugins to provide enhanced functionality (e.g., PR operations via `gh`
CLI) without modifying the core.

## Related

- [Contribute](index.md) — the section hub.

# Workspace Provider Reference

The **workspace provider layer** is an abstraction that handles workspace-level operations that vary across VCS hosting
environments. While the [VCS provider](vcs.md) handles low-level version control commands (commit, diff, checkout), the
workspace provider handles higher-level concerns: workflow type detection, reference resolution (e.g., `#git:repo` or
`#gh:org/repo`), change submission, mail preparation, and workspace directory management.

## Plugin Architecture

Workspace providers are implemented as [pluggy](https://pluggy.readthedocs.io/) plugins, following the same pattern as
VCS plugins. The core `sase` package bundles the **BareGitWorkspacePlugin** for local bare-remote git repositories.
Additional backends are installed as separate packages:

| Package       | Plugin                   | Description                                     |
| ------------- | ------------------------ | ----------------------------------------------- |
| `sase` (core) | `BareGitWorkspacePlugin` | Bare-git repos (local filesystem remote)        |
| `sase-github` | `GitHubWorkspacePlugin`  | GitHub-hosted repos (PR workflows via `gh` CLI) |
| `sase-google` | `HgWorkspacePlugin`      | Mercurial workspaces                            |

Plugins register themselves via the `sase_workspace` entry point group. The plugin manager loads all registered plugins
and dispatches operations through pluggy hooks. Most hooks use `firstresult=True` — the first plugin that returns a
non-`None` result wins.

### Hook Specification

All workspace operations are defined in `WorkspaceHookSpec` (`src/sase/workspace_provider/_hookspec.py`). Each method is
prefixed with `ws_` to namespace them within the pluggy project.

## Key Data Types

### WorkflowMetadata

Each workspace plugin declares metadata about the workflow type it supports:

| Field                      | Type   | Description                                                    |
| -------------------------- | ------ | -------------------------------------------------------------- |
| `workflow_type`            | string | Short name used in `#type:ref` prompts (e.g., `"git"`, `"gh"`) |
| `ref_pattern`              | string | Regex matching `#type:ref` or `#type(ref)` syntax              |
| `display_name`             | string | Human-readable name (e.g., `"Git (bare)"`, `"GitHub"`)         |
| `pre_allocated_env_prefix` | string | Env-var prefix for pre-allocated workspace variables           |
| `vcs_family`               | string | VCS family (e.g., `"git"`, `"hg"`)                             |
| `vcs_provider_name`        | string | Specific VCS provider name (e.g., `"bare_git"`, `"github"`)    |

### ResolvedRef

Result of resolving a workspace reference:

| Field                   | Type           | Description                             |
| ----------------------- | -------------- | --------------------------------------- |
| `project_file`          | string         | Path to the project spec file           |
| `project_name`          | string         | Name of the project                     |
| `primary_workspace_dir` | string         | Path to the primary workspace directory |
| `checkout_target`       | string         | Branch or revision to check out         |
| `extra`                 | dict[str, str] | Additional plugin-specific data         |

## Hook Reference

### Metadata and Detection

| Hook                       | Returns                    | Description                                  |
| -------------------------- | -------------------------- | -------------------------------------------- |
| `ws_get_workflow_metadata` | `WorkflowMetadata \| None` | Declare this plugin's workflow type metadata |
| `ws_detect_workflow_type`  | `str \| None`              | Detect workflow type from a project file     |
| `ws_get_change_label`      | `str \| None`              | Get the change label (e.g., `"PR"`, `"CL"`)  |
| `ws_get_workspace_name`    | `str \| None`              | Get the workspace/project name for a CWD     |

`ws_get_workflow_metadata` is the only hook that collects results from **all** plugins (not `firstresult`). This allows
the registry to build a complete map of all available workflow types.

### Reference Resolution and Workflow Setup

| Hook                         | Returns                 | Description                                       |
| ---------------------------- | ----------------------- | ------------------------------------------------- |
| `ws_resolve_ref`             | `ResolvedRef \| None`   | Resolve a `#type:ref` reference to workspace info |
| `ws_setup_workflow`          | `dict[str,str] \| None` | Set up environment variables for a workflow run   |
| `ws_get_workspace_directory` | `str \| None`           | Get or create a workspace directory for a clone   |

### Change Submission and Review

| Hook                                   | Returns                            | Description                                     |
| -------------------------------------- | ---------------------------------- | ----------------------------------------------- |
| `ws_submit`                            | `tuple[bool, str \| None] \| None` | Submit a ChangeSpec (merge, push, etc.)         |
| `ws_prepare_mail`                      | `object \| None`                   | Prepare a change for mailing/review             |
| `ws_extract_change_identifier`         | `tuple[str, str] \| None`          | Extract identifier from a CL/PR URL             |
| `ws_supports_reviewer_comments`        | `bool \| None`                     | Check if a CL URL supports reviewer comments    |
| `ws_generate_reviewer_comments_script` | `str \| None`                      | Generate a script to fetch reviewer comments    |
| `ws_generate_submitted_check_script`   | `str \| None`                      | Generate a script to check if a CL is submitted |

### Commit Formatting

| Hook                           | Returns        | Description                                               |
| ------------------------------ | -------------- | --------------------------------------------------------- |
| `ws_format_commit_description` | `bool \| None` | Format a commit description file (add tags, prefix, etc.) |

## Registry Functions

The workspace provider package (`sase.workspace_provider`) exports convenience functions that call through the plugin
manager. These are the primary API for consumers:

| Function                           | Description                                  |
| ---------------------------------- | -------------------------------------------- |
| `detect_workflow_type()`           | Detect workflow type for a project file      |
| `get_change_label()`               | Get the change label for a project           |
| `resolve_ref()`                    | Resolve a workspace reference                |
| `submit_changespec()`              | Submit a ChangeSpec                          |
| `get_workspace_directory()`        | Get a workspace directory for a clone number |
| `prepare_mail()`                   | Prepare a change for review                  |
| `format_commit_description()`      | Format a commit description                  |
| `get_all_workflow_metadata()`      | Get metadata from all registered plugins     |
| `get_workflow_names()`             | Get all registered workflow type names       |
| `get_display_name()`               | Get display name for a workflow type         |
| `get_display_name_by_vcs()`        | Get display name by VCS provider name        |
| `get_display_name_by_vcs_family()` | Get display name by VCS family               |
| `get_workspace_name()`             | Get workspace/project name for a directory   |
| `get_ref_patterns()`               | Get all registered ref patterns              |
| `get_pre_allocated_env_prefix()`   | Get env-var prefix for a workflow type       |

## Relationship to VCS Provider

The workspace provider and VCS provider are complementary plugin systems:

| Concern                | VCS Provider                            | Workspace Provider                                |
| ---------------------- | --------------------------------------- | ------------------------------------------------- |
| **Scope**              | Low-level VCS commands                  | High-level workspace operations                   |
| **Examples**           | `git commit`, `git diff`, `hg amend`    | Ref resolution, submit, mail prep, workspace dirs |
| **Plugin granularity** | One active plugin per detected VCS type | All plugins registered, firstresult dispatch      |
| **Entry point**        | `sase_vcs`                              | `sase_workspace`                                  |
| **Hook prefix**        | `vcs_`                                  | `ws_`                                             |

A single plugin package (e.g., `sase-github`) typically provides both a VCS plugin and a workspace plugin.

## Disabling Plugins

Set `SASE_DISABLE_PLUGIN_WORKSPACE` to disable workspace plugins. See
[docs/configuration.md](configuration.md#plugin-system) for details.

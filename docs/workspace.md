# Workspace Provider Reference

The **workspace provider layer** is an abstraction that handles workspace-level operations that vary across VCS hosting
environments. While the [VCS provider](vcs.md) handles low-level version control commands (commit, diff, checkout), the
workspace provider handles higher-level concerns: workflow type detection, reference resolution (e.g., `#git:repo` or
`#gh:org/repo`), change submission, mail preparation, and workspace directory management.

A **workspace reference** is a prompt prefix such as `#cd:/tmp/project`, `#git:sase`, `#gh:sase`, or `#hg:mychange`. It
tells SASE which project and workspace should be used before the rest of the prompt or workflow runs.

## Plugin Architecture

Workspace providers are implemented as [pluggy](https://pluggy.readthedocs.io/) plugins, following the same pattern as
VCS plugins. The core `sase` package bundles the **BareGitWorkspacePlugin** for local bare-remote git repositories.
Additional backends must be installed in the same Python environment as `sase`:

| Package       | Plugin                   | Description                                       |
| ------------- | ------------------------ | ------------------------------------------------- |
| `sase` (core) | `CdWorkspacePlugin`      | Local directory runs via `#cd:<path>` without VCS |
| `sase` (core) | `BareGitWorkspacePlugin` | Bare-git repos (local filesystem remote)          |
| `sase-github` | `GitHubWorkspacePlugin`  | GitHub-hosted repos (PR workflows via `gh` CLI)   |

Plugins register themselves via the `sase_workspace` entry point group. The plugin manager loads all registered plugins
and dispatches operations through pluggy hooks. Most hooks use `firstresult=True` — the first plugin that returns a
non-`None` result wins.

### Hook Specification

All workspace operations are defined in `WorkspaceHookSpec` (`src/sase/workspace_provider/_hookspec.py`). Each method is
prefixed with `ws_` to namespace them within the pluggy project.

## Key Data Types

### WorkflowMetadata

Each workspace plugin declares metadata about the workflow type it supports:

| Field                      | Type   | Description                                                            |
| -------------------------- | ------ | ---------------------------------------------------------------------- |
| `workflow_type`            | string | Short name used in `#type:ref` prompts (e.g., `"cd"`, `"git"`, `"gh"`) |
| `ref_pattern`              | string | Regex matching `#type:ref` or `#type(ref)` syntax                      |
| `display_name`             | string | Human-readable name (e.g., `"Git (bare)"`, `"GitHub"`)                 |
| `pre_allocated_env_prefix` | string | Env-var prefix for pre-allocated workspace variables                   |
| `vcs_family`               | string | VCS family (e.g., `"git"`, `"hg"`)                                     |
| `vcs_provider_name`        | string | Specific VCS provider name (e.g., `"bare_git"`, `"github"`)            |

Built-in metadata includes `SASE_CD` for `#cd` and `SASE_GIT` for `#git`. Plugin packages can add prefixes such as
`SASE_GH` and `SASE_HG`.

### ResolvedRef

Result of resolving a workspace reference:

| Field                   | Type           | Description                             |
| ----------------------- | -------------- | --------------------------------------- |
| `project_file`          | string         | Path to the project spec file           |
| `project_name`          | string         | Name of the project                     |
| `primary_workspace_dir` | string         | Path to the primary workspace directory |
| `checkout_target`       | string         | Branch or revision to check out         |
| `extra`                 | dict[str, str] | Additional plugin-specific data         |

For clone-based git workflows, `primary_workspace_dir` is the primary checkout path and `get_workspace_directory()`
derives numbered sibling workspaces from it. Some provider plugins can leave `primary_workspace_dir` empty and resolve
numbered workspaces through their own helper command.

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

| Hook                         | Returns                  | Description                                       |
| ---------------------------- | ------------------------ | ------------------------------------------------- |
| `ws_resolve_ref`             | `ResolvedRef \| None`    | Resolve a `#type:ref` reference to workspace info |
| `ws_setup_workflow`          | `dict[str, str] \| None` | Set up environment variables for a workflow run   |
| `ws_get_workspace_directory` | `str \| None`            | Get or create a workspace directory for a clone   |

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

| Function                           | Description                                |
| ---------------------------------- | ------------------------------------------ |
| `detect_workflow_type()`           | Detect workflow type for a project file    |
| `get_change_label()`               | Get the change label for a project         |
| `resolve_ref()`                    | Resolve a workspace reference              |
| `submit_changespec()`              | Submit a ChangeSpec                        |
| `get_workspace_directory()`        | Get the directory for a workspace number   |
| `prepare_mail()`                   | Prepare a change for review                |
| `format_commit_description()`      | Format a commit description                |
| `get_all_workflow_metadata()`      | Get metadata from all registered plugins   |
| `get_workflow_names()`             | Get all registered workflow type names     |
| `get_display_name()`               | Get display name for a workflow type       |
| `get_display_name_by_vcs()`        | Get display name by VCS provider name      |
| `get_display_name_by_vcs_family()` | Get display name by VCS family             |
| `get_workspace_name()`             | Get workspace/project name for a directory |
| `get_ref_patterns()`               | Get all registered ref patterns            |
| `get_pre_allocated_env_prefix()`   | Get env-var prefix for a workflow type     |

## Directory Workflow (`#cd`)

The core package also registers `#cd:<path>` as a workspace workflow. It resolves a local directory, makes that
directory the agent/workflow CWD, and deliberately skips numbered workspace allocation, checkout, diff, submit, and
release behavior. `#cd` is the right choice for one-off work in an existing directory when SASE should not prepare or
release a VCS workspace.

Prompts without any workspace reference are normalized to `#git:home`; use `#cd:~` when you want a direct home-directory
run with no VCS workspace management.

Supported examples include `#cd:~`, `#cd:/tmp/project`, `#cd:../sibling`, and `#cd(.)`. The target must already exist
and must be a directory. `~` and environment variables are expanded, and relative paths are resolved from the launching
process's current directory. Prefer the parenthesized form for paths with spaces, for example `#cd(/tmp/my project)`.

## Bare-Git Reference Auto-Initialization

The bundled bare-git provider resolves `#git:<ref>` in four modes:

1. A registered project shorthand, using `~/.sase/projects/<name>/<name>.sase` when it contains `BARE_REPO_DIR` and
   `WORKSPACE_DIR`.
2. A ChangeSpec name found across registered projects.
3. A missing project shorthand with no slash, which initializes a new bare-git project with the same defaults as
   `sase init-git <name>` and then resolves it.
4. A bare repository path, deriving the project name from the path basename and creating the matching ProjectSpec.

The missing-project shorthand is intended for first use from an xprompt or prompt bar: `#git:new_tool #!workflow`
creates the bare-git project on demand instead of requiring a separate `sase init-git new_tool` step.

`#git:home` is special because it is the default for bare prompts. If the `home` ProjectSpec is missing or has not yet
recorded `BARE_REPO_DIR`, SASE bootstraps a managed empty bare-git project at the default `home` paths. To point
`#git:home` at an existing home/dotfiles bare repository instead, configure it first with
`sase init-git home --existing <bare-repo> --clone-dir <checkout-dir>`. Add `#cd:~` to a prompt for a one-off direct
home-directory run without VCS.

The `sase init-git` command also supports `--bare-dir` and `--clone-dir` for new bare-git projects. Its defaults are
`~/.sase/repos/<name>.git` for the bare repo and `~/projects/git/<name>/` for the primary clone.

## Known-Project VCS Fallback

SASE also recognizes provider-prefixed VCS refs that target registered project names even when the corresponding
workspace plugin is not available in the current process. Known projects are discovered from `~/.sase/projects/*/*.sase`
(with legacy `~/.sase/projects/*/*.gp` accepted as a fallback) by reading each `WORKSPACE_DIR:` entry. For example, if
the `sase` project is registered, `#gh:sase #!some/workflow` and the underscore shorthand `#gh_sase #!some/workflow` are
treated as VCS workspace launches rather than ordinary xprompt references.

Non-wait launches allocate the next available numbered workspace for the project and set the VCS update target to the
provider default revision. When registered workspace metadata provides an env prefix, SASE passes the matching
`<PREFIX>_PRE_ALLOCATED`, `<PREFIX>_WORKSPACE_NUM`, and `<PREFIX>_WORKSPACE_DIR` values into the child process. Launches
that start with a wait directive keep workspace number `0` until the dependency is ready, then resolve a real workspace
during normal runner setup. Directory runs such as `#cd` also use workspace number `0` because they do not reserve a
numbered workspace. Before applying the current launch context, SASE removes inherited `SASE_*_PRE_ALLOCATED`,
`SASE_*_WORKSPACE_NUM`, and `SASE_*_WORKSPACE_DIR` variables so nested or follow-up launches do not accidentally reuse a
stale parent workspace.

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

## `sase workspace` CLI

The `sase workspace` command surface inspects and maintains the per-project workspace registry. All subcommands accept
`-p/--project NAME` to override the project; without it, the project is inferred from the current directory via the
nearest managed-checkout marker, the workspace provider hook, and finally a scan of `~/.sase/projects/`.

| Command                             | Description                                                                                            |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `sase workspace list [-j/--json]`   | List registered managed checkouts (always includes primary `#0`).                                      |
| `sase workspace path NUM`           | Print the checkout path for `NUM`. Materializes only when `NUM` already has a claim or registry entry. |
| `sase workspace open NUM`           | Conservative shim that prints the checkout path; reserved for future editor integration.               |
| `sase workspace cleanup -s/--stale` | Remove unclaimed managed checkouts older than `workspace.cleanup_ttl_days`. `-n/--dry-run` previews.   |
| `sase workspace repair [-n]`        | Drop registry entries whose checkout is gone; re-materialize checkouts for live RUNNING claims.        |

`cleanup` and `repair` skip workspace `#0` (primary) and any workspace number with an active claim in the RUNNING field.
`cleanup --include-shares` opts workflow-share checkouts into the same cleanup pass.

## Disabling Plugins

The workspace provider registry loads provider entry points directly. It does not currently consult the resource-plugin
disable switches described in [docs/configuration.md](configuration.md#plugin-system).

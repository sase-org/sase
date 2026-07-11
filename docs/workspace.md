# Workspace Provider Reference

The **workspace provider layer** is an abstraction that handles workspace-level operations that vary across VCS hosting
environments. While the [VCS provider](vcs.md) handles low-level version control commands (commit, diff, checkout), the
workspace provider handles higher-level concerns: workflow type detection, reference resolution (for example `#git:repo`
or `#gh:org/repo`), change submission, mail preparation, and workspace directory management.

A **workspace reference** is a prompt prefix such as `#git:sase`, `#gh:sase`, or a ref registered by another workspace
provider. It tells SASE which project and workspace should be used before the rest of the prompt or workflow runs.

## Plugin Architecture

Workspace providers are implemented as [pluggy](https://pluggy.readthedocs.io/) plugins, following the same pattern as
VCS plugins. The core `sase` package bundles the **BareGitWorkspacePlugin** for local bare-remote git repositories.
Additional backends must be installed in the same Python environment as `sase`:

| Package       | Plugin                   | Description                                     |
| ------------- | ------------------------ | ----------------------------------------------- |
| `sase` (core) | `BareGitWorkspacePlugin` | Bare-git repos (local filesystem remote)        |
| `sase-github` | `GitHubWorkspacePlugin`  | GitHub-hosted repos (PR workflows via `gh` CLI) |

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
| `workflow_type`            | string | Short name used in `#type:ref` prompts (e.g., `"git"`, `"gh"`)         |
| `ref_pattern`              | string | Regex matching `#type:ref` or `#type(ref)` syntax                      |
| `display_name`             | string | Human-readable name (e.g., `"Git (bare)"`, `"GitHub"`)                 |
| `pre_allocated_env_prefix` | string | Env-var prefix for pre-allocated workspace variables                   |
| `vcs_family`               | string | VCS family (e.g., `"git"`, `"hg"`)                                     |
| `vcs_provider_name`        | string | Specific VCS provider name (e.g., `"bare_git"`, `"github"`)            |
| `sdd_storage_policy`       | string | Optional provider SDD policy declaration: `in_tree` or `separate_repo` |

Built-in metadata includes `SASE_GIT` for `#git`. Plugin packages can add prefixes such as `SASE_GH`.

SASE treats `sdd_storage_policy` as authoritative. `in_tree` takes effect immediately, as it does for the built-in
bare-git provider. `separate_repo` requires the provider to materialize a companion before SDD writes or workflow setup
can continue. A positive `.sase/sdd-store.json` record preserves that materialized selection for offline use.

### ResolvedRef

Result of resolving a workspace reference:

| Field                   | Type           | Description                                                                                        |
| ----------------------- | -------------- | -------------------------------------------------------------------------------------------------- |
| `project_file`          | string         | Path to the project spec file                                                                      |
| `project_name`          | string         | Name of the project                                                                                |
| `primary_workspace_dir` | string         | Path to the primary workspace directory                                                            |
| `checkout_target`       | string         | Branch or revision to check out                                                                    |
| `extra`                 | dict[str, str] | Additional plugin-specific data                                                                    |
| `canonical_ref`         | string \| null | Optional stable ref to persist when the matched prompt ref was a provider-specific locator or path |

For clone-based git workflows, `primary_workspace_dir` is the primary checkout path and `get_workspace_directory()`
derives numbered sibling workspaces from it. Some provider plugins can leave `primary_workspace_dir` empty and resolve
numbered workspaces through their own helper command.

When `canonical_ref` is set, launch history, replay selections, and prompt MRU entries use `#<workflow>:<canonical_ref>`
instead of the raw user-entered locator; when it is absent, SASE keeps the matched ref. For example, first-use
repository paths or GitHub owner/repo refs can resolve to a stable SASE project key while still letting the provider
decide the checkout target. `canonical_ref` does not replace `checkout_target`; providers still decide which branch or
revision to check out.

## Hook Reference

### Metadata and Detection

| Hook                       | Returns                    | Description                                  |
| -------------------------- | -------------------------- | -------------------------------------------- |
| `ws_get_workflow_metadata` | `WorkflowMetadata \| None` | Declare this plugin's workflow type metadata |
| `ws_detect_workflow_type`  | `str \| None`              | Detect workflow type from a project file     |
| `ws_get_change_label`      | `str \| None`              | Get the change label (e.g., `"PR"`, `"PR"`)  |
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
| `ws_extract_change_identifier`         | `tuple[str, str] \| None`          | Extract identifier from a PR URL                |
| `ws_supports_reviewer_comments`        | `bool \| None`                     | Check if a PR URL supports reviewer comments    |
| `ws_generate_reviewer_comments_script` | `str \| None`                      | Generate a script to fetch reviewer comments    |
| `ws_generate_submitted_check_script`   | `str \| None`                      | Generate a script to check if a PR is submitted |

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
| `get_sdd_storage_policy_by_vcs()`  | Get an SDD storage policy declared by VCS  |
| `get_workspace_name()`             | Get workspace/project name for a directory |
| `get_ref_patterns()`               | Get all registered ref patterns            |
| `get_pre_allocated_env_prefix()`   | Get env-var prefix for a workflow type     |

## Bare-Git Reference Auto-Initialization

The bundled bare-git provider resolves `#git:<ref>` in four modes:

1. A registered project shorthand, using `~/.sase/projects/<name>/<name>.sase` when it contains `BARE_REPO_DIR` and
   `WORKSPACE_DIR`.
2. A ChangeSpec name found across registered projects.
3. A missing project shorthand with no slash, which initializes a new bare-git project using `~/.sase/repos/<name>.git`
   as the bare repository and `~/projects/git/<name>/` as the primary checkout.
4. A bare repository path, deriving the project name from the path basename and creating the matching ProjectSpec with
   that bare path and the default `~/projects/git/<name>/` primary checkout path.

The missing-project shorthand is intended for first use from an xprompt or prompt bar: `#git:new_tool #!workflow`
creates the bare-git project on demand.

`#git:home` is special because it is the default for bare prompts. If the `home` ProjectSpec is missing or has not yet
recorded `BARE_REPO_DIR`, SASE bootstraps a managed empty bare-git project at the default `home` paths. To point a
project at an existing bare repository, use `#git:<bare-repo-path>`; the path basename becomes the SASE project name, so
`#git:/path/to/home.git` registers the `home` project.

Bare-git projects use in-tree SDD under `sdd/`. SASE creates or refreshes generated SDD guide files during new project
initialization, existing bare-repo registration, and first `#git` or `sase workspace open` materialization. When
materialization owns the checkout setup, SASE commits and pushes only those generated guide paths with an
`Initialize SDD` init commit.

## Known-Project VCS Fallback

SASE also recognizes provider-prefixed VCS refs that target registered project names even when the corresponding
workspace plugin is not available in the current process. Known projects are discovered from `~/.sase/projects/*/*.sase`
(with legacy `~/.sase/projects/*/*.gp` accepted as a fallback) by reading each `WORKSPACE_DIR:` entry. For example, if
the `sase` project is registered, `#gh:sase #!some/workflow` and the underscore shorthand `#gh_sase #!some/workflow` are
treated as VCS workspace launches rather than ordinary xprompt references.

Known-project fallback is lifecycle-aware. Normal launch and xprompt/catalog discovery paths only include active
projects; a registered project with `PROJECT_STATE: inactive` or `PROJECT_STATE: sibling` is hidden from launch pickers
and broad known-project lookup. Legacy `archived` and `closed` values are read as inactive. If a prompt explicitly names
an inactive known project, launch resolution fails with an activation hint instead of silently allocating work. Use
`sase project list --state all` to inspect hidden projects and `sase project activate <project>` before launching normal
work there. Configured linked repositories use hidden `PROJECT_STATE: sibling` records instead of normal launch
discovery. To prepare one, pass its linked-repo name as the workspace CLI's project override:
`sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>`. In a SASE-launched agent session, that command
records the linked-repo name in the run artifacts; ACE uses that record for opened-workspace context, and the commit
finalizer uses it to enforce only configured numbered linked-repo workspaces the agent explicitly opened.

Non-wait launches allocate the next available numbered workspace for the project and set the VCS update target to the
provider default revision. When registered workspace metadata provides an env prefix, SASE passes the matching
`<PREFIX>_PRE_ALLOCATED`, `<PREFIX>_WORKSPACE_NUM`, and `<PREFIX>_WORKSPACE_DIR` values into the child process. Launches
that start with a wait directive keep workspace number `0` until the dependency is ready, then resolve a real workspace
during normal runner setup. Before applying the current launch context, SASE removes inherited `SASE_*_PRE_ALLOCATED`,
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

## Workspace Directory Layout

SASE resolves every workspace through a per-project store rather than by string-appending `_<num>` to the primary
checkout path. The store assigns workspaces stable numeric identities and chooses a physical path according to the
configured root policy.

### Numeric Identity

| Range     | Meaning                                                                                                                                         |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `#0`      | Primary checkout from ProjectSpec `WORKSPACE_DIR`. Also used as the placeholder for deferred launches.                                          |
| `#1`–`#9` | Reserved. The allocator never hands these out, but legacy tests and call sites that pass them by hand still work via the compatibility wrapper. |
| `#10`+    | Claim-allocated numbered workspaces. New agents allocate from this unified pool starting at `#10`.                                              |

Older releases allocated agent workspaces starting at `#1` and special-cased axe at `#100`. The current allocator uses
one shared pool for every claim source; `claim_next_axe_workspace()`, `get_first_available_axe_workspace()`, launch
executor pre-claims, and `axe` deferred claims all start at `#10` unless a caller passes explicit `min_workspace` /
`max_workspace` bounds.

User-facing checkout suffixes are `<project>_<num>` regardless of root policy. The primary checkout retains its
`WORKSPACE_DIR` path with no suffix.

### Root Policy

The physical location of managed checkouts is controlled by `workspace.root` (see
[`docs/configuration.md`](configuration.md#workspace)) and the `SASE_WORKSPACE_ROOT` environment override:

| Value         | Layout                                                                                                                                                                                                                                 |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `xdg-state`   | Default. Platform state root plus namespace: `$XDG_STATE_HOME/sase/workspaces/<project_key>/<project>_<num>/` on Linux, `~/Library/Application Support/sase/workspaces/...` on macOS, `%LOCALAPPDATA%\sase\workspaces\...` on Windows. |
| `adjacent`    | Legacy `<primary>_<num>/` siblings of the primary checkout. Explicit opt-in; byte-for-byte compatible with previous releases.                                                                                                          |
| absolute path | Treat the configured path as the managed-root base and create `<project_key>/<project>_<num>/` checkouts under it.                                                                                                                     |

`SASE_WORKSPACE_ROOT` overrides `workspace.root` for the process and is interpreted as an explicit managed root
directory, with the project namespace appended underneath it. Use an absolute path for predictable behavior. It is the
recommended override for ephemeral test runs and CI sandboxes.

The `project_key` namespace under managed roots is derived from a single Git remote slug when available, otherwise from
the primary-path basename plus a short hash so two projects with the same basename do not collide. An explicit
`workspace.project_key` in config wins over the heuristic.

Each managed checkout writes a `.sase/checkout.json` marker recording the project name, project key, workspace number,
primary workspace path, and the registry path. CWD-based project inference (used by `sase bead`, the file panel, and
similar callers) reads the nearest marker first and only falls back to sibling-pattern scanning for adjacent legacy
layouts.

Configured linked repositories for a numbered checkout are cloned beneath that host checkout at
`sase/repos/<linked_repo>`. SASE protects the directory immediately with the per-clone `/sase/repos/` exclude rule; run
`sase init workspace` to add the same rule durably to the tracked root `.gitignore`. Use `--check` to report drift,
`--diff` to preview it, or `--no-commit` to write the rule without the normal project commit/push sequence. A linked
clone found only at the legacy `.sase/workspaces/<linked_repo>` path remains visible to read-only resolution and is
moved to the canonical path the next time it is materialized.

### Registry

For non-adjacent roots SASE maintains a per-project registry alongside the checkouts. The registry tracks every
workspace the store owns — including primary `#0` — and records `checkout_dir`, `materialization`, `role`, `pinned`,
`created_at`, and `last_used_at`. Registry writes are atomic. `sase workspace repair` is the canonical way to reconcile
the registry against the filesystem after a manual delete or a partially completed migration. Adjacent checkouts keep
their legacy sibling behavior and normally do not write a persistent registry; `cleanup` and `repair` treat a missing
registry as "nothing managed here" rather than an error.

### Adjacent Compatibility And Migration

The default `workspace.root` is `xdg-state` for unconfigured installations and projects. Existing adjacent
`<primary>_<num>/` directories are not moved during ordinary resolution; SASE only creates new managed checkouts under
the configured root. To carry old adjacent checkouts into the managed root, run:

```bash
sase workspace migrate --to xdg-state [--symlink-transition] [--dry-run]
sase workspace migrate --finalize [--dry-run]
```

The first form moves every existing `<primary>_<num>` checkout under the managed root and records it in the registry.
With `--symlink-transition`, the original `<primary>_<num>` path becomes a symlink to the canonical managed checkout so
legacy tooling that walks `..` for siblings keeps working. Migration refuses to overwrite a real directory at the
managed destination; pre-existing managed content is reported and skipped. `--dry-run` reports the planned actions
without touching the filesystem or registry.

Once workflows have adapted to the managed paths, `sase workspace migrate --finalize` removes the leftover transition
symlinks without touching the canonical checkouts.

### Backup, Container, And Network-Storage Caveats

- **Backups.** With `adjacent`, every numbered checkout sits inside the user's normal source tree and gets captured by
  Borg/Restic/Syncthing/BTRFS snapshots. Managed roots move execution state out of the primary backup surface; if you
  want crashed-agent working trees included, add `~/.local/state/sase/workspaces/` (or the platform equivalent) to your
  backup profile explicitly.
- **BTRFS / ZFS snapshots.** A snapshot of `~/projects` no longer freezes every workspace atomically once the canonical
  checkouts live elsewhere. Snapshot the state root alongside the source tree if atomicity matters.
- **NFS / network home directories.** If `$HOME` is on NFS and your source tree is on local SSD, switching to
  `xdg-state` can move workspaces to slow storage. Set `workspace.root` to an absolute path on the fast volume, or keep
  `adjacent`.
- **Containers / devcontainers / Toolbx / Distrobox.** Tools that bind-mount `~/projects` into a container will not see
  managed checkouts under `~/.local/state`. Either add a second mount for the managed root or keep
  `workspace.root: adjacent` for the containerized project.
- **Recursive search performance.** `rg`, `fd`, IDE workspace-wide search and similar tools fan out N times across
  adjacent siblings. Managed roots avoid this by default.

### Post-Default Migration Guidance

Users and environments that still rely on sibling checkouts should set `workspace.root: adjacent` explicitly, either in
the project-local `sase.yml` or globally in `~/.config/sase/sase.yml`. The managed-root default is intentionally
non-migrating: it prevents silent moves, but a project with old adjacent clones and no explicit config will create new
non-primary checkouts under the state root after the default change.

Before switching shared CI images, containers, or network-mounted homes to the default, confirm the state root is
mounted, backed up, and on storage fast enough for agent work. Use an absolute `workspace.root` when the platform state
directory is not the right operational location.

## `sase workspace` CLI

The `sase workspace` command surface inspects numbered workspace paths and maintains the per-project registry used by
non-adjacent roots. All subcommands accept `-p/--project NAME` to override the project; without it, the project is
inferred from the current directory via the nearest managed-checkout marker, the workspace provider hook, and finally a
scan of `~/.sase/projects/`. With no subcommand, `sase workspace` defaults to `sase workspace list` with default
options. Use `sase workspace list -p NAME` or `sase workspace list --json` when passing list flags.

| Command                                                                          | Description                                                                                                                                                                                                                |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sase workspace list [-j/--json]`                                                | List the registry view for the project, root policy, project key, root path, and primary `#0`.                                                                                                                             |
| `sase workspace path NUM`                                                        | Print the configured checkout path for `NUM` without cloning or preparing it.                                                                                                                                              |
| `sase workspace open NUM -r/--reason REASON [-p/--project PROJECT] [-c/--clean]` | Materialize the checkout if needed, stash or otherwise back up local changes through the VCS provider, clean it, sync it to the provider default parent revision, then print the path. Requires a non-empty `-r/--reason`. |
| `sase workspace cleanup -s/--stale`                                              | Remove unclaimed managed checkouts older than `workspace.cleanup_ttl_days`. `-n/--dry-run` previews.                                                                                                                       |
| `sase workspace repair [-n]`                                                     | Drop registry entries whose checkout is gone; re-materialize missing registered checkouts that still have live RUNNING claims.                                                                                             |
| `sase workspace migrate --to xdg-state [-s/--symlink-transition] [-n]`           | Move existing `<primary>_<num>` adjacent checkouts under the managed `xdg-state` root and register them. Exits non-zero on skipped refusals.                                                                               |
| `sase workspace migrate --finalize`                                              | Remove `<primary>_<num>` transition symlinks once workflows have adapted to the managed paths.                                                                                                                             |

`path` always resolves `#0` to the primary checkout. For other numbers, it prints the configured path without cloning.
Use this command when you only need to inspect the path.

`open` is intentionally more forceful. It materializes the requested checkout, backs up uncommitted local changes
through the normal workspace-preparation path, cleans it, checks out the active VCS provider's default parent revision,
runs the provider's workspace sync hook when available, and then prints the path. For built-in bare-git projects, it
first makes sure the primary checkout has generated SDD guide files. `list` and `path` remain read-only and do not run
SDD initialization. `--clean` is accepted as a compatibility flag for this default behavior. Use a claim-range number
such as `10` when handing a numbered checkout to an external shell, editor, or debugging tool. `#0` is the primary
checkout, and `#1` through `#9` are reserved compatibility numbers rather than good choices for new manual checkouts.
For linked-repo work, `-p/--project` is still the project selector: pass the configured linked repo name there, then the
workspace number as the positional argument.

`cleanup` and `repair` skip workspace `#0` and any workspace number with an active claim. `cleanup --include-shares`
opts workflow-share checkouts into the same cleanup pass.

`migrate --to xdg-state` is opt-in. Existing adjacent checkouts are left in place until the command is invoked. With
`--symlink-transition` it leaves a `<primary>_<num>` symlink at the original adjacent path so legacy tooling that still
walks `..` for siblings keeps working; the canonical checkout lives under the managed root. Migration refuses to
overwrite a real directory at the managed destination — pre-existing managed content is reported and skipped instead of
clobbered. `cleanup --stale` removes both the canonical managed checkout and its transition symlink. Once workflows are
adapted, `migrate --finalize` removes the leftover transition symlinks without touching the canonical checkouts.

## Disabling Plugins

The workspace provider registry loads provider entry points directly. It does not currently consult the resource-plugin
disable switches described in [docs/configuration.md](configuration.md#plugin-system).

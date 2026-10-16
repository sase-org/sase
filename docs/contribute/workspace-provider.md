---
title: Workspace provider internals
description: Provider APIs, hooks, and ownership rules for workspace implementations.
---

# Workspace provider internals

This page documents the workspace provider contract and its core integration points.

## Plugin Architecture

Workspace providers are implemented as [pluggy](https://pluggy.readthedocs.io/) plugins,
following the same pattern as VCS plugins. The core `sase` package bundles the
**BareGitWorkspacePlugin** for local bare-remote git repositories. Additional backends
must be installed in the same Python environment as `sase`:

| Package       | Plugin                   | Description                                     |
| ------------- | ------------------------ | ----------------------------------------------- |
| `sase` (core) | `BareGitWorkspacePlugin` | Bare-git repos (local filesystem remote)        |
| `sase-github` | `GitHubWorkspacePlugin`  | GitHub-hosted repos (PR workflows via `gh` CLI) |

Plugins register themselves via the `sase_workspace` entry point group. The plugin
manager loads all registered plugins and dispatches operations through pluggy hooks.
Most hooks use `firstresult=True` — the first plugin that returns a non-`None` result
wins.

### Hook Specification

All workspace operations are defined in `WorkspaceHookSpec`
(`src/sase/workspace_provider/_hookspec.py`). Each method is prefixed with `ws_` to
namespace them within the pluggy project.

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

Built-in metadata includes `SASE_GIT` for `#git`. Plugin packages can add prefixes such
as `SASE_GH`.

SASE treats `sdd_storage_policy` as authoritative. `in_tree` takes effect immediately,
as it does for the built-in bare-git provider. `separate_repo` requires the provider to
materialize a sidecar before SDD writes or workflow setup can continue. A positive
`.sase/sdd-store.json` record preserves that materialized selection for offline use.
Managed GitHub initialization can record the resolved store as `sidecar_repos`, routing
every configured role and (in schema 3) beads to role-specific linked clones. Schema-2
records keep beads under the plans clone. This is a materialized-store layout, not an
additional provider policy value.

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

For clone-based git workflows, `primary_workspace_dir` is the primary checkout path and
`get_workspace_directory()` derives numbered sibling workspaces from it. Some provider
plugins can leave `primary_workspace_dir` empty and resolve numbered workspaces through
their own helper command.

When `canonical_ref` is set, launch history, replay selections, and prompt MRU entries
use `#<workflow>:<canonical_ref>` instead of the raw user-entered locator; when it is
absent, SASE keeps the matched ref. For example, first-use repository paths or GitHub
owner/repo refs can resolve to a stable SASE project key while still letting the
provider decide the checkout target. `canonical_ref` does not replace `checkout_target`;
providers still decide which branch or revision to check out.

## Hook Reference

### Metadata and Detection

| Hook                       | Returns                    | Description                                  |
| -------------------------- | -------------------------- | -------------------------------------------- |
| `ws_get_workflow_metadata` | `WorkflowMetadata \| None` | Declare this plugin's workflow type metadata |
| `ws_detect_workflow_type`  | `str \| None`              | Detect workflow type from a project file     |
| `ws_get_change_label`      | `str \| None`              | Get the change label (e.g., `"PR"`, `"PR"`)  |
| `ws_get_workspace_name`    | `str \| None`              | Get the workspace/project name for a CWD     |

`ws_get_workflow_metadata` is the only hook that collects results from **all** plugins
(not `firstresult`). This allows the registry to build a complete map of all available
workflow types.

### Reference Resolution and Workflow Setup

| Hook                         | Returns                  | Description                                       |
| ---------------------------- | ------------------------ | ------------------------------------------------- |
| `ws_resolve_ref`             | `ResolvedRef \| None`    | Resolve a `#type:ref` reference to workspace info |
| `ws_setup_workflow`          | `dict[str, str] \| None` | Set up environment variables for a workflow run   |
| `ws_get_workspace_directory` | `str \| None`            | Get or create a workspace directory for a clone   |

### Change Submission and Review

| Hook                                   | Returns                            | Description                                     |
| -------------------------------------- | ---------------------------------- | ----------------------------------------------- |
| `ws_submit`                            | `tuple[bool, str \| None] \| None` | Submit a Patch (merge, push, etc.)              |
| `ws_prepare_mail`                      | `object \| None`                   | Prepare a change for mailing/review             |
| `ws_extract_change_identifier`         | `tuple[str, str] \| None`          | Extract identifier from a PR URL                |
| `ws_supports_reviewer_comments`        | `bool \| None`                     | Check if a PR URL supports reviewer comments    |
| `ws_generate_reviewer_comments_script` | `str \| None`                      | Generate a script to fetch reviewer comments    |
| `ws_generate_submitted_check_script`   | `str \| None`                      | Generate a script to check if a PR is submitted |

### Commit Formatting

| Hook                           | Returns        | Description                                               |
| ------------------------------ | -------------- | --------------------------------------------------------- |
| `ws_format_commit_description` | `bool \| None` | Format a commit description file (add tags, prefix, etc.) |

### Repository Onboarding

The provider-neutral onboarding flows use additive hooks. Providers return `None` when
they do not own the requested `workflow_type`; repository creation never clones or
registers the project, which happens later through the normal reference resolver.

| Hook                            | Returns                       | Description                                                   |
| ------------------------------- | ----------------------------- | ------------------------------------------------------------- |
| `ws_parse_repo_ref`             | `ParsedRepoRef \| None`       | Purely normalize a user-entered repository reference          |
| `ws_list_local_repo_candidates` | `LocalRepoCandidates \| None` | Find bounded local repositories and checkouts                 |
| `ws_probe_repo`                 | `RepoProbe \| None`           | Read-only observation of availability and repository metadata |
| `ws_describe_repo_creation`     | `RepoCreationForm \| None`    | Describe provider-specific creation fields                    |
| `ws_create_repo`                | `RepoCreateResult \| None`    | Create the remote or bare repository only                     |

`ws_parse_repo_ref` must not access the filesystem, network, or subprocesses.
`ws_list_local_repo_candidates` reads local metadata without subprocesses, and
`ws_probe_repo` is bounded and non-interactive. Creation forms identify each option by
its stable `name`; `ws_create_repo` receives those values and returns `created`,
`exists`, or `failed` without deciding whether to adopt an existing repository.

Register an existing repository with `sase project add REF`. The command previews the
provider observation and planned local changes before resolving the repository; its
optional setup step is the human-only marker commit and push. Create a new repository
with `sase project create REF`; `--check` is available to agents, and apply is
human-only unless it runs as an approved `/sase_gate` option or
`SASE_PROJECT_CREATE_BYPASS` holds a reason.

## Registry Functions

The workspace provider package (`sase.workspace_provider`) exports convenience functions
that call through the plugin manager. These are the primary API for consumers:

| Function                              | Description                                     |
| ------------------------------------- | ----------------------------------------------- |
| `clone_external_repo()`               | Clone a repository by provider scheme           |
| `create_repo()`                       | Create a remote or bare repository              |
| `create_sdd_remote()`                 | Create the SDD sidecar remote                   |
| `describe_repo_creation()`            | Describe provider-specific creation fields      |
| `detect_workflow_type()`              | Detect workflow type for a project file         |
| `extract_change_identifier()`         | Extract a change identifier from a message      |
| `format_commit_description()`         | Format a commit description                     |
| `generate_reviewer_comments_script()` | Generate a reviewer-comments script             |
| `generate_submitted_check_script()`   | Generate a submitted-check script               |
| `get_all_workflow_metadata()`         | Get metadata from all registered plugins        |
| `get_change_label()`                  | Get the change label for a project              |
| `get_display_name()`                  | Get display name for a workflow type            |
| `get_display_name_by_vcs()`           | Get display name by VCS provider name           |
| `get_display_name_by_vcs_family()`    | Get display name by VCS family                  |
| `get_embedded_vcs_tag_pattern()`      | Get the embedded VCS tag pattern                |
| `get_external_repo_schemes()`         | Get clone schemes registered by providers       |
| `get_pre_allocated_env_prefix()`      | Get env-var prefix for a workflow type          |
| `get_ref_patterns()`                  | Get all registered ref patterns                 |
| `get_sdd_storage_policy_by_vcs()`     | Get an SDD storage policy declared by VCS       |
| `get_vcs_tag_pattern()`               | Get the VCS tag pattern for a workflow type     |
| `get_workflow_names()`                | Get all registered workflow type names          |
| `get_workspace_directory()`           | Get the directory for a workspace number        |
| `get_workspace_name()`                | Get workspace/project name for a directory      |
| `list_local_repo_candidates()`        | List local repositories and checkouts           |
| `list_ref_namespaces()`               | List owner/namespace candidates                 |
| `list_repo_candidates()`              | List remote repository candidates               |
| `materialize_sdd_store()`             | Materialize an SDD sidecar store                |
| `parse_repo_ref()`                    | Parse a user repository reference               |
| `peek_ref()`                          | Read-only workspace reference lookup            |
| `preflight_sdd_sidecar()`             | Preflight an SDD sidecar remote                 |
| `prepare_mail()`                      | Prepare a change for review                     |
| `probe_repo()`                        | Observe repository availability and metadata    |
| `reset_workflow_metadata_caches()`    | Drop cached workflow metadata                   |
| `resolve_ref()`                       | Resolve a workspace reference                   |
| `submit_patch()`                      | Submit a Patch                                  |
| `supports_reviewer_comments()`        | Whether the provider supports reviewer comments |

## Bare-Git Reference Auto-Initialization

The bundled bare-git provider resolves `#git:<ref>` in four modes:

1. A registered bare-git project shorthand, using `~/.sase/projects/<name>/<name>.sase`
   when it contains `BARE_REPO_DIR` and `WORKSPACE_DIR`.
2. A Patch name found across registered projects.
3. A missing project shorthand with no slash, which initializes a new bare-git project
   using `~/.sase/repos/<name>.git` as the bare repository and `~/projects/git/<name>/`
   as the primary checkout.
4. A bare repository path, deriving the project name from the path basename and creating
   the matching ProjectSpec with that bare path and the default `~/projects/git/<name>/`
   primary checkout path.

The missing-project shorthand is intended for first use from a macro or prompt bar:
`#git:new_tool #!workflow` creates the bare-git project on demand.

An existing ProjectSpec is never treated as a missing bare-git project merely because
`BARE_REPO_DIR` is absent. If the spec belongs to another workspace provider, `#git:`
fails with a provider-mismatch error and points to the matching VCS tag instead of
rewriting the project in place. A genuine bare-git project whose checkout still has a
local-path `origin` can repair a missing `BARE_REPO_DIR` automatically.

The same guard covers names another project already claims. Before a slashless `<ref>`
that has no ProjectSpec directory of its own is treated as a Patch name or a new
project, the resolver checks whether an existing project declares it as its
`PROJECT_NAME` or as an alias. A bare-git owner resolves as that canonical project; any
other owner fails with the provider-mismatch error, so `#git:<github-alias>` points you
to the matching tag (such as `#gh:<github-alias>`) instead of creating a stray bare-git
project. A bare-repository path whose basename is claimed this way resolves the same
way, and bare-git initialization likewise refuses a name another project claims.
`sase doctor`'s `project.name_collisions` check warns when a project's `PROJECT_NAME` or
alias matches another project's directory key, `PROJECT_NAME`, or alias (compared
case-insensitively, disabled projects included), or claims the reserved `home` ref. The
VCS-reference history also removes provider-mismatched alias entries.

`#git:home` is special because it is the default for bare prompts. If the `home`
ProjectSpec is missing, SASE bootstraps a managed empty bare-git project at the default
`home` paths; an existing non-bare-git `home` project receives the same provider guard
as any other project. To point a project at an existing bare repository, use
`#git:<bare-repo-path>`; the path basename becomes the SASE project name, so
`#git:/path/to/home.git` registers the `home` project.

Bare-git projects use in-tree SDD under `sdd/`. SASE creates or refreshes generated SDD
guide files during new project initialization, existing bare-repo registration, and
first `#git` or `sase repo open` materialization. When materialization owns the checkout
setup, SASE commits and pushes only those generated guide paths with an `Initialize SDD`
init commit.

## Known-Project VCS Fallback

SASE also recognizes provider-prefixed VCS refs that target registered project names
even when the corresponding workspace plugin is not available in the current process.
Known projects are discovered from `~/.sase/projects/*/*.sase` (with legacy
`~/.sase/projects/*/*.gp` accepted as a fallback) by reading each `WORKSPACE_DIR:`
entry. For example, if the `sase` project is registered, `+sase #!some/workflow`,
`#gh:sase #!some/workflow`, and the underscore shorthand `#gh_sase #!some/workflow` are
treated as VCS workspace launches rather than ordinary macro references.

Known-project fallback is lifecycle-aware. Launch pickers and broad macro/catalog
discovery include enabled projects only. Legacy `inactive`, `archived`, and `closed`
values normalize to disabled. An explicitly typed ref to a registered disabled project
is treated as intent to resume work: launch preparation writes `PROJECT_STATE: enabled`
before the workspace claim. A checkout cwd or mobile `project` value provides
prompt-resolution context but is not a workspace ref; a bare prompt without one defaults
to `#git:home`. Direct workspace claims that bypass launch preparation still fail
against a disabled ProjectSpec with an enable hint. Use `sase project list --state all`
to inspect disabled projects and `sase project enable <project>` when you want to make
that state change separately.

Configured linked repositories use hidden internal `PROJECT_STATE: sibling` backing
records rather than a project lifecycle state. Agents prepare them through `/sase_repo`.
In a SASE-launched agent run, the audited open records the repo name and kind in run
artifacts and the durable repo-open log; sase's TUI uses the artifact record for
opened-repo context, and the commit finalizer enforces the linked or external repo the
agent explicitly opened.

Non-wait launches allocate the next available numbered workspace for the project and set
the VCS update target to the provider default revision. When registered workspace
metadata provides an env prefix, SASE passes the matching `<PREFIX>_PRE_ALLOCATED`,
`<PREFIX>_WORKSPACE_NUM`, and `<PREFIX>_WORKSPACE_DIR` values into the child process.
Launches that start with a wait directive keep workspace number `0` until the dependency
is ready, then resolve a real workspace during normal runner setup. Before applying the
current launch context, SASE removes inherited `SASE_*_PRE_ALLOCATED`,
`SASE_*_WORKSPACE_NUM`, and `SASE_*_WORKSPACE_DIR` variables so nested or follow-up
launches do not accidentally reuse a stale parent workspace. When a session follow-up's
composed prompt still carries its `#git:` or `#gh:` ref, SASE then supplies fresh
pre-allocation variables for the workspace that successor actually received. The VCS
setup step adopts a numbered claim already owned by its runner instead of allocating a
second checkout, and rebinds a deferred `#0` runner to the real numbered workspace once
setup reports it. A pinned session workspace names the planner's workspace directly.
When it is taken, the launch fails with the occupant named unless
`SASE_AGENT_PINNED_WORKSPACE_FALLBACK=pool` requests relocation to a pool workspace;
relocated children record the real workspace they received.

The matching release step is handoff- and identity-aware. It leaves the claim and
checkout occupant in place when the run has written a pending plan, question, monitor,
gate, or pipe handoff marker. Otherwise it releases only a matching RUNNING claim whose
pid still belongs to the calling runner. Claim release and occupant cleanup are checked
separately: a claim-pid mismatch is a recorded no-op for the claim, and an occupant
record is cleared only when its pid matches the caller.

## Relationship to VCS Provider

The workspace provider and VCS provider are complementary plugin systems:

| Concern                | VCS Provider                            | Workspace Provider                                |
| ---------------------- | --------------------------------------- | ------------------------------------------------- |
| **Scope**              | Low-level VCS commands                  | High-level workspace operations                   |
| **Examples**           | `git commit`, `git diff`, `hg amend`    | Ref resolution, submit, mail prep, workspace dirs |
| **Plugin granularity** | One active plugin per detected VCS type | All plugins registered, firstresult dispatch      |
| **Entry point**        | `sase_vcs`                              | `sase_workspace`                                  |
| **Hook prefix**        | `vcs_`                                  | `ws_`                                             |

A single plugin package (e.g., `sase-github`) typically provides both a VCS plugin and a
workspace plugin.

## Ownership Boundary

SASE-initiated host, runner, and scheduled work never mutates the user's primary
checkout (`#0`, including the legacy `#1` spelling). Automation may read it to resolve
config, remotes, branches, project identity, and sidecar metadata, but every automated
write goes through one of these mechanisms instead:

- **Operational workspace leases** (`sase.workspace_provider.lease`) claim a numbered
  workspace from the unified pool (`#10`+), materialize and prepare its checkout from
  the configured primary remote, and expose a leased `OperationContext`. The lease is
  released exactly once on success, failure, timeout, cancellation, or reboot recovery,
  and acquisition never falls back to the primary checkout. Plan approval, epic
  launches, task launches, and background bead writers (claim acquisition, periodic
  reconciliation, external issue mirroring) all acquire a lease — or reuse an already
  claimed workspace when its store is a separate workspace-local sidecar — rather than
  resolving a canonical primary store for writing. Checkout preparation makes up to
  three `git fetch` attempts in total: it retries transient transport failures
  (connection reset, timeout, DNS) and re-checks an authentication refusal such as
  `Permission denied (publickey)` once after about 10 seconds, before failing the lease;
  see [Service host](../reference/agents/service-host.md#service-host).
- **Reset-and-replay conflict recovery** (`sase.workspace_provider.reset_replay`)
  recovers a stale rebase, merge conflict, or non-fast-forward publication race by
  hard-resetting only a live, leased, machine-owned checkout to its verified upstream
  tip and replaying the idempotent operation from durable inputs. It refuses to touch
  primary `#0`, an unclaimed checkout, or a user-directed/read-only context; remote
  unavailability and lock contention are retried or deferred, never reset.
- **Primary-sidecar auto-sync** (`sase._sidecar_auto_sync`, the `auto_sync` sidecar
  setting) is the one exception that touches a clone reachable from the primary
  checkout: it may fetch and fast-forward an already-materialized sidecar clone — not
  the primary repository itself — and only while that clone is clean, attached, and
  strictly behind its configured remote. Dirty, detached, diverged, remote-mismatched,
  or missing clones are left untouched and reported. See
  [`auto_sync` vs. `auto_clone`](../reference/config/repositories-behavior.md#repos) for
  the config-level distinction; sync runs both from a durable per-project/role hint
  recorded right after a workspace-sidecar publication and from a scheduled backstop
  job.

`sase.workspace_provider.ownership.authorize_store_mutation` and the `writable_*`
helpers are the shared enforcement point close to every store mutation seam, so a new
background caller cannot bypass the boundary by importing a lower-level commit helper
directly. Explicit foreground commands the user runs in their own chosen cwd — including
an agent's own git operations inside its already-claimed workspace — remain unaffected;
the boundary applies to SASE resolving and writing to _primary_ on the user's behalf.

## Related

- [Contribute](index.md) — the section hub.

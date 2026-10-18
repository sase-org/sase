---
title: "Repository configuration behavior"
description: "Repository lists, dispatch, VCS selection, and completion settings."
---

# Repository configuration behavior

Repository lists, dispatch, VCS selection, and completion settings.

## repos

Declares linked and sidecar repositories related to a project. Git linked-repo worktrees
are eligible for commit-finalizer checks at their resolved `workspace_dir`. Agents use
`/sase_repo` to prepare them; its audited `sase repo open` command records manually
opened linked workspaces in run artifacts for sase's TUI context and appends a durable
audit event. SASE materializes a hidden sibling-state ProjectSpec for the linked repo
when needed. Entries can live in user config or a project-local `sase/sase.yml`; local
entries are resolved relative to the project's primary workspace directory.

Repository inventory and linked-repo resolution load the project-local configuration
from the selected project's primary checkout, even when invoked from another checkout or
from the TUI. The bundled, plugin, user, and selected overlay layers also apply. For
example, querying project B from project A includes shared user-configured links and B's
local links; A's local links do not enter B's inventory. Relative repository paths
resolve against the selected project's primary checkout.

Linked repositories are lazy by default. Set `auto_clone: true` for a repository that
every launched agent needs; SASE materializes and prepares those entries before
execution. Lazy entries remain available through `sase repo open`, but their
per-repository `*_DIR` environment variables are not exported until the clone exists.
Repositories with `auto_clone: true` are omitted from generated agent instructions
because agents do not need to open them manually.

`auto_clone` and `auto_sync` are independent settings on a sidecar entry. `auto_clone`
controls whether a numbered workspace materializes its own clone of the sidecar before
each agent launch; that clone is disposable and owned by the launched agent's workspace.
`auto_sync` instead opts the _primary checkout's_ already-materialized sidecar clone
into conservative background convergence: SASE fetches and fast-forwards it only while
it is clean, attached, and non-diverged, and never rebases, commits, hard-resets, or
removes user state. A dirty, detached, diverged, remote-mismatched, or
not-yet-materialized primary sidecar clone is left untouched and reported rather than
repaired. Managed projects enable `auto_sync` for the generated `plans`, `beads`, and
`research` entries; custom roles default to `false` and opt in with the same property.
See [Ownership Boundary](../../contribute/workspace-provider.md#ownership-boundary) for
the underlying primary/leased distinction and how sync is scheduled.

`repos.sidecar` is a two-bucket mapping keyed by role: `builtin` holds overrides of the
reserved `plans`, `beads`, `agents`, `attachments`, and `attachments-private` roles, and
`custom` holds user-declared document sidecars such as `research`. The map key _is_ the
role, so an entry never carries a `name` field and a role cannot be declared twice in
one bucket. Because both buckets are mappings, a later config layer merges into an
inherited entry per key — a project-local `custom: {research: {disabled: true}}` opts
out of a global `research` sidecar. A sequence of entries carrying `name` is ignored;
run `sase doctor` to see which bucket each such entry belongs in.

Sidecar entries use their role key as the primary CLI lookup key. Ordinary roles use
`sase/repos/<role>` as their workspace clone directory. Their repository defaults to
`<project>--<role>` in the primary repository's GitHub organization; `repo` can pin a
bare slug or `owner/repo`. An explicit unpinned entry uses that project-local derivation
even when a persisted SDD store record names a different repository. Configured sidecars
appear in `sase repo list` even before cloning and can be opened by role name or
repository slug. Enabled ordinary sidecars that are not auto-cloned also appear by
repository slug in generated agent instruction files, where their `description` tells
agents when to open them with `/sase_repo`. Set `disabled: true` in a later config layer
to suppress a matching global entry or implicit fallback; disabled and auto-cloned
sidecars are omitted from generated instructions.

The roles `plans`, `beads`, `agents`, `attachments`, and `attachments-private` are
reserved and are configured under `repos.sidecar.builtin`. `plans` owns canonical plans,
`beads` owns the event store, `agents` is the hidden machine-level publication store
plus the canonical prompt and prompt-artifact archive, `attachments` is the hidden bare
store for public bead attachment bytes, and `attachments-private` is the hidden bare
store for private bead attachment bytes. Every other enabled role lives under
`repos.sidecar.custom` and is a document sidecar: a `<YYYYMM>/*.md` corpus whose kind
label is the role name. `attachments` and `attachments-private` are not document roles,
so neither can be declared under `custom`. Document roles receive clone/store
resolution, `sase repo path <role>`, doctor validation, commit routing,
`SASE_SDD_<ROLE>_DIR`, plan-search visibility, and an sase's TUI Plans kind. `research`
is simply the default-seeded document role; only its illustrated README/directory-map
preset is name-specific.

The `agents` role is intrinsically hidden from agent workflows. It never appears in
generated memory, launch metadata, linked-repository environment variables, or a
workspace's `sase/repos/` tree, even if an override sets `auto_clone: true`. It remains
visible to users as a `sidecar` row in `sase repo list`, and `sase repo path agents` or
`sase repo open agents -r "<reason>"` explicitly accesses the one machine-level clone at
`~/.sase/projects/<project_key>/repos/agents`. The derived or pinned repository slug is
also accepted by those commands.

`attachments-private` is also hidden from agent instructions. Managed projects receive
an implicit private `<project>--attachments-private` entry unless configuration names
that role or `default_linked_repos` is false. Its clone is a bare partial repository
(`git clone --bare --filter=blob:none`) at
`~/.sase/projects/<project_key>/repos/attachments-private`, with no worktree and no
README. `sase repo list` shows the role, and `sase repo path attachments-private` prints
that path. `auto_clone: true` does not put a copy in a workspace's `sase/repos/` tree.
Resolved visibility is always `private`: a `visibility: public` override is rewritten to
`private`, and preflight rejects a provider that would create the remote with another
visibility. SASE does not verify the visibility of a remote that already exists. Opt out
of sidecar setup with `repos.sidecar.builtin.attachments-private.disabled: true`.
Attachment commands still use an existing local clone even when that role is disabled;
`-L/--local-only` keeps an individual attachment on this machine. When available, the
git store takes objects up to `bead.attachments.git_max_bytes`; see
[Attachments](../work-units/bead-attachments.md#attachments).

The `beads` role does not default to `auto_clone: true`: the beads sidecar materializes
on demand, in `sase bead` and in the agent-launch bead claim, instead of during
workspace preparation. It is unconditionally omitted from generated agent instructions
regardless of its `auto_clone` setting, the same way `agents` is, because agents reach
bead state through `sase bead` rather than `/sase_repo`. Unlike `agents`, it otherwise
behaves like an ordinary reserved sidecar: it appears in `sase repo list` and resolves
through `sase repo path beads` or `sase repo open beads -r "<reason>"`.

The workspace provider owns sidecar transport. GitHub sidecars use canonical SSH origins
on the primary repository's GitHub host (`git@host:owner/repo.git`, or
`ssh://git@host:port/owner/repo.git` when a port is configured). Read-only store
resolution converts a GitHub HTTPS record to that exact SSH form in memory, so
inventory, launch-time auto-cloning, and on-demand materialization are safe immediately
without rewriting the durable record. Matching retained HTTPS clones keep their checkout
and local state while SASE rewrites `origin` in place. Any HTTP(S) sidecar remote that
cannot be derived from consistent GitHub provider, host, and repository metadata fails
materialization before Git runs. Rerun `sase repo init` to persist the migrated record;
it is not required to make a launch safe.

Managed projects (`is_sase_managed: true`) receive deterministic `<project>--plans`
(`auto_clone: true`), `<project>--beads` (`auto_clone: false`), `<project>--agents`
(`auto_clone: false`, public visibility unless the primary repository is private or
unverifiable, which forces every sidecar private), and private
`<project>--attachments-private` entries when no matching explicit sidecar is
configured. Research is config-declared per project and defaults to
`<owner>/<project>--research`; `sase repo init` writes the plans and research entries. A
project-local `agents` or `attachments-private` entry replaces that implicit entry. For
`agents`, use `disabled: true` to opt out or `visibility: private` to retain a private
remote. For `attachments-private`, use `disabled: true` to opt out; visibility stays
private. Project-local `default_linked_repos: false` suppresses those implicit
managed-project entries. `sase repo init` can create and seed the agents remote only
after its separate default-no consent prompt. Successful agent commit/PR workflows
publish the committing hood, while `sase agent sync` publishes every locally
commit-eligible hood through the stable machine-level clone. See
[Agent Hood Synchronization](../agents/index.md) before enabling a public remote.

`linked_repos` and `sibling_repos` are accepted as aliases for `repos.linked`.
`repos.linked` takes precedence when the same name is defined. See
[Configuration migration notes](../upgrading/configuration.md#repository-configuration).

A linked entry may declare `revision_pin`, a pin file relative to the primary checkout
root that holds that repo's pushed SHA (for example `sase-core-revision.txt`). The path
must be relative and stay inside the checkout. Absolute paths, `~`, drive-letter paths,
and `..` that would leave the checkout are rejected when the config is read. A relative
path that still leaves through a symlinked parent directory or a symlinked pin file is
not followed: `sase doctor` reports that escape, and the commit finalizer skips the pin
write with `pin-escapes-checkout`. `sase doctor` also flags a pin file that is missing
or does not hold a 40-character hex SHA. It resolves the pin from the current working
directory, so run it from the primary checkout. When one accepted declaration commits
both the primary and a pinned sibling, the host commits the sibling first and writes its
pushed SHA into the pin file before the primary commit. A skipped pin records the reason
and does not fail the run.

```yaml
github_orgs:
  - sase-org
repos:
  linked:
    - name: core
      path: ../sase-core
      description: Shared backend/domain behavior used by SASE frontends.
      auto_clone: true
  sidecar:
    builtin:
      plans:
        auto_clone: true
        ref:
          use: builtin@plan
      agents:
        visibility: private
    custom:
      research:
        description: Durable SASE research reports and generated media.
        visibility: public
        ref:
          icon: ∴
          inventory:
            globs: ["reports/**/*.md", "!drafts/**"]
```

[Generated reference for `repos`](repositories.md#repos)

Every enabled document sidecar exposes one compact `@<kind>:<path>` reference. Plans use
the built-in `plan` provider, and `sase repo init` records `ref: {use: builtin@plan}`.
Other document roles default to their role name, the sidecar pointer format
`the {repo_relative_path} file in the {sidecar_role} sidecar repo`, and `**/*.md`
inventory even when `ref` is omitted. Explicit custom path-bound providers may opt into
`the {checkout_path} file`.

`ref.use` selects a declarative provider installed through the `sase_artifact_refs`
plugin entry-point group, qualified as `<plugin>@<id>` where `<plugin>` is the literal
`builtin` or the installed distribution name. Any sibling keys deep-merge over that
provider's base spec. A cloned sidecar does not install its provider: when `use` names
an unavailable provider or omits its plugin prefix, the role's reference policy is
disabled and `sase doctor -C config.repos` reports how to fix it. Authors may omit `use`
and provide the inline fields in the table instead.

`ref.macro` is invalid. `ref.filters.path_globs` is accepted as an alias for
`ref.inventory.globs` and emits a warning; new configuration must use `inventory.globs`.
The `beads` and `agents` sidecars are entity-backed rather than document inventories, so
document filters do not apply to them. See
[Artifact References](../artifact-references.md) for canonical prompt forms and
project-context rules.

Workspace numbers `0` and `1` use the linked repo's primary checkout. Higher workspace
numbers use `<host_workspace>/sase/repos/linked/<linked_repo>`, naturally namespaced by
host project and workspace number. Agent and workflow launch preparation atomically
removes the numbered checkout's entire `<host_workspace>/sase/repos/` tree. The required
`plans` sidecar is then cloned directly from the canonical SSH or local remote resolved
from its recorded metadata; other linked repositories and sidecars remain lazy unless
configured with `auto_clone: true`. GitHub HTTPS metadata is normalized before the clone
command is built, and unresolved HTTP(S) metadata stops launch setup before Git
executes. The hidden `agents` sidecar is excluded from this clone mapping and always
resolves every registered workspace number to
`~/.sase/projects/<project_key>/repos/agents`. Agents materialize ordinary lazy entries
on demand through `/sase_repo`. `sase repo init` manages the tracked `/sase/repos/`
ignore rule, while SASE also installs the rule in `.git/info/exclude` before
materialization. SASE passes resolved metadata for all entries and exports
per-repository paths only for materialized entries. See
[Environment variables](../environment-variables.md#vcs-provider) for the per-repository
variables and their compatibility aliases.

Source: `src/sase/linked_repos.py`, `src/sase/agent/launch_spawn.py`

### External repositories

External repositories are per-task repos that are not part of the host project's
configured inventory. They require no configuration entry. `sase repo open` resolves
them after inventory names in two forms:

- Another registered SASE project name opens that project's primary repo from its local
  checkout, without network access, under `sase/repos/external/projects/<project>`.
- `gh:owner/repo`, or the `owner/repo` shorthand, clones through the installed GitHub
  workspace provider under `sase/repos/external/gh/<owner>/<repo>`.

Successful external opens are idempotent, audited, and included in `sase repo list`,
commit-finalizer enforcement, sase's TUI file and commit deltas, and revert. Agents must
use `/sase_repo` before reading or modifying any external repo and must use the path
printed by the skill rather than locating or cloning the repo themselves. External repos
are workspace-local and do not create project registry records.

## dispatch

Configures remote-machine discovery, enrollment records, gateway deadlines, and the
local federation worker. Ordinary config loading is pure: it reads and validates this
section but never discovers peers or contacts a gateway. Use `sase machine init`,
`discover`, or `status` for explicit network work. See the
[Remote Dispatch Runbook](../integrations/remote-dispatch.md) for the supported setup
flow.

```yaml
dispatch:
  providers:
    builtin@https:
      enabled: true
    builtin@tailnet:
      enabled: true
  machines: {}
  discovery:
    enabled_providers: [builtin@tailnet]
  request_timeout_seconds: 5
  status_cache_seconds: 60
  federation_worker:
    enabled: true
    command: ""
    sase_home: ""
    run_root: ""
    socket_path: ""
    idle_timeout_seconds: 300
    startup_timeout_seconds: 5
    request_timeout_seconds: 5
    max_frame_bytes: 1048576
  remote_hosts: []
```

[Generated reference for `dispatch`](repositories.md#dispatch)

Machine aliases are 1–64 characters, must start with an ASCII letter or digit, and may
otherwise contain ASCII letters, digits, `_`, `.`, and `-`. Each machine record stores a
dispatch provider ref, HTTPS endpoint, opaque credential reference, and pinned
`sase_inst_v1_...` installation identity. Optional `ssh_target` stores the SSH
destination used for terminal handoffs; when omitted it defaults to the alias at use
time. Optional fields select `gateway`, `tunnel`, or `direct` connection kind; TLS trust
mode (`system_roots`, `pinned_ca`, or `pinned_server_name`); and quarantine state.
Tokens do not belong in YAML: `credential_ref` points into the protected local
credential store.

Enrollment commands write those records and keep the installation pin authoritative. A
quarantined alias cannot receive launches or lifecycle mutations until repaired.

Source: `src/sase/dispatch/config.py`, `src/sase/dispatch/models.py`,
`src/sase/config/sase.schema.json`

<a id="vcsprovider"></a>

## vcs_provider

Configures the version control system backend. See
[docs/reference/vcs/providers.md](../vcs/providers.md) for the full VCS provider
reference including per-command behavior, Git/Mercurial details, and troubleshooting.

GitHub Enterprise host configuration (`github_hosts`) is owned by the `sase-github`
plugin; see its
[GitHub Enterprise setup walkthrough](https://github.com/sase-org/sase-github/blob/master/docs/configuration.md#github-enterprise-setup).

```yaml
vcs_provider:
  provider: auto # "git", "hg", or "auto" (default: "auto")
  workspace_root: ~/workspace # optional workspace root directory
  default_hooks: # optional list overriding built-in default hooks
    - "!$my_presubmit"
    - "$my_lint"
  pr_tags: # optional key-value tags appended to PR commit messages (keys are rendered SASE_-prefixed, e.g. SASE_BUG)
    BUG: "b/12345"
  use_project_pr_prefix: false # prepend [<project>] to PR titles (default: false)
```

[Generated reference for `vcs_provider`](repositories.md#vcs_provider)

When `default_hooks` is not set, plugins may provide their own defaults via
`default_config.yml` (for example, Mercurial-specific hooks from a provider plugin). The
core `sase` package has no built-in default hooks.

When `use_project_pr_prefix` is `true`, a `[<project>] ` prefix is prepended to PR
titles (GitHub) or PR descriptions (Mercurial) without polluting the Patch DESCRIPTION
or git commit message. The prefix is automatically stripped when reading descriptions
back.

Source: `src/sase/vcs_provider/config.py`, `src/sase/ace/hooks/defaults.py`

<a id="vcsrepocompletion"></a>

## vcs_repo_completion

Configures repository-name completion inside VCS workflow refs such as `#gh:owner/`.

```yaml
vcs_repo_completion:
  enabled: true
  cache_ttl_seconds: 600
  max_repos: 200
```

[Generated reference for `vcs_repo_completion`](repositories.md#vcs_repo_completion)

When disabled, sase's TUI does not detect repository-completion triggers, and the editor
helper bridge returns an empty catalog. Repository candidates are listed through
workspace-provider hooks, so provider-specific authentication and network requirements
belong to the installed plugin. For GitHub, the `sase-github` plugin uses the `gh` CLI
and can return private repositories visible to the authenticated user.

Source: `src/sase/default_config.yml`, `src/sase/macro/vcs_repo_completion.py`
<a id="vcsrefcompletion"></a>

## vcs_ref_completion

Configures project, Patch, and namespace completion at the root of VCS workflow refs
such as `#gh:` and `#git:`.

```yaml
vcs_ref_completion:
  enabled: true
```

[Generated reference for `vcs_ref_completion`](repositories.md#vcs_ref_completion)

When disabled, sase's TUI does not detect VCS ref-root completion triggers and the
materialized macro LSP VCS catalog omits namespace rows. Project and Patch candidates
come from local ProjectSpecs; provider namespace rows come from fast local
workspace-provider hooks.

Source: `src/sase/default_config.yml`, `src/sase/macro/vcs_ref_completion.py`

## Related

- [Repositories and version control configuration](repositories.md) — generated keys and
  defaults.
- [Workspace configuration](workspace-behavior.md) — workspace settings.

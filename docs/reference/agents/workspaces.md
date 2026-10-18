---
title: Workspaces
description: Look up workspace storage, repository commands, and workspace commands.
---

# Workspaces

This page describes numbered workspaces and the commands that inspect and manage them.

The **workspace provider layer** is an abstraction that handles workspace-level
operations that vary across VCS hosting environments. While the
[VCS provider](../vcs/index.md) handles low-level version control commands (commit,
diff, checkout), the workspace provider handles higher-level concerns: workflow type
detection, reference resolution (for example `#git:repo` or `#gh:org/repo`), change
submission, mail preparation, and workspace directory management.

A **workspace reference** is a prompt prefix such as `+sase`, `#git:sase`, `#gh:sase`,
or a ref registered by another workspace provider. It tells SASE which project and
workspace should be used before the rest of the prompt or workflow runs. The
`+<project>` [project tag](../macros/reference-syntax.md#project-tags) is the default
spelling for a known project; the `#` forms remain for Patches, `owner/repo`, `@agent`,
paren forms, and creating new projects.

SASE keeps three related concepts distinct:

- A **project** is a named unit of work with a ProjectSpec at
  `~/.sase/projects/<name>/<name>.sase`; it is enabled unless explicitly disabled.
- A **repo** is a primary project repository, a configured sidecar (such as `plans` or
  `designs`), or a configured linked repo.
- A **workspace** is a numbered clone of a project's primary repo, tracked in that
  project's workspace `registry.json`.

Workspace directories are not repos. Linked-repo and sidecar clones materialized inside
a numbered workspace are repo checkouts, not additional workspaces.

For everyday use, put `+<project>` in the agent's launch prompt and let SASE allocate an
isolated workspace. The agent opens linked or external repositories through
`sase repo open` and works in the path it prints. Before its normal final response, the
root agent uses the `/sase_final` skill to submit a declaration; the host then runs the
configured finalizers, including committing changes under the default configuration.
Numbered workspaces are reused. Before evicting leftover linked and external clones,
SASE attempts to rescue local work to a durable recovery directory; it does not publish
those clones during eviction, and a failed rescue does not stop eviction. See
[workspace maintenance](#workspace-maintenance) for recovery and retention details, and
[Monitors](../automation/monitors.md) for running a command from an opened repository.

## Workspace Directory Layout

SASE resolves every workspace through a per-project store rather than by
string-appending `_<num>` to the primary checkout path. The store assigns workspaces
stable numeric identities and chooses a physical path according to the configured root
policy.

### Numeric Identity

| Range     | Meaning                                                                                                                                            |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `#0`      | Primary checkout from ProjectSpec `WORKSPACE_DIR`. Also used as the placeholder for deferred launches.                                             |
| `#1`–`#9` | Reserved. The allocator never hands these out, but tests and call sites that pass them by hand remain supported through the compatibility wrapper. |
| `#10`+    | Claim-allocated numbered workspaces. New agents allocate from this unified pool starting at `#10`.                                                 |

The current allocator uses one shared pool for every claim source;
`claim_next_axe_workspace()`, launch executor pre-claims, and `axe` deferred claims all
start at `#10` unless a caller passes explicit `min_workspace` / `max_workspace` bounds.
`get_first_available_axe_workspace()` is a read-only selector and is not used to occupy
a slot.

User-facing checkout suffixes are `<project>_<num>` regardless of root policy. The
primary checkout retains its `WORKSPACE_DIR` path with no suffix.

### Root Policy

The physical location of managed checkouts is controlled by `workspace.root` (see
[`docs/reference/config/workspace-behavior.md`](../config/workspace-behavior.md#workspace))
and the `SASE_WORKSPACE_ROOT` environment override:

| Value         | Layout                                                                                                                                                                                                                                 |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `xdg-state`   | Default. Platform state root plus namespace: `$XDG_STATE_HOME/sase/workspaces/<project_key>/<project>_<num>/` on Linux, `~/Library/Application Support/sase/workspaces/...` on macOS, `%LOCALAPPDATA%\sase\workspaces\...` on Windows. |
| `adjacent`    | Adjacent `<primary>_<num>/` siblings of the primary checkout. Explicit opt-in to keep this layout.                                                                                                                                     |
| absolute path | Treat the configured path as the managed-root base and create `<project_key>/<project>_<num>/` checkouts under it.                                                                                                                     |

`SASE_WORKSPACE_ROOT` overrides `workspace.root` for the process and is interpreted as
an explicit managed root directory, with the project namespace appended underneath it.
Use an absolute path for predictable behavior. It is the recommended override for
ephemeral test runs and CI sandboxes.

The `project_key` namespace under managed roots is derived from a single Git remote slug
when available, otherwise from the primary-path basename plus a short hash so two
projects with the same basename do not collide. An explicit `workspace.project_key` in
config wins over the heuristic.

Each managed checkout writes a `.sase/checkout.json` marker recording the project name,
project key, workspace number, primary workspace path, and the registry path. CWD-based
project inference (used by `sase bead`, the file panel, and similar callers) reads the
nearest marker first and only falls back to sibling-pattern scanning for adjacent
layouts.

Configured linked repositories for a numbered checkout are cloned beneath that host
checkout at `sase/repos/linked/<linked_repo>`. Before every agent or workflow launch,
SASE atomically removes the numbered checkout's entire `sase/repos/` tree and deletes it
in the background. Sidecars configured with `auto_clone: true` (normally `plans`) are
then cloned directly from their recorded authoritative remotes. GitHub HTTPS records are
resolved to canonical SSH before the clone command runs; already-valid SSH and local
remotes are preserved, while any remaining HTTP(S) metadata fails launch preparation
before Git executes. The normalization is read-only, so rerunning `sase repo init`
persists the migrated record but is not required for a safe launch. Other linked
repositories and ordinary document sidecars remain lazy unless configured for automatic
cloning and can be materialized on demand through `/sase_repo`. External repos are also
cloned on demand below `sase/repos/external/projects/` or
`sase/repos/external/<scheme>/`. SASE protects the whole tree immediately with the
per-clone `/sase/repos/` exclude rule; run `sase repo init` to add the same rule durably
to the tracked root `.gitignore`. Use `--check` to report drift, `--diff` to preview it,
or `--no-commit` to write the rule without the normal project commit/push sequence.

### Registry

For non-adjacent roots SASE maintains a per-project registry alongside the checkouts.
The registry tracks every workspace the store owns — including primary `#0` — and
records `checkout_dir`, `materialization`, `role`, `pinned`, `created_at`, and
`last_used_at`. Registry writes are atomic. `sase workspace repair` is the canonical way
to reconcile the registry against the filesystem after a manual delete or a partially
completed migration. Adjacent checkouts keep sibling behavior and normally do not write
a persistent registry; `cleanup` and `repair` treat a missing registry as "nothing
managed here" rather than an error.

<a id="adjacent-compatibility-and-migration"></a> Moved to
[Workspace upgrades](../upgrading/workspaces.md#adjacent-compatibility-and-migration).

### Backup, Container, And Network-Storage Caveats

- **Backups.** With `adjacent`, every numbered checkout sits inside the user's normal
  source tree and gets captured by Borg/Restic/Syncthing/BTRFS snapshots. Managed roots
  move execution state out of the primary backup surface; if you want crashed-agent
  working trees included, add `~/.local/state/sase/workspaces/` (or the platform
  equivalent) to your backup profile explicitly.
- **BTRFS / ZFS snapshots.** Once canonical checkouts live outside `~/projects`, a
  snapshot of that tree does not freeze every workspace atomically. Snapshot the state
  root alongside the source tree if atomicity matters.
- **NFS / network home directories.** If `$HOME` is on NFS and your source tree is on
  local SSD, switching to `xdg-state` can move workspaces to slow storage. Set
  `workspace.root` to an absolute path on the fast volume, or keep `adjacent`.
- **Containers / devcontainers / Toolbx / Distrobox.** Tools that bind-mount
  `~/projects` into a container will not see managed checkouts under `~/.local/state`.
  Either add a second mount for the managed root or keep `workspace.root: adjacent` for
  the containerized project.
- **Recursive search performance.** `rg`, `fd`, IDE workspace-wide search and similar
  tools fan out N times across adjacent siblings. Managed roots avoid this by default.

<a id="post-default-migration-guidance"></a> Moved to
[Workspace upgrades](../upgrading/workspaces.md#post-default-migration-guidance).

## `sase repo` CLI

Repository commands treat the repo as the object and the workspace as context.
`sase repo open` accepts a host-project inventory name, another registered SASE project
name, or an external provider ref such as `gh:owner/repo` (with `owner/repo` as GitHub
shorthand). Run it from a managed checkout to infer both the host project and workspace,
or pass `-p/--project` and `-w/--workspace` explicitly. Successful opens print the
prepared path, write the agent artifact markers used by sase's TUI and the commit
finalizer, and append the project's durable repo-open audit event. Agents use this
surface through `/sase_repo` and treat the printed path as authoritative.

Provider refs are resolved against the host project's configured repositories before
SASE materializes an external checkout. For example, if a configured linked repo's
GitHub origin is `git@github.com:sase-org/sase-core.git`, then
`sase repo open gh:sase-org/sase-core` and `sase repo open sase-org/sase-core` reuse
that configured checkout, so build commands and host commit hooks see the same files. If
more than one configured repo has the same verified remote, the command reports an
ambiguity and asks for an explicit configured name or path. If the current workspace
already contains an external checkout for the same provider identity, the provider alias
reports a collision naming both checkouts; recover or intentionally select the existing
checkout before using the alias. Exact configured names remain valid even while such a
duplicate external checkout exists.

See the generated [repo CLI reference](../cli/repo.md) for the command inventory and
exact options.

Bare `sase repo` defaults to `sase repo list`. `sase repo list --all` includes enabled
and disabled projects at primary workspace context, while `sase repo log` remains
project-scoped.

The JSON inventory's `declared_by` field identifies a linked repository's configuration
source: `project` for the selected project's local config, or `user` for the shared
default, plugin, user, and overlay layers. Other repository kinds have no declaration
source. Selecting a different project also selects that project's local configuration;
see [Repository configuration behavior](../config/repositories-behavior.md#repos).

## `sase workspace` CLI

The `sase workspace` command surface inspects numbered workspace paths and maintains the
per-project registry used by non-adjacent roots. All subcommands accept
`-p/--project NAME` to override the project; without it, the project is inferred from
the current directory via the nearest managed-checkout marker, the workspace provider
hook, and finally a scan of `~/.sase/projects/`. With no subcommand, `sase workspace`
defaults to `sase workspace list` with default options. `sase workspace list --all`
switches from one inferred/selected project to the shared inventory across enabled and
disabled projects; `--json` emits the same inventory model as structured data.

See the generated [workspace CLI reference](../cli/workspace.md) for the command
inventory and exact options.

The all-project inventory includes disabled projects only when `--all` is explicit. One
corrupt or unreadable registry is returned as an isolated issue and does not suppress
rows from other projects. Registry entries whose checkout has been deleted remain
visible with `exists: false`; preview reconciliation with
`sase workspace repair -p <project> -n`.

By default, numbered managed Git checkouts share the primary checkout's object database
through Git alternates. New managed clones are created with the shared object store
enabled, the primary checkout is protected with local `gc.pruneExpire=never`, and
borrowers disable automatic Git maintenance that would silently copy objects back into
private packs. The dependency is explicit: deleting or moving the primary checkout can
break borrowers until `sase workspace repair` repoints their alternates to the current
primary object directory. The alternate policy itself (path resolution, SASE-owned
versus foreign entries, and rewrite plans) is decided by the Rust core; Python runs the
Git commands under the project lock.

Workspace preparation never rewrites an existing checkout's object dependency. A usable
alternate is kept as-is, even when it still points at an older primary object directory;
only `sase workspace repair` repoints it. A broken SASE borrower (for example one whose
`git status` fails because the borrowed objects are gone) makes preparation fail with a
pointer to `sase workspace repair`, leaving the checkout and any uncommitted work intact
instead of deleting and recloning it. This holds whether or not sharing is enabled.
Preview the fix with `sase workspace repair -n`.

When preparation fails, the error names the workspace, the failing step (`clean`,
`checkout`, `sync`, `sidecar-protection`, or `agents-sync-guard`), and the underlying
git or guard message, in the form
`Failed to prepare workspace <dir> during <step>: <reason>`; `sase workspace open`
prints that message to stderr. On an agent's first launch attempt, the run log records
it as `Workspace preparation failed: …` (or
`Linked repo '<name>' workspace preparation failed: …`), while the error the agent run
reports omits the step: `Failed to prepare workspace <dir>: <reason>`.

`sase workspace compact -n` previews eligible existing checkouts and reports local
object bytes without changing Git config or objects. Before/after/reclaimed bytes count
only exclusively owned object files (`st_nlink == 1`), so objects a checkout shares with
the primary by hardlink are never reported as reclaimed. Pass one or more workspace
numbers to restrict the operation to those registered checkouts, and `-j/--json` for a
per-checkout result object (status, reason, and before/after/reclaimed bytes). Apply
mode skips the primary, missing or non-Git paths, RUNNING claims, live occupant records,
dirty checkouts, unexpected alternates, and broken alternates that SASE does not own. It
repeats those checks under the project lock before writing the SASE-owned alternate
while preserving foreign alternate entries, runs a local-only repack, and requires
`git fsck --connectivity-only` to pass before reporting success. `sase disk reap` runs
this same command (`sase workspace compact --json`, plus `-n` unless `--apply` is given)
for each enabled project as one of its owner cleanup steps; the hourly `disk_pressure`
job does not.

Set `workspace.share_git_objects: false` to opt out for future materializations. With
sharing disabled, `sase workspace repair` safely dissociates existing SASE-managed
borrowers by first repointing them to the current primary when needed, copying reachable
objects into a local pack, then removing only the SASE-owned alternate after
connectivity can be proven. Repair does not claim or overwrite non-SASE alternate
entries, including files that contain the primary object directory alongside foreign
entries. With sharing enabled, repair repoints stale or broken SASE-owned alternates,
leaves unexpected foreign alternates alone, and reports a broken non-SASE alternate as a
failure. Either way, alternate repair skips checkouts with a live RUNNING claim, a live
occupant record, or uncommitted changes.

`sase doctor -C workspace.occupancy_conflicts` is the read-only occupancy check. It
reads every project's RUNNING field and each checkout's occupant record, then reports
duplicate workspace-number claims, one live pid claiming multiple numbered workspaces, a
live claim whose occupant names a different live pid, and occupant records with no
matching claim. Conflicts include the last workspace-claim ledger mutation and caller
tag when one exists. The check never auto-repairs; use `sase workspace repair -n` to
preview registry/checkout reconciliation separately.

`path` always resolves `#0` to the primary checkout. For other numbers, it prints the
configured path without cloning. Use this command when you only need to inspect the
path.

The hidden `sase workspace open NUM -r REASON` compatibility command is omitted from
help. It remains available to callers that need its forceful preparation behavior;
`sase repo open` is the documented command for opening a repository. It requires a
non-empty `-r/--reason`, records the same repo-open audit event as `sase repo open`,
materializes the requested checkout, backs up uncommitted local changes through the
normal workspace-preparation path, cleans it, checks out the active VCS provider's
default parent revision, runs the provider's workspace sync hook when available, and
then prints the path. For built-in bare-git projects, it first makes sure the primary
checkout has generated SDD guide files. `list` and `path` remain read-only and do not
run SDD initialization. `--clean` is accepted as a compatibility flag for this default
behavior. Use a claim-range number such as `10` when handing a numbered checkout to an
external shell, editor, or debugging tool. `#0` is the primary checkout, and `#1`
through `#9` are reserved compatibility numbers rather than good choices for new manual
checkouts. For linked-repo work, `-p/--project` is still the project selector: pass the
configured linked repo name there, then the workspace number as the positional argument.

### Workspace maintenance

`cleanup` and `repair` skip workspace `#0` and any workspace number with an active
claim. `cleanup --include-shares` opts workflow-share checkouts into the same cleanup
pass.

Preparing a numbered workspace (`#2` and above) for a launch evicts everything under its
`sase/repos/` directory — the sidecar and linked-repo clones — which would otherwise
carry stale state into the new run. Leftover state from an earlier run never fails a new
launch: preparation attempts to publish each sidecar once, then to rescue unpublished
work to the durable rescue store outside the workspace
(`~/.sase/projects/<project>/rescue/<YYYYMM>/`, falling back to `~/.sase/rescue/`).
Linked and external clones use the same rescue store, with a bundle of local-only
commits and a worktree patch; they are never published during eviction. Rescue is
best-effort: if it fails, eviction can still discard local work. Tags never trigger a
rescue on their own: they are bundled only as labels for local-only commits that a
branch, stash, recovery ref, or detached HEAD is already being rescued for, so upstream
release tags in third-party clones produce no rescue entries. A tag whose commit nothing
else references is not rescued. Eviction always proceeds. Each rescue pins a
`refs/sase/recovery/` ref inside the store's own repository, writes a `manifest.json`
with copy-pasteable restore commands
(`git fetch <bundle> 'refs/*:refs/sase/rescued/<stamp>/*'`,
`git apply --index <patch>`), and sends one inbox notification naming the rescue dir.
Entries older than 30 days (7 days for quarantined whole-clone copies) are reaped. See
[Publication Verification](../work-units/bead-storage.md#publication-verification) for
the invariant this protects and how to restore rescued commits by hand.

Checkout preparation for the same numbered workspaces (`#2` and above) also heals the
checkout itself instead of failing on leftover git state. Launches, launch retries, and
retained linked-repo clones use this path; the primary checkout (`#0`, or reserved
compatibility number `#1`), home mode, and `sase workspace open` keep the fail-closed
behavior. The ladder, printed to the run log as `Self-heal: ...` lines, is:

1. Rescue first: an interrupted rebase, `am`, merge, cherry-pick, revert, or bisect,
   unmerged paths, or a detached HEAD holding orphan commits is bundled into the rescue
   store before anything is touched. A plain dirty worktree needs no rescue entry; the
   usual clean stash remains its backup.
2. Abort every in-progress git operation, then clean. If the stash backup itself fails,
   the worktree is rescued and the checkout is hard-reset and cleaned instead.
3. Check out the target. A failed checkout is retried with `-f`; for the default branch
   a still-failing checkout recreates the branch from its remote tip.
4. When the target is the default branch, fetch, then rebase onto its remote tip (a
   Patch-branch target skips this step). A fetch failure stays a hard failure. A
   conflicting rebase is aborted, the local-only commits are pinned under
   `refs/sase/recovery/` and bundled into the rescue store, and the branch is hard-reset
   to the remote tip.
5. Verify the postcondition: no in-progress operations, no unmerged paths, HEAD attached
   to the expected branch, and a clean worktree.

When in-place healing still fails at the abort, clean, checkout, sync, or verify step
(fetch and network failures are never eligible), the workspace is re-created once: the
main checkout and every `sase/repos/<role>` clone are rescued, the checkout is moved
aside for background deletion, and a fresh one is materialized from the primary (the run
log says the workspace `could not be repaired in place`). A failing linked-repo clone is
re-created the same way without touching its parent checkout. When preparation still
fails — a fetch failure, or a second failure after re-creation — the run ends with the
`setup_workspace_failed` outcome and the workspace is released rather than held as a
visible failed run, since the agent never started and anything valuable was rescued.

`migrate --to xdg-state` is opt-in. Existing adjacent checkouts are left in place until
the command is invoked. With `--symlink-transition` it leaves a `<primary>_<num>`
symlink at the original adjacent path so tools that walk `..` for siblings keep working;
the canonical checkout lives under the managed root. Migration refuses to overwrite a
real directory at the managed destination — pre-existing managed content is reported and
skipped instead of clobbered. `cleanup --stale` removes both the canonical managed
checkout and its transition symlink. Once workflows are adapted, `migrate --finalize`
removes the leftover transition symlinks without touching the canonical checkouts.

## Disabling Plugins

The workspace provider registry loads provider entry points directly. It does not
currently consult the resource-plugin disable switches described in
[docs/reference/environment-variables.md](../environment-variables.md#plugin-system).

## Related

- [Agents and workspaces](index.md) — the section hub.

## `sase repo`

Bare `sase repo` defaults to `sase repo list`. The command family inventories primary,
sidecar, linked, and opened external repositories, prepares a selected repo inside one
workspace context, and exposes the durable audit history of successful opens.

`sase repo list` defaults to the current project and infers both the project and
workspace context from cwd. Primary repos come from ProjectSpecs, sidecars from
`repos.sidecar` plus SDD store records, linked repos from resolved `repos.linked`
(including compatibility aliases), and external repos from materialized workspace-local
clones; a sidecar wins when the same checkout is also auto-injected as linked. The Rich
table reports whether each repo is cloned in the selected workspace plus the number of
registered workspaces containing it. External rows use the canonical project name or
provider ref such as `gh:pallets/click`. Hidden `agents` rows remain visible and report
the same stable machine-level path for every registered workspace context.

<a id="cli-options-14"></a> Moved to [sase repo](workspaces.md#sase-repo).

<a id="command-behavior-8"></a> Moved to [Workspaces](workspaces.md#command-behavior-8).

## Command behavior {#command-behavior-8}

`--all` and `--project` are mutually exclusive. JSON records retain source, description,
`auto_clone`, environment, and SDD-storage metadata while making `path` and `exists`
describe the selected workspace context.

`sase repo open REPO -r "<reason>"` resolves `REPO` in three tiers: a host-project
inventory name, another registered SASE project name, then an external provider ref
(`gh:owner/repo` or `owner/repo` GitHub shorthand). It materializes and prepares the
repo, prints only its path to stdout, records the per-run artifact markers used by
sase's TUI and the commit finalizer, and appends an event to
`~/.sase/projects/<project>/repo_opens.jsonl`. Run it inside a managed checkout to infer
the host project and workspace. Reopening a valid external clone preserves its current
contents and records a new open event.

When a supported provider ref or another registered SASE project corresponds to a
configured linked repo in the host project, `sase repo open` opens the linked checkout
instead of cloning or reopening an external copy. Stdout remains exactly the linked
path; stderr explains the redirect and suggests the configured linked name for next
time. If a previous external checkout of the same repo exists, it is left untouched and
reported as a warning so any work already there remains visible.

| Open argument / flag | Description                                                                             |
| -------------------- | --------------------------------------------------------------------------------------- |
| `REPO`               | Inventory name, registered project name, `gh:owner/repo`, `owner/repo`, or record path. |
| `-p, --project`      | Select the host project instead of inferring it from cwd.                               |
| `-r, --reason`       | Required non-empty audit reason.                                                        |
| `-w, --workspace`    | Select the host workspace number instead of inferring it from cwd.                      |

When two inventory records share a name or slug, `sase repo open` refuses rather than
guessing and lists each candidate as `<kind> '<name>' (<path>)`. To pick one, re-run the
command with that candidate's path as `REPO`, copied exactly as printed: a record path
is matched literally, ahead of any name or slug, so it selects that record even when its
name collides with another's. This is a disambiguator, not a general "open any
directory" mode — a path that matches no primary, sidecar, or linked record falls
through to the usual name and provider-ref tiers and fails there.

`sase repo log` renders a project-scoped summary and per-repo rollup of durable open
events. Repo, agent, or workspace filters add agent and event drill-down panels; an
event ID prefix shows one complete event. `--json` returns the same filtered data
deterministically.

| Log flag          | Description                                               |
| ----------------- | --------------------------------------------------------- |
| `-a, --agent`     | Filter by agent name or interactive user.                 |
| `-i, --id`        | Show one event by exact ID or unambiguous ID prefix.      |
| `-j, --json`      | Emit deterministic structured output.                     |
| `-p, --project`   | Select the host project instead of inferring it from cwd. |
| `-r, --repo`      | Filter by repository name.                                |
| `-w, --workspace` | Filter by host workspace number.                          |

## `sase repo init`

`sase repo init` declares the managed plans, beads, and default `research` document
sidecar, initializes every enabled configured sidecar, and ensures the project root
`.gitignore` contains `/sase/repos/`, protecting host-scoped repository clones durably.
`-c, --check` reports drift without writing, `-d, --diff` renders proposed full-file
diffs, and `-C, --no-commit` writes project config and ignore changes without the normal
project commit/pull/push sequence. `sase init repo` is an alias; bare `sase init` and
`sase validate` include the same check for Git projects.

## `sase workspace`

Workspace commands inspect and maintain the managed checkout registry for the inferred
project, or for the project named by `-p/--project`. With no subcommand,
`sase workspace` defaults to `sase workspace list` with default options. Use
`sase workspace list -p <project>`, `sase workspace list --all`, or
`sase workspace list --json` when passing list flags.

<a id="cli-options-28"></a> Moved to [sase workspace](workspaces.md#sase-workspace).

<a id="command-behavior-17"></a> Moved to
[Workspaces](workspaces.md#command-behavior-17).

## Command behavior {#command-behavior-17}

For built-in bare-git projects, `sase repo open` may initialize generated SDD guide
files in the primary checkout before materializing a numbered workspace.
`sase workspace list` and `sase workspace path` remain read-only and do not run SDD
initialization.

# Agent Hood Synchronization

SASE publishes deterministic project-scoped agent-hood snapshots through each managed project's hidden `agents` sidecar.
The machine-level clone lives under `~/.sase/projects/<project-key>/repos/agents`; it is never exposed to launched
agents or copied into numbered workspaces.

## Privacy and configuration

One publication includes every locally owned active, waiting, terminal, failed, and dismissed run in the committing
agent's complete top-level hood. Active prompts can therefore appear before a transcript exists; later syncs can refresh
the stable run with terminal state, commits, or a readable chat. Portable metadata and family/clan relationships are
included as well. Creating or pushing the sidecar publishes that data to everyone who can read the configured remote.

Before running `sase repo init`, set the intrinsic `agents` sidecar's `visibility: private` when that scope must remain
restricted. Set `disabled: true` to opt out entirely. Synchronization never creates a remote and cannot bypass the
explicit consent requested by repository initialization.

Every publisher needs a complete selected `id.username` / `id.machine_name` owner identity. Local artifacts keep bare
semantic names such as `foo.bar--code`; v2 transport uses the canonical global name
`<username>.<machine_name>.foo.bar--code`. The exact owner manifest is the only shared authority file that publisher
mutates. Run `sase config init` to create or migrate the identity; see
[owner identity and machine overlays](configuration.md#owner-identity).

## Strict v2 layout

```text
README.md
schema.json
users/<username>/README.md
users/<username>/machines/<machine>/README.md
users/<username>/machines/<machine>/manifest.json
users/<username>/machines/<machine>/hoods/<hood>/README.md
users/<username>/machines/<machine>/hoods/<hood>/snapshot.json
agents/<global-name>/
  README.md
  meta.json
  state.json
  prompt.md
  commits.json
  chat.md                 # only when readable
families/<global-family>.md
```

Owner manifests map each hood to the snapshot digest and its complete referenced-file set. Snapshot and per-run JSON is
strictly versioned, canonically encoded, size/count bounded, and content-addressed with SHA-256. Names and paths are
validated as single components, and every relationship/container batch passes through the Rust identity facade before
publication.

The allowlist excludes PIDs, workspace numbers, credentials, absolute paths, checkout paths, and other host-local
execution state. A publication is fully built and validated before rollback-safe atomic writes begin, so malformed input
cannot leave a half-rendered hood.

Existing top-level v1 `manifest.json` and `agents/<machine-qualified-name>` bundles are left untouched. Sync can still
read those records for compatibility, but it no longer creates or refreshes v1 transport data.

## Scope and reconciliation

Targeted publication refreshes exactly the committing agent's complete top-level hood. Full reconciliation publishes
every locally owned project hood with at least one primary-repository commit association. Commit-less plan members,
active siblings, failed/waiting runs, dismissed archives, and structural family/clan containers are included when they
belong to that hood.

After an agent-backed commit or pull-request operation records its first durable result marker, the commit workflow
resolves the project's agents target. When that target is available, SASE records an outbox request for the exact hood
before trying to publish it; the attempt also drains older queued publications for the project. A failure after the
request is queued does not roll back the primary VCS result, and the entry remains for a later commit or full sync. If
the target cannot be resolved, no outbox entry is guaranteed; a later full sync still publishes every locally eligible
hood. See [runtime provenance and publication](commit_workflows.md#cli-inputs-and-internal-payload).

Published runs that are temporarily missing from local inventory are retained. New terminal state, commits, prompt data,
and chat refresh the same stable run; absence does not create an implicit deletion or tombstone. Identical inputs
produce byte-identical files and a no-op publication.

After each pull/rebase, SASE rebuilds root, user, machine, hood, family, and agent Markdown from every validated owner
manifest. Family member links use stable `member-<role>` anchors; solo links target the corresponding agent README.
Because owners mutate disjoint authority files, a bounded non-fast-forward retry can pull a competing owner, recompute
the shared views, and converge without overwriting either snapshot.

## Importing shared history

A mutating sync also imports shared v2 hoods into local, project-scoped history. Each owner hood is an independent
package. Before writing local state, SASE validates its owner manifest, snapshot and referenced-file digests, bounded
paths and payloads, portable metadata, relationship graph, and permanent-name claims. A malformed owner or hood is
reported as quarantined and is not imported; validation can continue for unrelated packages.

A valid remote run becomes a terminal historical artifact and dismissed-agent bundle, not a live process. Source
`active`, `waiting`, and `stopped` states appear locally as `STOPPED`; a source failure remains `FAILED`; other terminal
states appear as `DONE`. Available prompts, chats, commits, restart metadata, and family/clan/wait/retry relationships
are retained. A sequential family is also recorded as one stable saved-family group, so the normal ACE family-revival
flow can relaunch it. Refreshing that family preserves its existing revival timestamp and count.

Imports are transactional per hood. SASE prepares the complete local artifact, dismissed bundle, saved-family record,
and permanent-name claims as a staged transaction, then applies and finalizes it under a project import lock. Loaders
ignore a transaction until it is complete. A later v2 import pass discards an interrupted prepared transaction or
finishes one that had begun applying. Re-importing the same snapshot is a no-op; a new digest refreshes the existing
imported records. When the package describes the current owner and SASE can match a local run by durable ID or primary
commit evidence, it treats that run as already observed instead of creating a duplicate.

## Commands and status

Run a mutating reconciliation for all enabled projects:

```bash
sase agent sync
sase agent sync -p project-alias -p another-project
```

The repository transaction acquires a bounded lock, pulls with rebase, imports validated shared v2 history and optional
legacy v1 bundles, performs v2 publication for locally owned hoods, stages the complete shared payload, commits with the
full owner identity, and pushes. A non-fast-forward rejection triggers one pull/recompute/commit/push retry. Conflicted
rebases are aborted and reported; a failure in one project does not prevent the others from running.

Use `--json` to audit the complete schema-version-2 result. In addition to the legacy `integrated`, `refreshed`,
`exported`, and `export_refreshed` fields, each project reports `hoods_imported`, `hoods_import_refreshed`,
`hoods_import_unchanged`, `hoods_quarantined`, `families_imported`, and `runs_imported`, plus the corresponding v2
publication counts and diagnostics. The default table is intentionally compact: `IMPORTED` is the changed legacy-v1
import count, `V1` is the changed legacy-v1 publication count, and `HOODS` / `RUNS` report v2 publication—not v2 import—
totals. ACE's tracked-task lines likewise do not currently include the v2 import fields, so a project that only imports
or refreshes v2 history can be summarized there as `current`; use the CLI's `--json` result to audit those imports.

Status checks maintain `~/.sase/agents_sync/status_snapshot.json` and, after a refreshed check, validated incoming-hood
cache objects:

```bash
sase agent sync --check
sase agent sync --check --refresh
sase agent sync --check --json
```

Neither check mode imports agent history, publishes local hoods, changes the sidecar worktree, commits, or pushes.
Without `--refresh`, `--check` does not run Git or scan local agent artifacts: it resolves the current project
inventory, reconciles persisted incoming-hood entries against import receipts, and rewrites the status snapshot with the
previously recorded Git and unexported-agent counts. Those counts can therefore be absent or stale.

`--check --refresh` is the networked status path. It fetches remote refs, validates the fetched agents commit, stores
independently valid foreign hoods in the local incoming cache, and recomputes ahead, behind, and legacy unexported-agent
counts. `--refresh` is rejected unless `--check` is also present. Use `--json` to inspect cached `pending_updates`,
quarantine diagnostics, and the fetched ref and commit.

## ACE integration

ACE performs a networked status check after first paint and then checks enabled agents repositories periodically. When
the cached status says a project is behind, ahead, has a nonzero legacy unexported-agent count, or is otherwise not
ready, the top bar shows a green `⇅ N` badge. Hover it for per-project details or click it to run the same
all-enabled-project sync as a tracked background task. The `,U` comprehensive update preview includes an **Agents
repos** section and synchronizes every represented enabled project after its agent-CLI and SASE/core/plugin legs.
Lifecycle-disabled projects are excluded from this all-project inventory rather than displayed as skipped.

Configure that status loop under `ace.agents_sync`. By default, ACE reconciles cached entries and receipts every 10
minutes and, once at least 30 minutes have elapsed, performs the remote-fetching recomputation on the next status tick.
It shows the indicator. The immediate post-sync recheck is also cache-only, so a badge based on previously recorded
ahead, behind, or unexported counts can remain visible until the next remote recomputation. See
[ACE agents-sync configuration](configuration.md#aceagents_sync).

## Recovery

- A busy lock is a benign skip; retry after the active sync finishes.
- A missing sidecar reports `not_created`; run `sase repo init` interactively if you intend to publish this scope.
- A malformed legacy v1 manifest is quarantined and skipped with a diagnostic. A malformed v2 owner manifest, snapshot,
  or referenced digest is quarantined from import; full v2 publication still validates all shared authority and may fail
  that project's reconciliation rather than overwrite corrupt data.
- An interrupted v2 local import stays invisible until complete. A subsequent v2 import pass performs journal recovery;
  in the normal case, rerunning a mutating sync supplies that pass. Use `--json` to inspect recovery or quarantine
  diagnostics.
- A push or fetch failure leaves local agent history intact. Fix credentials/connectivity and retry.
- A rebase conflict is aborted before the command returns. Resolve unexpected state in the hidden clone, then rerun
  `sase agent sync`.

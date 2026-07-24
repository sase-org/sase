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

After a successful commit or pull-request operation records its first durable result marker, the commit workflow runs
targeted publication for that exact hood. Publication failure does not roll back the primary VCS result: SASE queues a
project-scoped outbox entry for a later commit or full sync. See
[runtime provenance and publication](commit_workflows.md#cli-inputs-and-internal-payload).

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

Imports are transactional per hood. SASE stages the complete local artifact, archive, saved-family, and registry update
behind a project lock and makes loaders ignore an incomplete transaction. A later mutating sync discards an interrupted
prepared transaction or finishes one that had begun applying. Re-importing the same snapshot is a no-op; a new digest
refreshes the existing imported records. When the package describes the current owner and SASE can prove that the local
run already exists from its durable ID or commit evidence, it observes that run instead of creating a duplicate.

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
publication counts and diagnostics. The default table is intentionally compact: `IMPORTED` and `V1` are the legacy
import/export totals, while `HOODS` and `RUNS` are v2 publication totals.

Status checks use an atomic snapshot under `~/.sase/agents_sync/`:

```bash
sase agent sync --check
sase agent sync --check --refresh
sase agent sync --check --json
```

`--check` never imports, publishes, commits, or pushes. It always revalidates local git and unexported-agent facts; a
fresh cached snapshot avoids a fetch, while a missing or stale snapshot refreshes remote refs first. `--refresh` forces
that fetch regardless of cache age.

## ACE integration

ACE checks enabled agents repositories after first paint and then periodically. When any project is behind, ahead, has a
nonzero legacy unexported-agent count, or is otherwise not ready, the top bar shows a green `⇅ N` badge. Hover it for
per-project details or click it to run the same all-enabled-project sync as a tracked background task. The `,U`
comprehensive update preview includes an **Agents repos** section and synchronizes every enabled agents repository after
its agent-CLI and SASE/core/plugin legs; disabled repositories remain visible as skipped.

Configure that status loop under `ace.agents_sync`. The defaults revalidate local/cached status every 10 minutes, permit
a remote-fetching recomputation every 30 minutes, and show the indicator. See
[ACE agents-sync configuration](configuration.md#aceagents_sync).

## Recovery

- A busy lock is a benign skip; retry after the active sync finishes.
- A missing sidecar reports `not_created`; run `sase repo init` interactively if you intend to publish this scope.
- A malformed legacy v1 manifest is quarantined and skipped with a diagnostic. A malformed v2 owner manifest, snapshot,
  or referenced digest is quarantined from import; full v2 publication still validates all shared authority and may fail
  that project's reconciliation rather than overwrite corrupt data.
- An interrupted v2 local import stays invisible until complete. Rerun a mutating sync to invoke journal recovery; use
  `--json` to inspect any recovery or quarantine diagnostics.
- A push or fetch failure leaves local agent history intact. Fix credentials/connectivity and retry.
- A rebase conflict is aborted before the command returns. Resolve unexpected state in the hidden clone, then rerun
  `sase agent sync`.

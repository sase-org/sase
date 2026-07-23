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

Published runs that are temporarily missing from local inventory are retained. New terminal state, commits, prompt data,
and chat refresh the same stable run; absence does not create an implicit deletion or tombstone. Identical inputs
produce byte-identical files and a no-op publication.

After each pull/rebase, SASE rebuilds root, user, machine, hood, family, and agent Markdown from every validated owner
manifest. Family member links use stable `member-<role>` anchors; solo links target the corresponding agent README.
Because owners mutate disjoint authority files, a bounded non-fast-forward retry can pull a competing owner, recompute
the shared views, and converge without overwriting either snapshot.

## Commands and status

Run a mutating reconciliation for all enabled projects:

```bash
sase agent sync
sase agent sync -p project-alias -p another-project
```

The transaction acquires a bounded per-repository lock, pulls with rebase, reads optional legacy v1 imports, performs v2
full reconciliation, stages the complete v2 payload, commits with the full owner identity, and pushes. A
non-fast-forward rejection triggers one pull/recompute/commit/push retry. Conflicted rebases are aborted and reported; a
failure in one project does not prevent the others from running.

JSON and table outcomes report additive v2 hood, family, and run publication counts while retaining the legacy
integration/export fields with their original meanings.

Status checks use an atomic snapshot under `~/.sase/agents_sync/`:

```bash
sase agent sync --check
sase agent sync --check --refresh
sase agent sync --check --json
```

## Recovery

- A busy lock is a benign skip; retry after the active sync finishes.
- A missing sidecar reports `not_created`; run `sase repo init` interactively if you intend to publish this scope.
- A corrupt v1 manifest, owner manifest, snapshot, or referenced digest stops that project's sync rather than being
  overwritten.
- A push or fetch failure leaves local agent history intact. Fix credentials/connectivity and retry.
- A rebase conflict is aborted before the command returns. Resolve unexpected state in the hidden clone, then rerun
  `sase agent sync`.

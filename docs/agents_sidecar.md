# Completed Agent Synchronization

SASE can exchange completed, commit-associated agents through each managed project's hidden `agents` sidecar. The
machine-level clone lives under `~/.sase/projects/<project-key>/repos/agents`; it is never exposed to launched agents or
copied into numbered workspaces.

## Privacy and configuration

An agents sidecar contains full chat transcripts—including prompts and responses—portable display metadata, and commit
associations. Creating or pushing it therefore publishes agent data to everyone who can read the configured remote.
Before running `sase repo init`, set the intrinsic `agents` sidecar's `visibility: private` when that data must remain
restricted. Set `disabled: true` to opt out entirely. Synchronization never creates a remote and cannot bypass the
explicit consent requested by repo initialization.

Every participating machine needs a configured `machine_name`. The machine hood is part of each durable agent name, such
as `athena.worker`, so independently created names remain distinct. Run `sase config init` to select or create the
machine identity; see [machine_name and machine overlays](configuration.md#machine_name) for how the identity is stored
and layered. A machine is authoritative for bundles in its own hood: pulled copies from the same machine are not
imported over local artifacts, and a later local export replaces the transport copy when its commits or portable
metadata change.

## Portable bundle layout

The sidecar uses a versioned manifest and one directory per qualified name:

```text
manifest.json
agents/
  athena.worker/
    meta.json
    commits.json
    chat.md
```

`meta.json` is an allowlisted projection. It excludes PIDs, workspace numbers, checkout paths, chat/output paths, and
other machine-local absolute state. `commits.json` contains stable SHA, subject, and committed-time records. `chat.md`
is the exact transcript. The manifest advertises a SHA-256 digest over canonical metadata and commits plus the exact
chat bytes. Unsupported schemas, unsafe paths, identity mismatches, or digest failures stop that project's integration
without partially importing the corrupt bundle.

Foreign bundles are reconstructed as normal terminal `ace-run` artifacts and standard sharded chat files. Their exact
qualified names are claimed in the durable registry, so `sase agent list`, `sase chats`, name lookup, and ACE scans see
them like local history. Provenance and digest markers distinguish imports from locally owned artifacts.

## Commands and status

Run a mutating synchronization for all enabled projects:

```bash
sase agent sync
sase agent sync -p project-alias -p another-project
```

The transaction acquires a bounded per-repository lock, pulls with rebase, integrates foreign bundles, exports local
bundles, commits only `manifest.json` and `agents/`, and pushes. A non-fast-forward rejection triggers one
pull/recompute/commit/push retry. Conflicted rebases are aborted and reported; a failure in one project does not prevent
the others from running.

Status checks use an atomic snapshot under `~/.sase/agents_sync/`. A fresh snapshot is revalidated from local refs and
terminal artifact markers without network access. A stale snapshot is recomputed; `--refresh` explicitly forces the
selected fetches:

```bash
sase agent sync --check
sase agent sync --check --refresh
sase agent sync --check --json
```

Status reports ahead, behind, and unexported-agent counts together with missing clones/upstreams, disabled sidecars,
configuration errors, and last fetch time.

## Recovery

- A busy lock is a benign skip; retry after the active sync finishes.
- A missing sidecar reports `not_created`; run `sase repo init` interactively if you intend to publish agent data.
- A corrupt manifest or bundle is not overwritten automatically. Repair or restore the sidecar data, then rerun sync.
- A push or fetch failure leaves local agent history intact. Fix credentials/connectivity and retry.
- A rebase conflict is aborted before the command returns. Resolve unexpected repository state in the hidden clone, then
  rerun `sase agent sync`.

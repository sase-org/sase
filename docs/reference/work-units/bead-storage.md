---
title: Bead storage
description:
  The bead store layout, event log, synchronization, and checkout source of truth.
---

# Bead storage

This page describes where bead data lives and how stores stay synchronized.

## Storage

### Directory Structure

When the workspace provider declares in-tree storage, as the built-in `bare_git`
provider does:

```
sdd/beads/
  config.json           # Configuration (issue prefix, counter, owner)
  events/
    manifest.json       # Event-store schema and migration metadata
    streams/
      <root-id>.jsonl   # Canonical append-only event stream
  issues.jsonl          # On-demand export (gitignored; regenerate with `sase bead export`)
  beads.db              # Mutation flock (gitignored; never a cache)
```

Providerless local storage and single-sidecar storage use `.sase/sdd/beads/` with the
same structure. Local storage uses the primary workspace; every sidecar layout uses the
active workspace clone and records provider/remote metadata in the primary workspace's
`.sase/sdd-store.json`.

Split sidecar storage puts bead state in its own `<owner>/<repo>--beads` repository,
materialized on demand and checked out at `<workspace>/sase/repos/beads`. That
repository keeps the store **at its root** rather than under a `beads/` subdirectory, so
`config.json`, `metadata.json`, `issues.jsonl`, and `events/` sit beside the generated
`README.md`, `assets/`, `.gitignore`, and generated `pages/`. A split project that has
not been migrated yet still keeps bead state at `beads/` in the root of its auto-cloned
`--plans` repository; the `.sase/sdd-store.json` record decides which, and only a record
that names a `beads` sidecar (schema version 3) resolves to the dedicated repository.
See [SDD Storage](../../contribute/sdd-storage.md) for the record format and the
adoption transaction that performs the move.

Isolating bead state this way gives it its own git history, its own cooperative write
lock, and its own repository-health preflight, so hot bead writes avoid serializing
behind plan writes and a wedged bead rebase cannot block plan commits or epic approval.

Normal bead commands read and write one store for the active checkout. The exception is
a full bead ID that the active store does not hold: it routes to the owning enabled
project's store, as described in [Bead ID Arguments](beads.md#bead-id-arguments). In
in-tree mode, canonical bead state lives in the current checkout's `sdd/beads/events/**`
event store plus `sdd/beads/config.json`. Providerless local commands route to the
primary workspace's `.sase/sdd/beads/` store. Sidecar-policy commands first materialize
the provider store, then route to the active workspace clone so an agent in workspace
`#N` writes its matching `.sase/sdd/` checkout, its `sase/repos/beads/` clone, or its
`sase/repos/plans/beads/` directory. If the event store is absent, reads fall back to
`issues.jsonl`. Numbered sibling workspaces and stores from other layouts are not merged
into normal `sase bead` reads.

`sase bead` clones the beads sidecar on demand. When the store record names one and
`sase/repos/beads` is missing or its origin does not match the recorded remote, the
command materializes the clone before serving the request—reads included, since a read
cannot be served from a clone that does not exist. If the clone cannot be made usable,
the command fails with an error naming the repository and its remote. Projects whose
record has no beads sidecar clone nothing extra.

### Event Log + Compatibility Projections

Rust owns the bead storage/query/mutation path. The append-only event streams are the
canonical git-portable state. `issues.jsonl` is an on-demand export regenerated from
those streams (never committed), and `beads.db` is only the mutation flock, never a
cache.

- **Writes** append canonical Rust events. Event stores never rewrite `issues.jsonl` on
  the per-mutation path; `sase bead export -o <path>` regenerates it on demand (default:
  the store's `issues.jsonl`), and `sase bead doctor --fix-projection` regenerates the
  local untracked copy. Stores without `events/` keep writing the tracked projection.
  `beads.db` is touched only as the cooperative write lock.
- **Reads** prefer `events/manifest.json` plus `events/streams/*.jsonl`, falling back to
  `issues.jsonl` only when no event store is present.
- **Read model.** Hot reads are served from a versioned SQLite read model under the
  clone's git dir (`<git-dir>/sase/bead-read-model/<key>.sqlite`, WAL). A constant-cost
  freshness token (streams-directory `mtime`/`inode` plus manifest and config
  signatures) decides whether the cache serves; a full stat sweep runs whenever the
  token changes, on every write, at least every 60 s, and on demand. Any schema,
  reducer, or crate version mismatch drops and rebuilds the cache, and any cache error
  falls back to plain replay. When the sweep finds changes, the cache applies only the
  appended bytes after each stream's stored length instead of rebuilding, as long as
  every changed stream is a pure append, no stream vanished, the manifest only grew by
  stream additions, the parsed config is unchanged, and every new event sorts after the
  stored merge frontier; any precondition failure rebuilds from a full replay.
  `sase bead doctor` prints a cache status line (location, size, generation, last sweep,
  serve/tail/rebuild outcome counts, last refresh and why), and
  `sase bead doctor --verify-cache` compares the cache against a forced full replay and
  reports drift.
- **History** replays those same streams in projection order; `sase bead history <id>`
  makes every recorded field revision readable without changing canonical state.
- **Fresh clones** read directly from the tracked event streams and can rebuild the
  compatibility mirrors on demand.
- **Dependency removals** are recorded as `dependency_removed` events. During merged
  replay, a remove sorts after an add with the same timestamp, so add-then-remove
  deterministically leaves the edge absent.
- **Closed intervals** start with the first close after a bead becomes closed. Later
  close events in the same interval are kept in the log but ignored by the projection,
  so duplicate closes cannot move `closed_at` or erase a close reason. Reopening or
  otherwise moving out of `closed` ends the interval and archives its close metadata as
  a [close-history](bead-triage.md#close-history) record instead of discarding it.
- **Notes are a structured, append-only log**, not a free-text blob. `note_appended`
  events store only the new entry text; the reducer builds a timestamped, attributed
  record from the event's own metadata, so concurrent note appends merge as separate
  records instead of replacing each other. `sase bead note --edit`/`--remove` record
  their own events and stamp an `edited_at`/`edited_by` marker rather than mutating the
  original record in place; a retraction stays visible in `sase bead history`. The
  `issue_updated { notes }` events (written before this log existed) remain immutable
  whole-field replacements in the stream; on replay their blob is parsed back into
  individually timestamped and attributed records instead of one opaque string.

The `.gitignore` excludes the local `beads.db*` flock files and the `issues.jsonl`
on-demand export. The event store and `config.json` are tracked in git.

### Sealed Segments (Gated Design)

"Archived" is logical today: the read model never re-parses unchanged closed history.
The physical sealed archive below is **not built**. It waits behind measured triggers,
and `sase bead doctor` reports each trigger as `OK` with its current value or `WARN`
with a pointer back here:

- **Hot stream files** warn above 10,000 files in `events/streams/`.
- **Full stat sweep** warns above 50 ms for the read-model sweep pass.
- **Store working tree** warns above ~250 MiB.

The thresholds are core constants (`SEAL_WATCH_HOT_STREAM_FILES_WARN`,
`SEAL_WATCH_SWEEP_MS_WARN`, `SEAL_WATCH_TREE_BYTES_WARN`), computed in Rust and rendered
by doctor, so every frontend reports the same numbers.

When a trigger fires, the gated build seals fully closed root lineages that have been
quiet for at least 30 days and have no live dependents, claims, or pending outbox
entries. Sealed streams move verbatim with `git mv` into `events/sealed/<YYYY-MM>/`,
recorded in a SHA-256 manifest plus a sealed index. Thawing replays an overlay stream
while the reducer de-duplicates by `event_id`; the integrity guard and conflict resolver
compare hot plus sealed; every seal commit carries a parity proof proving the sealed
read matches the pre-seal replay. Compressed bundles (zstd) exist only as off-repo
backups, never as canonical state.

Two triggers are not measurable and stay judgment calls: clone complaints that partial
clones cannot fix, and parity proving itself becoming infeasible.

### Sync Mechanism

`sase bead sync` stages the bead state in the owning git repo, including `events/**` and
`config.json` (`issues.jsonl` is git-ignored and never staged). For stores without
`events/` it first regenerates the tracked projection. The export contains one JSON
object per line, sorted by issue ID for clean diffs; regenerate it any time with
`sase bead export`.

When both stores exist, the event store wins. Manual edits to `issues.jsonl` do not
change command output unless the event store is absent.

#### Publication Verification

Agents work in numbered workspace clones that are eventually discarded. A bead mutation
that is committed but never pushed therefore does not merely arrive late — it is
destroyed. Committing is not sufficient on its own, because the configured push policy
can be asynchronous, queued, or aimed at a different checkout than the one holding the
commit.

So every bead CLI mutation that creates a commit runs a verification pass after the
normal push policy: it resolves the bead store's own git root, and if that root has a
tracking upstream and still carries unpushed canonical bead commits, it forces one
synchronous push against the checkout holding them and re-verifies. If commits remain
unpublished the command **fails** with an operator diagnostic naming the unpublished
commit count, the store path and repository, the latest managed sync log, and a literal
`git -C <repo> push` remediation:

```text
ERROR: <mutation> was committed locally but NOT published.
  unpublished bead commit(s): 1
  bead store: …/sase/repos/plans/beads
  store repository: …/sase/repos/plans
  latest managed sync log: …
  This mutation exists only in this checkout. It is invisible to everyone else and is destroyed if this workspace is
  evicted.
  Remediation: git -C … push
```

A store with nothing of its own to publish to is reported as not applicable and never
fails the command: no git root, no tracking upstream, an [in-tree](#directory-structure)
layout, or a store this checkout may only read (one discovered through a checkout-local
`.sase/sdd-store.json` record, which refuses mutations outright). `--no-push` skips the
check along with the push it verifies. The check is also defensive about itself: a
verification that raises is logged and ignored rather than converting an otherwise
healthy mutation into a failure.

Because verifying a close by reading the local store cannot distinguish a published
close from one that will die with the workspace, agent-facing instructions point at the
close command's own exit status and this diagnostic rather than at a follow-up
`sase bead show`.

Two other surfaces enforce the same invariant:

- **The commit finalizer** commits leftover bead state as a safety net, then runs the
  same verification against the store it committed to. Unpublished state fails the run
  through `finalizer_result.json`, carrying the full diagnostic instead of reporting
  success. The failure is raised at the finalizer's return points, so the agent's own
  commit passes still run first — aborting earlier would strand uncommitted code in the
  workspace in order to report a bead problem.
- **Launch-time workspace preparation** rescues and evicts a numbered workspace (`#2`
  and above) whose sidecar bead-store clones hold unpublished canonical commits. It
  publishes synchronously first (one attempt per store per launch, with a bounded wait
  for a busy sync worker); anything still unpublished is rescued to the durable rescue
  store outside the workspace — a git bundle of the local-only commits, a binary
  worktree patch, and a `manifest.json` with restore commands
  (`git fetch <bundle> 'refs/*:refs/sase/rescued/<stamp>/*'`,
  `git apply --index <patch>`) — plus a recovery ref under `refs/sase/recovery/` in the
  store's own repository, and exactly one inbox notification. Eviction then proceeds; a
  launch never fails because of leftover state. The guard understands the sidecar
  layouts — `sase/repos/beads` for a split clone root and `sase/repos/plans/beads` for a
  combined sidecar — in addition to `<repo_root>/beads` and in-tree stores. Ordinary
  (non-launch) workspace preparation warns and proceeds instead of rescuing; only a
  store whose recovery ref could not be written stops it too.

#### Duplicate Bead IDs

Two clones minting from their own `next_counter` can allocate the same bead ID and each
write their own `events/streams/<id>.jsonl`. A naive merge of that add/add conflict
produces a stream with two `issue_created` events, which the reducer rejects —
historically wedging the shared store because every sync retry failed the same way.

Conflict resolution relocates one of the two beads instead of failing. The resolver
allocates the relocation ID from a store-wide pool built from `config.json`'s
`next_counter` plus every stream ID already in the store, so the ID a collision lands on
depends only on the store's contents and not on which clone happens to resolve the
conflict first. Both beads survive under distinct IDs, and the resolver reports
`relocated duplicate beads: <old> -> <new>` — in its own resolution message and in the
managed sync log under `~/.sase/bead_push_logs/sync-*.log`. If a bead you expect is
missing after a concurrent-mint conflict, search those logs for that line: the bead
still exists, under the new ID.

## Rust Backend

The bead data model, event reducer, JSONL/config codecs, compatibility-cache refresh,
mutation transactions, ID allocation, deterministic work-plan DAG, and common CLI output
planning are implemented in `sase-core` and exposed through `sase_core_rs`. Python keeps
the host logic that belongs in the application layer: locating the active bead store,
relativizing plan paths, resolving VCS context and macros for `sase bead work`,
prompting the user, launching agents, rolling back failed launches, and incrementing
telemetry counters.

Common `sase bead` commands dispatch through an early CLI fast path before the full
top-level parser is built. Help text and host-coupled commands still fall through to the
normal Python parser/handlers where needed.

Use these checks when changing bead internals:

```bash
sase core health -j
pytest tests/test_bead tests/test_core_facade/test_bead_read.py tests/test_core_facade/test_bead_mutation_operations.py tests/test_core_facade/test_bead_mutation_claim.py
just rust-check
just bead-perf-smoke
```

## Current Checkout Source Of Truth

In in-tree mode, `sase bead` reads and mutations of beads that the current checkout
holds use that checkout's `sdd/beads/events/**` event store and `sdd/beads/config.json`,
with `issues.jsonl` used only as a fallback when events are absent. Running the command
in `myproject/` reads that checkout's bead state; running it in `myproject_2/` reads
`myproject_2/sdd/beads/`. The CLI does not merge sibling workspace stores, and duplicate
IDs in another checkout do not override the active checkout's records.

ID allocation also uses only the active store's `config.json` and canonical event state.
If a sibling checkout has not pulled or merged the latest bead state, it may allocate
IDs based on its local state; sync bead changes through the normal VCS workflow when
several agents are coordinating on the same project.

Cross-project helper surfaces, such as mobile/editor bead pickers, may inspect one
canonical store per known project. So may CLI commands, which fall back to those stores
for a full bead ID after a local miss (see
[Bead ID Arguments](beads.md#bead-id-arguments)). None of them merge numbered sibling
workspaces or stores from other layouts for the same project.

## Related

- [Beads](beads.md)
- [Bead pages](bead-pages.md)

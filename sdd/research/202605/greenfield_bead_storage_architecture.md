# Greenfield Bead Storage Architecture

Date: 2026-05-14

## Question

If SASE were designing bead storage from scratch, should all bead data live in one git-tracked JSONL file? If not, what
storage model best supports parallel agents, git portability, reviewability, and deterministic automation?

## Short Answer

No. A single rewritten `issues.jsonl` file is the wrong source-of-truth shape for parallel agents. It is acceptable as a
generated compatibility export, but it should not be the canonical record.

The best greenfield design is:

1. **Canonical source:** append-only bead operation events, sharded by writer/run/month so parallel agents normally write
   different files.
2. **Local query store:** SQLite projections built from those events, with WAL and immediate transactions for fast reads
   and safe local concurrency.
3. **Generated views:** compact JSONL snapshots and/or one-file-per-bead materialized views generated from the event log,
   either ignored or explicitly marked as generated.
4. **Semantic resolver:** domain merge/replay rules owned by Rust core, reused for Git merge drivers, doctor repair,
   migration, compaction, and daemon projections.

This keeps the git-native property, but stops using a mutable materialized view as the shared collaboration surface.

## Current Shape

In this workspace, `sdd/beads/issues.jsonl` currently has 933 rows, is about 784 KiB, and has 757 commits in visible git
history. The current Rust mutation path in `../sase-core/crates/sase_core/src/bead/mutation.rs` loads all issues from
`issues.jsonl`, mutates an in-memory vector, writes `issues.jsonl.tmp`, and renames it over `issues.jsonl`. Export in
`../sase-core/crates/sase_core/src/bead/jsonl.rs` sorts the whole issue set by ID and serializes one full issue row per
line.

That design creates a predictable conflict profile:

- Every mutation rewrites the same path.
- Same-bead changes conflict even when they touch different fields.
- `updated_at`, `status`, and `assignee` make operational claims look like durable data churn.
- Parallel top-level creation can allocate the same sequential ID from separate checkouts.
- The file is a materialized view, but Git treats it as ordinary line-oriented source.

The earlier research note, `sdd/research/202605/bead_jsonl_merge_conflicts.md`, recommends a custom semantic merge
driver as the pragmatic near-term fix. This note answers the stronger greenfield question.

## Design Goals

| Goal | Implication |
|---|---|
| Parallel agents should not block each other | Independent writers should append to independent files or independent DB rows. |
| Git remains the sync substrate | Canonical state should be text, deterministic, reviewable, and cloneable. |
| Reads must be fast | Query APIs should hit SQLite projections, not replay full history on every command. |
| Merges must preserve bead semantics | Conflict policy belongs in Rust core, not in ad hoc manual JSON editing. |
| Human IDs can remain meaningful | IDs may be hierarchical, but allocation must avoid cross-branch collisions or detect them cleanly. |
| Operational state should not pollute durable history | Launch claims, live assignees, and transient `in_progress` state need separate semantics. |

## Prior Art

### Git Attributes and Custom Merge Drivers

Git supports path-specific merge behavior through `.gitattributes`; custom merge drivers receive ancestor/current/other
files and write the merged result back to the current path. This makes a SASE-specific JSONL merge driver viable, but it
is still a patch on top of a poor source-of-truth shape. Source: [Git gitattributes documentation](https://git-scm.com/docs/gitattributes).

### SQLite WAL

SQLite write-ahead logging lets readers continue while writers append to a WAL file, and SASE's projection database
already uses WAL plus `BEGIN IMMEDIATE` in `../sase-core/crates/sase_core/src/projections/db.rs`. This is the right
local concurrency primitive for query caches and daemon-owned write coordination. Source: [SQLite WAL documentation](https://sqlite.org/wal.html).

### Upstream Beads

Upstream Beads uses SQLite as the local working store, a daemon that syncs SQLite to git-tracked JSONL with a debounce,
git hooks for import/export, a merge driver, deletion tracking, duplicate detection, and hash-based IDs to avoid
cross-branch sequential allocation conflicts. Sources: [Beads JSONL Sync](https://steveyegge.github.io/beads/core-concepts/jsonl-sync),
[Beads Hash-based IDs](https://steveyegge.github.io/beads/core-concepts/hash-ids), and
[Beads Daemon Architecture](https://steveyegge.github.io/beads/core-concepts/daemon).

The lesson is not "copy upstream exactly." Upstream can make different tradeoffs because hash IDs make duplicate
"same ID, different issue" less likely, and SQLite is closer to its working source of truth. SASE has stronger human-ID
and SDD-review requirements.

### git-bug

`git-bug` stores issues, comments, and metadata as Git objects rather than working-tree files. That avoids a shared
rewritten file and makes issue state naturally distributed. Source: [git-bug README](https://raw.githubusercontent.com/git-bug/git-bug/master/README.md).

The lesson for SASE is the operation-log model, not the exact storage location. SASE probably should not hide bead state
inside Git refs/objects because SDD artifacts are meant to be inspected in normal working-tree review.

### Jujutsu

Jujutsu records conflicted states as first-class commit data and lets rebases/merges complete before conflicts are
resolved. Source: [Jujutsu first-class conflicts](https://jj-vcs.github.io/jj/latest/conflicts/).

The relevant idea is that conflicts should be structured data, not inline text markers. SASE can approximate that inside
Git by storing events and typed unresolved conflicts instead of forcing the whole bead graph through one file merge.

### JSON Patch and JSON Merge Patch

JSON Patch (RFC 6902) gives a standard vocabulary for operation logs; JSON Merge Patch (RFC 7396) gives recursive patch
semantics for object updates. Sources: [RFC 6902](https://www.rfc-editor.org/rfc/rfc6902) and
[RFC 7396](https://www.rfc-editor.org/rfc/rfc7396).

SASE does not need to expose these standards directly, but bead events should be operation-shaped rather than full-row
snapshot rewrites.

## Greenfield Architecture

### 1. Canonical Event Log

Store canonical bead mutations as immutable JSONL event files:

```text
sdd/beads/
  config.json
  events/
    202605/
      host-a.agent-sase-3a.1.20260514T153000Z.jsonl
      host-a.agent-sase-3a.2.20260514T153012Z.jsonl
      host-b.cli.20260514T154200Z.jsonl
  snapshots/
    202605/
      checkpoint-00000120.jsonl
  generated/
    issues.jsonl
```

Each event should be small and intention-preserving:

```json
{
  "schema_version": 1,
  "event_id": "01J...",
  "created_at": "2026-05-14T15:30:00Z",
  "writer_id": "host-a/agent/sase-3a.1",
  "project_id": "sase",
  "bead_id": "sase-3a.1",
  "type": "bead.status_changed",
  "payload": {
    "from": "open",
    "to": "in_progress",
    "assignee": "sase-3a.1"
  },
  "idempotency_key": "agent:sase-3a.1:claim:sase-3a.1"
}
```

Events should be append-only once written. Writers should create a new file per agent run, workflow run, or CLI session.
This makes the common parallel case conflict-free at Git's file level.

### 2. SQLite Projection as Query Cache

Use SQLite for all normal reads:

- `beads` table: current issue projection by bead ID.
- `bead_dependencies` table: edge projection.
- `bead_events` table: indexed event history.
- `projection_meta` table: last replayed event and snapshot checkpoint.

The existing projection foundation in `../sase-core/crates/sase_core/src/projections/` is already close to this shape:
it has event envelopes, idempotency keys, WAL, `BEGIN IMMEDIATE`, bead event types, bead projections, replay tests, and
projection rebuild helpers. A greenfield bead store should promote this from "projection support" to the bead storage
contract.

SQLite remains a local cache, not the git-transport artifact. Fresh clones rebuild it from event files plus snapshots.

### 3. Generated Snapshots and Exports

Keep generated state for compatibility and fast recovery, but do not treat it as canonical:

- `snapshots/checkpoint-*.jsonl`: compact projection checkpoints after N events or M days.
- `generated/issues.jsonl`: compatibility export for old tooling and review summaries.
- `beads.db`: ignored local cache.

Generated exports can be recreated, so conflicts in them should never block a merge. If they are tracked at all, give
them a merge driver that regenerates from canonical events, or mark them generated and ignore normal merge conflicts.

### 4. Rust-Owned Replay and Merge Policy

Replay order and conflict policy must be explicit:

- Sort events by causal dependencies first, then `created_at`, then `event_id`.
- Deduplicate by `event_id` and `idempotency_key`.
- Treat create/create with the same bead ID but different immutable identity as an unresolved conflict.
- Merge dependency additions as set union by `(issue_id, depends_on_id)`.
- Treat dependency removal as a tombstone event so old additions do not reappear after merge.
- Use a status lattice for lifecycle events, for example `closed` wins over older `in_progress` claims unless a later
  explicit reopen exists.
- Treat notes/comments as append-only child events, not a mutable string field.
- Treat destructive deletes as tombstones with explicit scope and timestamp.

Unresolved conflicts should become structured records, for example:

```text
sdd/beads/conflicts/202605/<conflict-id>.json
```

That is better than conflict markers in `issues.jsonl` because tools can list, explain, resolve, and test them.

### 5. ID Allocation

If starting from scratch, avoid globally sequential top-level IDs. Good options:

| Option | Fit |
|---|---|
| Hash/random root IDs with hierarchical children | Best concurrency. Matches upstream Beads. Less pretty than current `sase-3a`. |
| Reserved ID ranges per writer/workspace | Preserves more human readability. Needs range leasing and repair tooling. |
| Semantic aliases over opaque IDs | Best long-term UX. Store stable opaque IDs, display `sase-3a` aliases where useful. |
| Current local sequential IDs | Worst greenfield choice. Easy to read, but causes cross-branch allocation conflicts. |

My greenfield choice would be **opaque collision-resistant root identity plus human alias**. For example, the canonical
ID is `bd-01J...`, while the display alias can be `sase-3a`. External references should store the canonical ID in
frontmatter or structured metadata and render aliases for humans.

If SASE insists that `sase-3a.2` remains the canonical ID, then ID allocation needs one of:

- per-workspace reserved counter blocks;
- writer-prefixed IDs;
- a merge-time duplicate-ID failure that requires human reassignment and rewrites all references.

The third option is safest but painful. It is what the current JSONL design is drifting toward.

### 6. Durable vs Transient State

Do not store every live operational detail in the durable event log.

| State | Recommended storage |
|---|---|
| Bead created, title changed, dependency added, closed, reopened | Durable event log |
| Agent launched, currently working, heartbeat, local assignee claim | Local runtime/projection state |
| Claim meant to coordinate across agents in one workspace | SQLite transaction or daemon lease |
| Claim meant to coordinate across machines | Explicit lease event with expiry, not plain `status=in_progress` |
| Notes/comments | Append-only comment events |
| Commit/ChangeSpec links | Structured durable link events |

This matters because the highest-conflict fields are often not durable product facts. "Agent X is currently working" is
a lease, not the same kind of data as "this bead is closed."

## Why Not One File Per Bead?

One-file-per-bead is better than one JSONL file, but it is not the best greenfield source of truth.

It fixes independent-bead conflicts because different beads map to different files. It does not solve:

- concurrent edits to the same bead;
- appendable notes/comments unless they become separate files;
- dependency edges spanning beads;
- deletion/update conflicts;
- sequential ID allocation;
- audit history unless old versions are reconstructed from Git.

If event sourcing is too large a jump, one-file-per-bead is the best intermediate storage rewrite. But the final shape
should still add operation events or per-field histories for high-churn and append-only subdomains.

## Why Not Track SQLite?

Tracking SQLite directly is a poor git collaboration format:

- binary diffs are not reviewable;
- Git cannot semantically merge two SQLite files;
- WAL/shm side files are runtime artifacts, not source artifacts;
- resolving conflicts requires app-specific export/import anyway.

SQLite is the right local query and transaction engine. It is the wrong portable source artifact.

## Why Not a CRDT Library?

A JSON/SQLite CRDT could solve concurrent edits, but it is probably too much machinery for bead data. Beads have a small
domain model with obvious merge rules: creation, field update, dependency add/remove, close/reopen, comment append,
delete tombstone, and lease expiry. A SASE-owned event model is simpler, easier to review in Git, and easier to explain
to agents.

CRDT techniques are still useful for one subdomain: free-form collaborative notes. The cleaner product move is to avoid
mutable note strings and make notes append-only comments.

## Greenfield Decision Matrix

| Design | Parallel write conflicts | Same-bead merge quality | Git reviewability | Implementation cost | Verdict |
|---|---:|---:|---:|---:|---|
| Single `issues.jsonl` source | Poor | Poor without custom driver | Good until conflicts | Low | Do not choose greenfield |
| Single JSONL plus semantic merge driver | Medium | Good if policy is strong | Good | Medium | Best near-term retrofit |
| One file per bead | Good for independent beads | Medium | Good | Medium-high | Good intermediate rewrite |
| SQLite authoritative, JSONL export | Good locally | Depends on export merge | Weak if DB tracked | Medium | Good local engine, weak git artifact |
| Git refs/objects like `git-bug` | Good | Good | Weak in normal working tree | High | Conceptually strong, poor SDD fit |
| Event log plus SQLite projections | Best | Best if policy is explicit | Good | High | Best greenfield design |

## Recommended Greenfield Contract

The storage contract should be:

1. **All writes append durable domain events or transient lease records through Rust core.**
2. **No caller rewrites the canonical current-state file because no such file is canonical.**
3. **Read APIs query SQLite projections rebuilt from events and snapshots.**
4. **Generated exports are reproducible and never required for semantic correctness.**
5. **Merge/replay policy is a Rust API with fixture coverage, not a Git-driver-only script.**
6. **Agents write to per-run event files and never share a hot append file unless a daemon serializes it.**

## Migration Implications for SASE

Even if the greenfield answer is event-sourced storage, the practical path from today should be staged:

1. **Short term:** implement the semantic merge driver from `bead_jsonl_merge_conflicts.md` and add an advisory write
   lock around current JSONL read-mutate-write operations.
2. **Medium term:** route bead mutations through the existing projection/event framework in `../sase-core`, initially
   shadowing `issues.jsonl` and checking that projected output matches current reads.
3. **Medium term:** split notes, commit links, and launch claims out of the mutable issue row.
4. **Long term:** make event files canonical, make `issues.jsonl` generated, and teach `sase bead doctor` to rebuild
   projections and exports from events.
5. **Later:** consider opaque canonical IDs plus human aliases if sequential ID collisions remain a recurring cost.

## Concrete Event Types

Start with a small closed set:

- `bead.created`
- `bead.field_changed`
- `bead.status_changed`
- `bead.closed`
- `bead.reopened`
- `bead.removed`
- `bead.dependency_added`
- `bead.dependency_removed`
- `bead.comment_added`
- `bead.link_added`
- `bead.link_removed`
- `bead.lease_acquired`
- `bead.lease_released`
- `bead.lease_expired`
- `bead.snapshot_observed`

Avoid generic "replace whole issue" events except for import/migration snapshots. Generic replacement events recreate
the same semantic merge problem inside the event log.

## Validation Fixtures

A greenfield implementation should ship fixtures for:

- two agents closing different beads;
- two agents updating different fields on the same bead;
- `in_progress` claim racing with `closed`;
- duplicate top-level ID creation;
- dependency add/add, add/remove, and remove/update;
- append-only comment ordering;
- delete versus later update;
- snapshot plus later events;
- replay idempotency;
- corrupted event line;
- generated JSONL regeneration;
- projection rebuild from empty SQLite;
- merge of two event directories with deterministic output.

## Bottom Line

If starting over, do not make `issues.jsonl` the bead database. Make it an export.

The durable unit should be an immutable bead event, written to a sharded git-tracked event log. SQLite should serve
queries and local transactions. Rust core should own deterministic replay, merge policy, validation, compaction, and
generated exports. That design matches the way SASE actually uses beads: many short-lived agents mutate small pieces of
a shared work graph, while humans still need a durable, inspectable project history.

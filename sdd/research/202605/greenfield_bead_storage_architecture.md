# Greenfield Bead Storage Architecture

Date: 2026-05-13 (revised same day with additional prior art — Pijul, Fossil, Datomic, Automerge/Yjs — operational
design sections covering clocks, schema evolution, compaction cadence, concurrency, durability, repository file-count
cost, reviewability, observability, an external-reference integrity section, a fresh-clone bootstrap section, and a
risk register; corrected current-shape stats)

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

In this workspace, `sdd/beads/issues.jsonl` currently has 933 rows, is about 781 KiB, and has 759 commits in visible git
history. The current Rust mutation path in `../sase-core/crates/sase_core/src/bead/mutation.rs` loads all issues from
`issues.jsonl`, mutates an in-memory vector, writes `issues.jsonl.tmp`, and renames it over `issues.jsonl`. Export in
`../sase-core/crates/sase_core/src/bead/jsonl.rs` sorts the whole issue set by ID and serializes one full issue row per
line. The on-disk layout under `sdd/beads/` is currently flat: `config.json`, `metadata.json`, `issues.jsonl`, and a
local `beads.db` cache.

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

### Pijul Patch Theory

Pijul models history as a set of named patches with explicit dependencies, not a linear sequence of snapshots. Patches
that touch disjoint regions commute, so applying them in any order yields the same working tree. Source: [Pijul
manual](https://pijul.org/manual/).

The relevant lesson is not "adopt Pijul." It is that a bead operation log with explicit per-event causal dependencies
(for example, `bead.status_changed` depends on `bead.created`, `bead.dependency_removed` depends on the matching add)
admits the same commute property: independent agents' event streams can be merged in any order without semantic
ambiguity. SASE already needs causal ordering for replay determinism; making the dependency explicit per event is
cheaper than reverse-engineering it from timestamps at merge time.

### Fossil SCM

Fossil stores all repository content — checkins, wiki, tickets, forum posts, technotes — as immutable, content-addressed
artifacts inside an embedded SQLite database; the working SQLite file is itself the durable source of truth, and sync
happens by exchanging artifacts. Source: [Fossil concepts](https://fossil-scm.org/home/doc/trunk/www/concepts.wiki).

The lesson for SASE is the *artifact-set* mental model rather than Fossil's specific storage. Bead events should be
addressable, immutable, and content-hashed once written, so that "do we already have this event?" is a constant-time
local question and so that two clones can reconcile state by exchanging the set difference of event hashes rather than
diffing rewritten files.

### Datomic and Immutable Databases

Datomic separates the durable transaction log (an append-only sequence of immutable facts) from query-time indexes
(maintained projections) and read-time peers (in-process caches). Source: [Datomic architecture
overview](https://docs.datomic.com/pro/architecture.html).

This is the same shape recommended below for SASE: durable events, derived projections, ephemeral readers. Datomic's
specific contribution is the "as-of" query model — being able to ask "what did this bead look like at time T?" is
basically free once the canonical store is an event log, and the bead doctor / audit / blame use cases benefit from it.

### Automerge and Yjs

Automerge (JSON CRDT) and Yjs (sequence/map CRDT) implement conflict-free replicated data types that converge on the
same state regardless of operation order. Sources: [Automerge documentation](https://automerge.org/docs/) and [Yjs
documentation](https://docs.yjs.dev/).

The relevant takeaway is the same as the dedicated CRDT section below: full CRDT machinery is overkill for bead data
because the bead domain admits simple per-field merge rules. But Automerge's actor-ID-plus-Lamport-counter event
identity is a clean template for the `event_id` / `writer_id` design proposed here, and Yjs's append-only update files
are a working example of the per-writer event log pattern at production scale.

### Hybrid Logical Clocks

Wall-clock timestamps are insufficient to order events across machines because clocks drift. Lamport clocks preserve
causal order but not wall-clock locality; hybrid logical clocks (HLCs) combine both and stay within a bounded delta of
real time while still being monotone per causal chain. Sources: [Lamport, "Time, Clocks, and the Ordering of Events in
a Distributed System"](https://lamport.azurewebsites.net/pubs/time-clocks.pdf) and [Kulkarni et al., "Logical Physical
Clocks"](https://cse.buffalo.edu/tech-reports/2014-04.pdf).

SASE will eventually run beads across machines (mobile, multiple workstations, remote agents). If event ordering relies
only on `created_at`, clock skew silently corrupts replay. HLCs are the right primitive; ULIDs alone are not enough
because two writers can mint nearby ULIDs from skewed clocks.

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

## Operational Design

### Clock and Causal Ordering

The event envelope above carries `created_at` and `event_id`. For single-machine ordering that is fine. For multi-host
replay determinism it is not, because nothing prevents two machines from minting events with wall-clock values out of
causal order.

The recommended replacement is a hybrid logical clock per writer:

```json
{
  "event_id": "01J...",
  "writer_id": "host-a/agent/sase-3a.1",
  "hlc": "2026-05-13T18:42:01.327Z/0042"
}
```

The HLC stamp combines the writer's wall clock with a per-writer monotonic counter, with the bounded-delta invariant
from the Kulkarni paper above. Replay sorts by `(hlc, writer_id, event_id)`. Wall-clock `created_at` is still useful
for human-readable diagnostics, but it must not be the merge sort key.

Causal dependencies should be explicit on the event:

```json
{
  "type": "bead.status_changed",
  "depends_on": ["<event_id of bead.created>"]
}
```

This lets the resolver detect missing-prerequisite events (for example, status change for a bead whose creation event
never arrived) and either defer replay or surface a structured conflict.

### Event Schema Evolution

Event schemas will change. The greenfield contract must commit upfront to how:

- Every event carries `schema_version: <int>` at the envelope level and `payload_version: <int>` inside `payload`.
- Forward compatibility: unknown event types replay as opaque `bead.unknown` placeholders that block writes against the
  affected bead but do not corrupt unrelated projections. This prevents an old client from silently dropping events it
  does not understand.
- Backward compatibility: removed event types stay defined in code as no-op replayers with a documented `removed_at`
  release.
- Field additions are additive-only with explicit defaults. Renames require a new event type and a one-shot migration
  event that replays the old shape.
- Schema upgrades ship a `bead.migration_applied` event so any later replayer can see which migrations the log has
  consumed, rather than guessing from event content.
- A pinned schema bundle lives under `sdd/beads/schemas/<version>.json` so old events remain reproducible even if the
  current Rust types have moved on.

### Compaction and Snapshot Cadence

Append-only event logs grow without bound. The greenfield design needs an explicit retention policy, not a hope:

| Trigger | Action |
|---|---|
| Every N events (default 5000) | Emit a `snapshots/<yyyymm>/checkpoint-<event-id>.jsonl` projection snapshot. |
| Every M days (default 30) of inactivity for a writer shard | Roll the shard closed and stop accepting appends. |
| Every snapshot older than the latest two checkpoints | Mark eligible for compaction. |
| User-initiated `sase bead compact` | Replay all events into a new snapshot, rewrite causally redundant events into one summary event per bead, and prune superseded events. |

Snapshots are checkpoints, not deletions. Pruned events should move to `sdd/beads/archive/<yyyymm>/` rather than being
removed, so the audit chain remains complete and so that `bead doctor` can re-verify the projection from a clean state.

The cadence numbers above are starting points. The realistic tuning question is "how many events per active root bead
per day?" — current `issues.jsonl` churn (456 single-line commits in two weeks) suggests roughly 30-50 mutation events
per active day. A 5000-event checkpoint cadence is therefore monthly under current load.

### Concurrency and Locking Model

Per-writer event files solve cross-writer contention but do not eliminate intra-writer races. Two CLI invocations from
the same workspace, or a CLI plus the daemon, can both try to append to the same writer's current event file.

Recommended model:

- Writes go through a Rust core API, never through direct file appends.
- Each writer shard has a sibling lock file (`*.lock`) acquired via `flock(2)` (`fs2`/`fd-lock` in Rust) for the
  duration of one append.
- A long-lived `sase beadd` daemon, if present, owns the writer shard for its workspace; CLI mutations route through
  the daemon over a local socket and skip the flock entirely.
- If the daemon is not running, the CLI takes the flock directly and writes the event file inline.
- Fsync is mandatory after each append. Event durability is the new merge-conflict-prevention substrate, so a torn
  write that loses an event is much more harmful than the same bytes lost in today's JSONL rewrite (today's loss
  surfaces as a textual conflict; tomorrow's would surface as a missing operation).

This is similar to upstream Beads' daemon-owned write path, but it keeps the daemon optional rather than required, so
short-lived CLI sessions and CI jobs do not need to start a daemon to mutate state.

### Durability, Torn Writes, and Idempotency

Each event line should be self-contained and verifiable:

- Lines end with `\n`. Readers ignore the final line if it lacks a terminating newline (it is a torn write in
  progress).
- Each event carries `content_hash: "sha256:<hex>"` over its canonical JSON form, computed before write.
- Each event carries `idempotency_key: "<writer_id>:<intent>:<scope>"`. Replaying with the same key produces no change.
- The shard file format is `JSON Lines + final-line-newline-required + line-hash-verified`. Recovery for partially
  written files truncates back to the last newline.
- `fsync(file)` after each append; `fsync(dir)` at shard boundaries.
- A periodic `sase bead doctor --verify` should re-hash every event line and report drift.

Idempotency keys are also the right tool for retried agent actions. An agent that crashes mid-mutation and restarts
should produce the same idempotency key for the same intent so the resolver dedupes the retry rather than recording two
status changes.

### Repository Cost: File Count and Pack Pressure

Sharding by writer/run/month produces more files than today's single JSONL. Two concerns are worth pricing out:

- **Working-tree file count.** At current churn (~30-50 events/day, ~5 active writers), event-file count grows by
  roughly 5-25 files per month. The `events/<yyyymm>/` partition keeps any single directory under a few hundred files
  for years. Tools that recurse the working tree (search, fzf, watchman) handle this trivially.
- **Git pack pressure.** Many tiny files create many loose objects until `git gc` packs them. At the scale above this
  is negligible (kilobytes-per-month of additional pack data), but the same effect compounds if event files are
  per-event rather than per-run. Source: [Git internals — packfiles](https://git-scm.com/book/en/v2/Git-Internals-Packfiles).
  Keep events batched per agent run, not per individual mutation.
- **Clone size.** Snapshots dominate. A monthly snapshot file at ~1 MiB plus 12 months of retained checkpoints is
  ~12 MiB — still smaller than today's `issues.jsonl` history footprint, because the JSONL file's full text rewrites
  on every commit.

A reasonable safety valve is a target of "no more than one event-log directory per month per writer." If a writer
exceeds it, the daemon rolls a new shard.

### Reviewability of Event-Sourced PRs

A reviewer looking at a PR today sees a diff of `issues.jsonl` and reads it row-by-row. An event-sourced PR instead
adds a few new event files, which is harder to skim without tooling. The greenfield design needs to ship that tooling
alongside the storage:

- `sase bead diff <base>..<head>` renders the projection delta — beads created, fields changed per bead, dependencies
  added or removed, status transitions — independent of how those changes are stored.
- `sase bead log <bead-id>` reconstructs a per-bead operation history from the event log.
- A pre-commit hook or PR template appends the rendered projection diff to the commit message body so the GitHub UI
  surfaces the semantic change even when the file diff is sharded.
- Generated `generated/issues.jsonl` can still be committed as a reviewer-facing export. It should never be the merge
  source of truth, but it remains the single best-known projection for code review.

This is the same design move that lets generated lockfiles (Cargo.lock, package-lock.json) be reviewed in PRs without
humans reading them line by line.

### Operational Observability

The greenfield store should emit structured metrics from day one. Without them the team cannot tell whether the new
design is actually reducing conflicts:

- `bead.events.appended{type,writer_id}`: counter, per event type per writer.
- `bead.projection.replay_seconds{kind=cold|incremental}`: histogram of replay duration.
- `bead.merge.outcome{result=clean|conflict|aborted}`: counter for resolver invocations.
- `bead.shard.size_bytes`, `bead.shard.file_count`: gauges to detect runaway sharding.
- `bead.lock.wait_ms`: histogram of intra-workspace lock contention.
- `bead.idempotency.deduped`: counter for retries the resolver collapsed.
- A `~/.sase/metrics/bead.jsonl` sink with one event per significant resolver action is enough; no Prometheus
  dependency.

A weekly summary command (`sase bead stats`) makes these visible to humans and is the leading indicator if a refactor
accidentally regresses the model.

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

## External Reference Integrity

Bead IDs are not internal. They appear in:

- ChangeSpec drawers (NAME, COMMITS, MENTORS) under `~/.sase/projects/<project>/*.gp`.
- Tale, plan, legend, and prompt markdown files under `sdd/`.
- Commit message footers (`Bead: sase-3a.2.5`).
- Hook scripts and xprompt templates that grep for bead IDs.
- TUI keybindings and dynamic memory matchers that key off bead IDs.

A storage migration that even *threatens* to rename an existing ID must inventory these reference sites first. The
greenfield contract should therefore preserve `sase-<root>.<phase>` IDs as stable display aliases over the migration,
even if it introduces opaque canonical IDs underneath. The mapping `display_alias -> canonical_id` belongs in the
projection database, with `bead.alias_assigned` and `bead.alias_renamed` events for any future remapping.

The corollary is that the resolver's duplicate-display-ID conflict case must remain fail-closed: two writers cannot
silently coexist with the same `sase-3a.2.5` because external content links to that string and would not be rewritten
automatically.

## Bootstrap and Fresh Clone

A greenfield contract needs a story for "what is on disk in a brand-new project":

- `sdd/beads/config.json` with `schema_version`, `writer_id_seed`, `id_strategy` (`opaque-with-alias` or `sequential`),
  and `display_id_prefix` (`sase`).
- `sdd/beads/events/` exists but empty. Writers create the first month directory lazily.
- `sdd/beads/snapshots/` exists with a single empty checkpoint marking the genesis state.
- `sdd/beads/generated/issues.jsonl` is an empty file.
- `sdd/beads/.gitattributes` marks the generated directory as `linguist-generated` and configures any merge driver for
  `generated/issues.jsonl` to regenerate rather than text-merge.
- `beads.db` is created lazily on first read.

A fresh clone runs `sase bead doctor --rebuild` once, which materializes `beads.db` from snapshots plus events. Cold
rebuild time should be budgeted under one second at current scale (under 1000 events) and under ten seconds at
projected scale (low tens of thousands of events).

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
- merge of two event directories with deterministic output;
- two writers with skewed wall clocks producing causally-ordered HLC events;
- a torn write at the end of an event file (final line missing terminating newline);
- replay across a schema version bump with a `bead.migration_applied` event;
- replay against a snapshot plus tail events versus full-replay-from-zero — must match;
- a `bead.unknown` opaque event from a newer schema version (forward compatibility);
- deduplication of a retried agent action with the same `idempotency_key`;
- alias rename event followed by external reference resolution;
- compaction that prunes superseded events without changing the projection.

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Many small event files inflate clone size | Low | Low | Per-run (not per-event) sharding; monthly directory partitions; periodic snapshot compaction. |
| Reviewers cannot read event-file diffs | High | Medium | Ship `sase bead diff` from day one; keep `generated/issues.jsonl` as reviewer-facing export. |
| Clock skew across machines corrupts replay order | Medium | High | Use hybrid logical clocks per writer; explicit `depends_on` references; reject events whose HLC is more than a configured delta from observed wall clock. |
| Torn writes silently drop events | Low | High | Mandatory `fsync`, content-hashed events, final-newline-required parser, periodic `bead doctor --verify`. |
| Schema migration breaks old clones | Medium | High | Pinned schema bundle under `sdd/beads/schemas/`, opaque `bead.unknown` replayers, `bead.migration_applied` audit trail. |
| Display-ID collisions across branches | Medium | Medium | Display-ID is an alias over an opaque canonical ID; resolver fails closed on conflicting aliases. |
| Daemon optionality causes inconsistent lock semantics | Medium | Medium | Same `flock(2)` contract whether the daemon owns the lock or the CLI does; documented in `mutation.rs`. |
| Append-only log accumulates sensitive content (e.g., notes with secrets) | Low | High | Tombstone-with-redaction event type (`bead.note_redacted`) that the resolver applies before exposing notes; archive directory for the original event. |
| Generated `issues.jsonl` drifts from canonical events | Medium | Low | Regenerate-on-commit hook; CI assertion that re-rendering produces a clean diff. |
| Replay performance degrades on large logs | Low | Medium | Checkpoint cadence policy (Compaction section); incremental replay since last snapshot. |

## Bottom Line

If starting over, do not make `issues.jsonl` the bead database. Make it an export.

The durable unit should be an immutable bead event, written to a sharded git-tracked event log. SQLite should serve
queries and local transactions. Rust core should own deterministic replay, merge policy, validation, compaction, and
generated exports. That design matches the way SASE actually uses beads: many short-lived agents mutate small pieces of
a shared work graph, while humans still need a durable, inspectable project history.

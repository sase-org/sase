---
create_time: 2026-05-13 14:52:27
status: wip
prompt: sdd/prompts/202605/rust_daemon_event_projection_core_epic1.md
---
# Plan: Epic 1 Rust Event Model and Projection Storage Core

## Context

Epic 1 from `sdd/legends/202605/rust_daemon_indexed_projections_1.md` establishes the shared Rust-owned state substrate
for the daemon rebuild. The primary write scope is the sibling Rust workspace: `../sase-core/crates/sase_core`.

The existing Rust core already owns several reusable contracts that this epic should build on rather than duplicate:

- ChangeSpec parsing and wire records in `parser`, `sections`, `wire`, and `project_spec`.
- Notification JSONL and pending-action behavior in `notifications`.
- Bead SQLite/JSONL storage and mutation/read behavior in `bead`.
- Agent artifact scanning and a small SQLite index in `agent_scan`.
- Dismissed-agent archive query/FTS behavior in `agent_archive`.
- Xprompt and editor catalog behavior in `xprompt_catalog` and `editor`.

The missing substrate is a canonical append-only event model, one SQLite projection database shared by all indexed
surfaces, deterministic replay/rebuild behavior, and transaction/maintenance policy. This plan intentionally does not
route production CLI, ACE, editor, or daemon reads to the new projections. That belongs to later epics.

## Goals

- Add a reusable event envelope and typed event families with stable serde JSON shapes.
- Add a projection store module that owns SQLite migrations, WAL pragmas, event append, projection application,
  metadata, replay, rebuild, checkpoint, backup, and compaction primitives.
- Materialize indexed projections for ChangeSpecs, notifications, agents/artifacts/archive, beads, workflows, xprompts,
  memory catalog, and file history.
- Prove by tests that live event application and replay produce equivalent projections for representative valid event
  sequences.
- Preserve existing source stores as source-of-truth inputs; projections are rebuildable and disposable.

## Non-Goals

- Do not introduce a long-lived daemon process or local transport in this epic.
- Do not change Python CLI/TUI behavior or make the new database authoritative for reads/writes.
- Do not remove current `.sase`, `.gp`, notification JSONL, bead, artifact, or workflow files.
- Do not create parallel business logic for parsing or mutation semantics that already exists in `sase_core`.

## Proposed Module Shape

Add a new `projection` module under `../sase-core/crates/sase_core/src/projection/`:

- `mod.rs`: public facade, error type, store config, exports.
- `event.rs`: canonical event envelope, IDs, typed source/identity/causality structs, event family enum.
- `schema.rs`: ordered migrations, schema version constants, table/FTS creation SQL.
- `store.rs`: SQLite connection setup, WAL pragmas, `BEGIN IMMEDIATE` transactions, append/apply APIs.
- `replay.rs`: replay gaps, full replay, rebuild from event log plus source snapshots.
- `maintenance.rs`: checkpoint, backup, compaction, retention decisions.
- Surface projection modules:
  - `changespec.rs`
  - `notification.rs`
  - `agent.rs`
  - `bead.rs`
  - `workflow.rs`
  - `catalog.rs`
  - `file_history.rs`

Keep the public API narrow at first: event append, replay/rebuild, projection inspection helpers for tests, and explicit
surface upsert/apply functions. Later daemon/read API epics can add paged query contracts on top.

## Phase Split

Each phase below is intended for a distinct agent instance. Phases are sequential unless explicitly marked as able to
branch after the previous phase lands.

### Phase 1A: Event Envelope, Store Skeleton, Migrations, Metadata

Primary files:

- `../sase-core/crates/sase_core/src/projection/event.rs`
- `../sase-core/crates/sase_core/src/projection/schema.rs`
- `../sase-core/crates/sase_core/src/projection/store.rs`
- `../sase-core/crates/sase_core/src/projection/mod.rs`
- `../sase-core/crates/sase_core/src/lib.rs`
- focused tests under `../sase-core/crates/sase_core/tests/`

Tasks:

1. Define the canonical event envelope:
   - schema version
   - sequence number
   - timestamp
   - source
   - project identity
   - host identity
   - event type
   - typed JSON payload
   - idempotency key
   - causality metadata
2. Define event family/type enums for all Epic 1 surfaces, with serde representations stable enough for snapshot tests.
3. Add the base SQLite schema:
   - `schema_migrations`
   - `event_log`
   - `projection_meta`
4. Implement connection setup:
   - create parent directories
   - `journal_mode=WAL`
   - `synchronous=NORMAL`
   - `foreign_keys=ON`
   - busy timeout
5. Implement `BEGIN IMMEDIATE` transaction helpers that append an event and update `projection_meta.last_seq`
   atomically, but leave surface-specific projection application as no-op or explicit test hooks.
6. Add unit tests for migration idempotency, event JSON shape, idempotency-key handling, sequence monotonicity, and
   metadata updates.

Acceptance:

- `cargo test -p sase_core projection` passes.
- A newly opened projection DB has all base tables and records the current schema version.
- Duplicate idempotency keys do not create duplicate logical events.
- Reopening an existing DB does not rewrite or regress schema metadata.

### Phase 1B: ChangeSpec and Notification Projections

Primary files:

- `../sase-core/crates/sase_core/src/projection/changespec.rs`
- `../sase-core/crates/sase_core/src/projection/notification.rs`
- `../sase-core/crates/sase_core/src/projection/schema.rs`
- tests under `../sase-core/crates/sase_core/tests/`

Tasks:

1. Add ChangeSpec event payloads for parsed snapshot/upsert, mutation, status/archive movement, section updates, and
   deletion/tombstone.
2. Add ChangeSpec tables:
   - `changespecs`
   - `changespec_edges`
   - `changespec_sections`
   - `changespec_search_fts`
3. Populate ChangeSpec projections from existing `ChangeSpecWire` records produced by `parse_project_bytes`.
4. Add notification event payloads for append, rewrite/snapshot, state update, pending-action register/update/cleanup,
   and deletion/tombstone.
5. Add notification tables:
   - `notifications`
   - `pending_actions`
   - `notification_search_fts`
6. Populate notification projections using existing `NotificationWire` and `PendingActionWire` semantics.
7. Add replay-vs-live tests for ordered and reordered independent events, archive movement, notification rewrite, and
   pending action state.

Acceptance:

- ChangeSpec projections preserve parser wire identity for fixture `.sase` and archive files.
- Notification projections preserve current notification-store visibility/count behavior for representative JSONL rows.
- FTS rows are bounded to summary/searchable text and are removed on tombstone/rewrite.
- Live application and replay produce byte-equivalent inspection snapshots for this phase's surfaces.

### Phase 1C: Agent, Artifact, and Archive Projections

Primary files:

- `../sase-core/crates/sase_core/src/projection/agent.rs`
- `../sase-core/crates/sase_core/src/projection/schema.rs`
- integration with existing `agent_scan` and `agent_archive` types where needed
- tests under `../sase-core/crates/sase_core/tests/`

Tasks:

1. Add agent event payloads for lifecycle transitions, attempts, parent/child edges, workflow-child edges, artifacts,
   dismissed identities, archive bundle upsert, revive, purge, and tombstone.
2. Add agent tables:
   - `agents`
   - `agent_attempts`
   - `agent_edges`
   - `agent_artifacts`
   - `agent_archive`
   - `dismissed_identities`
   - `agent_search_fts`
3. Reuse `AgentArtifactRecordWire`, scanner summaries, and archive summary logic instead of reparsing marker/archive
   formats in the projection module.
4. Encode stable identities for agent families, attempts, artifact directories, workflow children, and dismissed
   bundles.
5. Add tests for active-to-done transitions, waiting/question markers represented as lifecycle events, retry chains,
   parent/child edges, archive revive, and tombstone cleanup.

Acceptance:

- Existing agent artifact scanner output can be transformed into projection events without losing fields needed by ACE.
- Archive projection rows align with current `agent_archive` summary/query behavior on fixture bundles.
- Replay equivalence holds for lifecycle transitions, edge updates, retry chains, and archive rows.

### Phase 1D: Bead, Workflow, Xprompt, Memory, and File-History Projections

Primary files:

- `../sase-core/crates/sase_core/src/projection/bead.rs`
- `../sase-core/crates/sase_core/src/projection/workflow.rs`
- `../sase-core/crates/sase_core/src/projection/catalog.rs`
- `../sase-core/crates/sase_core/src/projection/file_history.rs`
- `../sase-core/crates/sase_core/src/projection/schema.rs`
- tests under `../sase-core/crates/sase_core/tests/`

Tasks:

1. Add bead event payloads for create, update, status transition, dependency add/remove, ready-to-work marker,
   ChangeSpec metadata changes, import/export snapshot, and tombstone.
2. Add bead tables:
   - `beads`
   - `bead_dependencies`
   - `bead_events`
   - optional `bead_search_fts` if useful for later Epic 4 read APIs
3. Reuse existing `bead` wire records and mutation/read semantics.
4. Add workflow event payloads for run start/finish, step transition, HITL pause/resume, retry, and tombstone.
5. Add workflow tables:
   - `workflows`
   - `workflow_steps`
   - `workflow_events`
6. Add catalog/file-history event payloads and tables:
   - `xprompt_catalog`
   - `memory_catalog`
   - `file_history`
7. Add tests for bead dependency graph updates, ready/blocked state materialization, workflow step transitions, HITL
   pause/resume, xprompt catalog replacement, and file-history replacement/tombstone behavior.

Acceptance:

- Bead projection events can be generated from existing `IssueWire`/dependency data without inventing parallel issue
  semantics.
- Workflow projections support run/step state sufficient for later ACE list/detail views.
- Catalog and file-history projections handle complete snapshot replacement deterministically.
- Replay equivalence holds for all new phase surfaces.

### Phase 1E: Replay, Rebuild, Maintenance, Compaction, and Property Tests

Primary files:

- `../sase-core/crates/sase_core/src/projection/replay.rs`
- `../sase-core/crates/sase_core/src/projection/maintenance.rs`
- surface modules touched only to expose rebuild/replay hooks
- tests under `../sase-core/crates/sase_core/tests/`

Tasks:

1. Implement startup gap detection:
   - read `event_log`
   - compare with `projection_meta.last_seq`
   - replay missing events in order
   - refuse or report impossible gaps/corruption with structured errors
2. Implement full projection drop/rebuild from event log.
3. Add source-snapshot rebuild helpers that accept already-parsed source rows from existing parsers/scanners/stores.
   File watching and source crawling belong to Epic 3, so this phase should expose primitives rather than own watchers.
4. Add maintenance policy:
   - idle checkpoint API
   - checkpoint trigger helpers for 1 GiB or 10-minute soft cap
   - `VACUUM INTO` backup snapshot API
   - bounded retention and compaction for high-volume ephemeral log/tick event classes
5. Add generated sequence tests. Prefer a small local generator using existing dev dependencies unless the phase first
   justifies adding `proptest` to the workspace.
6. Add corruption/stale-projection tests:
   - drop projection tables and rebuild
   - stale `projection_meta.last_seq`
   - duplicate idempotency key
   - truncated/corrupt payload row
   - FTS rows after tombstones and compaction

Acceptance:

- Full replay and rebuild are deterministic for all Epic 1 surfaces.
- Corrupt or stale projection tables can be dropped and rebuilt from the event log.
- Maintenance functions can checkpoint, back up with `VACUUM INTO`, and compact high-volume events without changing
  durable projections.
- `cargo test -p sase_core` passes.

## Cross-Phase Constraints

- Keep projection DB state disposable. Source files and event logs remain the durable recovery path.
- Use existing Rust parser/store/scanner wire types for canonical semantics.
- Keep schema migrations additive and ordered; never require a production command to route through the new projections
  during Epic 1.
- Avoid Python bindings unless a later phase explicitly needs test-only parity plumbing. The daemon/client integration
  comes in later epics.
- Keep FTS content intentionally bounded to user-visible searchable summaries, not full artifact payloads or full logs.
- Treat host identity and project identity as first-class fields in every event and projection row that can cross
  workspaces or synced directories.

## Verification Strategy

Focused commands for phase agents:

```bash
cargo test -p sase_core projection
cargo test -p sase_core --test golden_corpus_parity
cargo test -p sase_core --test notification_store_parity
cargo test -p sase_core --test bead_read_parity
cargo test -p sase_core --test agent_scan_parity
```

Final Epic 1 verification:

```bash
cargo test -p sase_core
cargo test --workspace
```

If a phase modifies this Python repo as well as `../sase-core`, run the repo workflow after `just install`:

```bash
just install
just check
```

## Handoff Notes for Phase Agents

- Start each phase by checking `git status --short` in both this repo and `../sase-core`.
- Do not modify memory files.
- Do not reroute CLI/TUI behavior to the projection DB.
- Update `lib.rs` exports only for APIs that later phases or tests need.
- If a phase needs to alter files owned by a previous phase, keep changes narrow and mention the cross-phase dependency
  in the final handoff.

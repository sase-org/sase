---
create_time: 2026-05-13 17:11:16
status: wip
prompt: sdd/prompts/202605/rust_daemon_epic2_event_projection_storage.md
---
# Epic 2 Plan - Event Model and Projection Storage Core

## Context

Epic 2 from `sdd/legends/202605/rust_daemon_indexed_projections_1.md` creates the Rust-owned state substrate for the
future SASE daemon. The primary implementation scope is the sibling repository:

- `../sase-core/crates/sase_core`

This work should not reroute Python commands, ACE, editor helpers, or mobile APIs. It should create a reusable
append-only event log, SQLite migration/projection core, and domain projections that later epics can query through the
daemon.

Important existing facts:

- `sase_core` already owns canonical Rust parser/query/notification/bead/agent-scan logic.
- `sase_core` already depends on bundled `rusqlite`.
- `agent_scan::index` is a useful but local precedent for WAL-backed SQLite indexing; Epic 2 should generalize the
  pattern rather than continue one-off indexes.
- Existing parity tests cover ChangeSpecs, notifications, beads, agent scans, query evaluation, and Python wire shapes.
- Shared backend behavior belongs in `sase_core`; Python should remain a compatibility caller until later epics.

## Product And Architecture Goals

- Introduce a canonical event envelope with versioning, monotonic sequence, source metadata, host/project identity,
  event type, JSON payload, idempotency key, and causality links.
- Store durable events and materialized projections in SQLite with WAL enabled and deterministic migrations.
- Apply each event and its projection updates in one `BEGIN IMMEDIATE` transaction.
- Keep projections rebuildable from event logs plus current source files; SQLite is not the source of truth yet.
- Reuse existing Rust parsers and wire records instead of duplicating domain logic.
- Keep all APIs shaped for future daemon use: pages, handles, stable IDs, summaries, and replayable state.

## Out Of Scope For Epic 2

- Starting or managing a long-lived daemon process.
- Unix-socket transport, SSE/delta subscriptions, or Python daemon clients.
- Routing production CLI/TUI/editor reads or writes to the new projections.
- Moving source-of-truth writes into the daemon.
- Removing or replacing existing `.sase`, `.gp`, notification JSONL, bead JSONL/SQLite, or agent artifact files.

## Proposed Module Shape

Use a new top-level module in `sase_core`:

- `src/projections/mod.rs`
- `src/projections/error.rs`
- `src/projections/event.rs`
- `src/projections/db.rs`
- `src/projections/migrations.rs`
- `src/projections/replay.rs`
- `src/projections/rebuild.rs`
- `src/projections/changespec.rs`
- `src/projections/notifications.rs`
- `src/projections/agents.rs`
- `src/projections/beads.rs`
- `src/projections/workflows.rs`
- `src/projections/catalogs.rs`
- `src/projections/maintenance.rs`

Prefer typed helpers around a stable envelope instead of one huge exhaustive enum that every phase must edit. The core
envelope can use `event_type: String` and `payload: serde_json::Value`, while each domain module owns typed constructors
and decoders for its event families.

## Phase 2A - Storage Foundation And Event Envelope

Owner: one agent.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/{mod.rs,error.rs,event.rs,db.rs,migrations.rs,replay.rs}`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core/Cargo.toml` only if property-test or time/UUID helpers are needed

Deliverables:

- `EventEnvelopeWire` and supporting records:
  - `schema_version`
  - `seq`
  - `created_at`
  - `source`
  - `host_id`
  - `project_id`
  - `event_type`
  - `payload`
  - `idempotency_key`
  - `causality`
  - optional `source_path` and `source_revision`
- Event source and causality structs that serialize deterministically.
- `ProjectionDb` open/configure path:
  - creates parent directories;
  - sets `busy_timeout`;
  - sets `PRAGMA journal_mode=WAL`;
  - sets `PRAGMA synchronous=NORMAL`;
  - sets `PRAGMA foreign_keys=ON`;
  - exposes transaction helpers using `BEGIN IMMEDIATE`.
- Base schema migrations:
  - `schema_migrations`
  - `event_log`
  - `event_idempotency`
  - `projection_meta`
- Migration runner with idempotent ordered migrations and tests for re-running migrations.
- Event append API that:
  - allocates monotonic `seq`;
  - enforces idempotency key uniqueness when provided;
  - stores canonical JSON payload;
  - updates `projection_meta.last_seq` inside the same transaction.
- Replay scaffold that can iterate event rows in sequence and dispatch to registered projection appliers.

Acceptance gates:

- `cargo test -p sase_core projections::` passes.
- Reopening the same database after migrations is a no-op.
- Duplicate idempotency keys return the original event metadata or a typed duplicate result, not a second event.
- A crash-safe transaction test proves no projection metadata advance occurs without the event row.

## Phase 2B - ChangeSpec Projection

Owner: one agent after Phase 2A.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/changespec.rs`
- new ChangeSpec migration entries/files
- focused tests under `../sase-core/crates/sase_core/tests/` or module tests

Deliverables:

- Typed ChangeSpec event helpers for:
  - source file observed/reparsed;
  - spec created/updated/deleted;
  - active/archive move;
  - status transition;
  - section updates for commits, hooks, comments, mentors, timestamps, deltas.
- Projection tables:
  - `changespecs`
  - `changespec_edges`
  - `changespec_sections`
  - `changespec_search_fts`
- Projection applier that uses existing `parse_project_bytes`, `ChangeSpecWire`, section parsers, status helpers, and
  query/searchable logic.
- Query helpers for later daemon read APIs:
  - list page by status/project/updated time;
  - fetch detail by stable handle;
  - search against bounded FTS content.
- Replay tests comparing live application with replay from `event_log`.
- Fixture tests using existing `.sase` and legacy `.gp` files.

Acceptance gates:

- Live application and full replay produce byte-equivalent ChangeSpec projection rows.
- Archive/active moves leave no duplicate active row for a single ChangeSpec identity.
- Corrupt source parse events are represented as typed projection errors without poisoning the entire database.

## Phase 2C - Notification And Pending Action Projection

Owner: one agent after Phase 2A. This can run in parallel with Phase 2B if both agents only add domain files and
migrations through the agreed migration registry pattern.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/notifications.rs`
- new notification migration entries/files
- notification projection tests

Deliverables:

- Typed events for notification append/rewrite/state update and pending action register/update/cleanup.
- Projection tables:
  - `notifications`
  - `notification_pending_actions`
  - `notification_search_fts`
- Projection applier built around existing
  `notifications::{read_notifications_snapshot, apply_notification_state_update, read_pending_action_store}` behavior.
- Count/facet helpers for priority/errors/rest/muted and active/dismissed/read status.
- Replay tests for append, rewrite, dismiss, mark-read, mute/snooze, and pending action cleanup.

Acceptance gates:

- Projected notification snapshots match existing notification store parity fixtures.
- Rewrites are deterministic and do not duplicate notification IDs.
- Pending action rows can be rebuilt from events and current pending-action source files.

## Phase 2D - Agent, Artifact, Archive, And Dismissal Projection

Owner: one agent after Phase 2A. Prefer starting after Phase 2B/2C patterns settle because this is a wider surface.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/agents.rs`
- new agent/artifact/archive migration entries/files
- agent projection tests

Deliverables:

- Typed events for:
  - agent lifecycle marker observed;
  - attempt created/updated;
  - parent/child/workflow edge observed;
  - artifact associated;
  - dismissed identity changed;
  - archive bundle indexed/revived/purged.
- Projection tables:
  - `agents`
  - `agent_attempts`
  - `agent_edges`
  - `agent_artifacts`
  - `agent_archive`
  - `agent_dismissed_identities`
  - `agent_search_fts`
- Projection applier that reuses `agent_scan` and `agent_archive` records. Do not duplicate marker parsing.
- Migration path that can coexist with the existing one-off `agent_artifact_index.sqlite` until later epics decide
  whether to retire it.
- Query helpers for active/recent/archive pages, parent-child lookups, and artifact associations.

Acceptance gates:

- Projected rows match representative `agent_scan_parity` fixtures.
- Workflow parent/child edges are stable across replay.
- Dismissed and archived identities remain queryable after rebuild.

## Phase 2E - Bead Projection

Owner: one agent after Phase 2A.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/beads.rs`
- new bead migration entries/files
- bead projection tests

Deliverables:

- Typed events for bead create/update/close/reopen/remove, dependency add/remove, work-preclaim, and ready-to-work
  state.
- Projection tables:
  - `beads`
  - `bead_dependencies`
  - `bead_events`
  - optional `bead_search_fts`
- Projection applier that reuses existing `bead` JSONL import/export, mutation, schema, and work-plan helpers.
- Query helpers for list/show/ready/blocked/stats and plan hierarchy traversal.

Acceptance gates:

- Projection rows match existing bead read/storage parity fixtures.
- Dependency cycle/blocked/ready behavior matches `bead::work` and `bead::read`.
- Replaying mutation events yields the same bead state as applying them live.

## Phase 2F - Workflow, Xprompt, Memory, And File-History Catalog Projections

Owner: one agent after Phase 2A and preferably after Phase 2D.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/workflows.rs`
- `../sase-core/crates/sase_core/src/projections/catalogs.rs`
- new workflow/catalog migration entries/files
- projection tests

Deliverables:

- Typed workflow events for run created/updated, step transition, HITL pause/resume, retry, and terminal state.
- Typed catalog events for xprompt/config/memory/file-history source observed/updated/removed.
- Projection tables:
  - `workflows`
  - `workflow_steps`
  - `workflow_events`
  - `xprompt_catalog`
  - `memory_catalog`
  - `file_history`
- Projection appliers that reuse `agent_scan::WorkflowStateWire`, workflow marker parsing, `xprompt_catalog`, and editor
  file-history helper logic where it exists.
- Query helpers for workflow list/detail and catalog lookup.

Acceptance gates:

- Workflow rows preserve parent/child and step ordering across replay.
- Xprompt catalog results match existing catalog loaders for representative project/user/plugin inputs.
- Memory and file-history tables tolerate missing/deleted source files and can be invalidated cleanly.

## Phase 2G - Rebuild, Maintenance, Retention, And Property Tests

Owner: one final hardening agent after 2B-2F.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/{rebuild.rs,maintenance.rs,replay.rs}`
- projection integration/property tests

Deliverables:

- Full rebuild API:
  - drop projection tables without losing `event_log`;
  - replay all retained events;
  - optionally seed/reconcile from current source files for each domain.
- Deterministic projection/source diff structs for later daemon doctor commands.
- Gap detection on startup:
  - compare `event_log` max sequence with `projection_meta.last_seq`;
  - replay missing events;
  - report non-replayable projection versions with typed recovery guidance.
- Maintenance policy:
  - explicit WAL checkpoint API;
  - soft-cap decision helper for 1 GiB or 10-minute checkpoint trigger;
  - backup helper using SQLite `VACUUM INTO`;
  - retention/compaction helpers for high-volume ephemeral log/tick event classes.
- Property-style tests proving live application equals replay for generated valid event sequences. Add `proptest` as a
  dev-dependency if needed.
- Large-ish deterministic integration test covering a mixed sequence of ChangeSpec, notification, agent, bead, workflow,
  and catalog events.

Acceptance gates:

- Dropping projection tables and rebuilding yields the same materialized state.
- Replay repairs `projection_meta.last_seq` gaps.
- Retention keeps durable user-facing events while compacting only declared ephemeral event classes.
- Checkpoint and backup helpers are covered by tests against temporary SQLite files.

## Cross-Phase Contracts

Each phase should preserve these conventions:

- All public wire structs include `schema_version`.
- All event type strings use stable namespaced identifiers, for example `changespec.status_transitioned`.
- All stable handles include the domain and enough identity to survive path moves where possible.
- Projection appliers are deterministic and side-effect-free except for their SQLite transaction.
- Source file parsing uses existing `sase_core` domain modules.
- FTS content is bounded summaries, not unlimited raw logs.
- Errors are typed and serializable; no `String`-only public error surface for the new projection APIs.
- No phase routes production commands to the projection store.

## Suggested Verification Commands

For each Rust phase:

```bash
cargo test -p sase_core
```

For phases that touch public wire JSON:

```bash
cargo test -p sase_core python_wire_parity
```

For final integration after all phases:

```bash
cargo test --workspace
```

If any Python-facing bindings are updated in a later follow-up, that later agent should return to this repo, run
`just install`, and then run `just check`.

## Rollout Notes For Later Epics

- Epic 3 should open the same `ProjectionDb` through daemon-owned connection management.
- Epic 4 should feed file watcher observations into these event constructors in shadow mode.
- Epic 5 should expose read APIs over the query helpers only after shadow parity is proven.
- Epic 6 should append authoritative mutation events and source exports through the same transaction policy.

## Completion Definition

Epic 2 is complete when `sase_core` has a tested append-only event log, migration runner, deterministic replay/rebuild
path, and domain projections for ChangeSpecs, notifications, agents/artifacts/archive, beads, workflows, xprompts,
memory catalog, and file history. All projections must be rebuildable, all live-vs-replay tests must pass, and no
production Python/TUI command should depend on the new store yet.

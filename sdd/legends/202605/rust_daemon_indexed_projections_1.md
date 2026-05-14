---
create_time: 2026-05-13 14:43:59
status: done
prompt: sdd/prompts/202605/rust_daemon_indexed_projections_1.md
legend_bead_id: sase-3e
tier: legend
epic_count: 11
---
# Plan - Rust Daemon and Indexed Projections Performance Rebuild

## Context

The research in `sdd/research/202605/rebuild_from_scratch_performance.md` argues that SASE's largest performance wins
come from changing the runtime architecture, not from continuing to port isolated helper functions to Rust. The current
system already has the right direction: deterministic data operations live in the sibling Rust workspace `../sase-core`,
while this repo owns Python CLI/TUI orchestration, provider/plugin execution, workflow side effects, and Textual
rendering.

The proposed rebuild should preserve the current product surface:

- `sase run`, multi-agent prompts, xprompts, workflows, plan/question/HITL pauses, resume, retry, artifacts, and
  provider behavior.
- ACE views for ChangeSpecs, agents, notifications, artifacts, axe status, tags, grouping, filters, revive, cleanup,
  logs, and keyboard-first workflows.
- Axe scheduling, hooks, mentor checks, workflow checks, cleanup, digests, and background automation.
- ChangeSpec, VCS, bead, SDD, notification, mobile, editor, and plugin workflows.

The architectural bet is to extend the existing Rust `sase_gateway` into the long-lived local SASE daemon, backed by
append-only events and SQLite/WAL/FTS materialized projections. Python remains part of the product, but it should move
off hot read/render paths and become a compatibility host for providers, plugins, workflow steps, and UI glue.

This plan is intentionally split into epics. Each epic is large enough to become a durable SDD/bead workstream, and each
epic should later be split into smaller phases owned by distinct agent instances.

## Goals

- Warm daemon-backed CLI/editor queries in roughly 5-30 ms for common reads.
- ACE first useful paint under 100 ms for the shell and under 250 ms for active indexed data on large local histories.
- No broad filesystem hydration during navigation, no-change refresh, or common list/search operations.
- Agent history, ChangeSpec, notification, bead, artifact, and workflow views are paged, indexed, and streamed.
- Stateful write operations are transactional, auditable, recoverable, and still produce human-inspectable source files
  where SASE users rely on them today.
- Existing Python commands continue to work during migration through shadow mode, direct fallback paths, and
  compatibility adapters.

## Non-Goals

- Do not rewrite every SASE surface in Rust before the backend contract is fast and stable.
- Do not make SQLite projections the only source of truth. Projections must be rebuildable.
- Do not force user-authored Python/bash workflow steps or existing provider/plugin behavior into Rust.
- Do not create a second long-lived Rust service beside `sase_gateway`; extend it into one daemon process with local and
  mobile transports.
- Do not remove current source artifacts, `.sase`/`.gp` compatibility, JSONL stores, or explicit user recovery paths in
  early migration phases.

## Architectural Rules

1. Shared backend behavior goes in `../sase-core/crates/sase_core`; Python code calls through Rust bindings or daemon
   clients rather than reimplementing core logic.
2. The daemon is `../sase-core/crates/sase_gateway` evolved into a state engine with:
   - existing loopback HTTPS/SSE mobile API retained;
   - internal Unix-socket framed JSON request/response for local CLI/TUI/editor clients;
   - shared serde wire structs for both transports;
   - tokio runtime, `tracing`, and bounded `spawn_blocking` for SQLite and parsing.
3. Durable runtime state is append-only events plus rebuildable SQLite projections:
   - WAL mode with explicit checkpoint policy;
   - FTS5 for bounded searchable summaries;
   - event retention and compaction for high-volume ephemeral streams;
   - deterministic rebuild and doctor commands.
4. Hot APIs use pages, cursors, snapshot IDs, deltas, batch requests, and stable handles. They should not return "the
   whole world" as nested Python dictionaries.
5. Migration proceeds in shadow mode first: daemon indexes existing files and diff-tests its projections against current
   Python implementations before it becomes authoritative for reads or writes.

## Epic 1 - Baseline, Contracts, and Compatibility Inventory

Purpose: make the performance and functional contract explicit before building the daemon.

Deliverables:

- A compatibility matrix covering CLI, ACE, axe, ChangeSpecs, agents, artifacts, notifications, beads, workflows,
  mobile, editor helpers, providers, plugins, and recovery commands.
- Perf baselines from the existing harnesses and new command-level measurements:
  - cold Python CLI startup;
  - warm daemon round-trip target harness, initially mocked;
  - ACE first paint, j/k key-to-paint, no-change refresh, large history search;
  - agent launch fan-out and notification action latency.
- Golden fixtures for representative source stores:
  - project `.sase`/legacy `.gp`;
  - notification JSONL and pending actions;
  - agent artifact directories, dismissed identities, dismissed bundles;
  - bead stores and work-plan outputs;
  - workflow state and xprompt catalog inputs.
- A route/wire contract strategy for daemon APIs, including schema versioning and compatibility policy.

Suggested later phases:

- Phase 1A: inventory and fixtures only.
- Phase 1B: perf harnesses and thresholds.
- Phase 1C: daemon wire versioning and contract snapshot scaffolding.

Acceptance gates:

- Every later epic can point at concrete fixtures and p50/p95 targets.
- The plan records which behavior is intentionally unchanged, intentionally moved, or deferred.
- No production command is rerouted yet.

## Epic 2 - Event Model and Projection Storage Core

Purpose: define the Rust-owned state substrate that every indexed surface will share.

Primary write scope: `../sase-core/crates/sase_core`.

Deliverables:

- Canonical event envelope with schema version, sequence, timestamp, source, project/host identity, event type, payload,
  idempotency key, and causality metadata where needed.
- Event classes for:
  - ChangeSpec mutations and archive moves;
  - agent lifecycle, attempts, parent/child edges, artifacts, dismissed identities;
  - notifications and pending actions;
  - bead mutations and dependencies;
  - workflow runs, step transitions, HITL pauses, retry/resume;
  - xprompt/config/memory catalog changes;
  - high-volume ephemeral logs/ticks with retention policy.
- SQLite schema migrations and projection APIs for:
  - `changespecs`, edges, sections, search FTS;
  - `agents`, attempts, edges, artifacts, archive, dismissed identities, search FTS;
  - `notifications`, pending actions, search FTS;
  - `beads`, dependencies, bead events;
  - `workflows`, workflow steps, workflow events;
  - `xprompt_catalog`, `memory_catalog`, `file_history`;
  - `projection_meta` and `schema_migrations`.
- Transaction policy:
  - `BEGIN IMMEDIATE`;
  - append event and update projections in one transaction;
  - record `projection_meta.last_seq`;
  - replay gaps on startup;
  - full rebuild path from event logs plus source files.
- WAL/checkpoint/backup policy:
  - `journal_mode=WAL`, `synchronous=NORMAL`;
  - idle checkpoint plus 1 GiB or 10-minute soft cap;
  - daily `VACUUM INTO` snapshots;
  - bounded FTS content and log retention.

Suggested later phases:

- Phase 2A: event envelope, migrations, metadata, unit tests.
- Phase 2B: ChangeSpec and notification projections.
- Phase 2C: agent/artifact/archive projections.
- Phase 2D: bead/workflow/xprompt projections.
- Phase 2E: replay, rebuild, checkpoint, backup, and compaction.

Acceptance gates:

- Property tests prove live projection application equals replay for generated valid event sequences.
- Corrupt or stale projections can be dropped and rebuilt deterministically.
- Existing Rust-backed parser/query/notification/bead APIs are reused rather than duplicated.

## Epic 3 - Daemon Runtime, Ownership, and Local Transport

Purpose: turn `sase_gateway` into the single SASE daemon process.

Primary write scope: `../sase-core/crates/sase_gateway`, with Python lifecycle glue in this repo.

Deliverables:

- Daemon mode in `sase_gateway` with:
  - loopback/mobile API preserved;
  - Unix-socket framed JSON request/response for local clients;
  - SSE or equivalent delta stream for local and mobile subscribers;
  - shared serde request/response types from `sase_core`.
- Local ownership model:
  - PID/lock file under host-local `~/.sase/run/<hostname>/`;
  - host identity in lock metadata;
  - refusal and recovery messaging for stale or synced-conflict locks;
  - `sase daemon start|stop|status|doctor|rebuild` Python CLI wrappers.
- Runtime services:
  - open SQLite connection manager with prepared statements;
  - bounded blocking pool for SQLite/parsing;
  - tracing spans for every RPC, query, event append, projection update, and file-watch event;
  - Prometheus metrics on loopback;
  - dev `tokio-console` support.
- Client library:
  - Rust client used internally;
  - thin Python client facade for this repo;
  - direct no-daemon fallback hooks for scripts and recovery.

Suggested later phases:

- Phase 3A: process lifecycle, lock, config, health, Python `sase daemon` wrapper.
- Phase 3B: Unix-socket transport and request/response contract.
- Phase 3C: delta stream and subscription contract.
- Phase 3D: observability and metrics.
- Phase 3E: fallback and recovery behavior.

Acceptance gates:

- Only one local daemon can own a host-local state directory.
- Mobile gateway routes still pass existing contract tests.
- A local client can query health and subscribe to heartbeats without importing Textual or heavyweight Python modules.

## Epic 4 - Shadow Indexers and File Watch Ownership

Purpose: make the daemon observe current SASE files and build projections without changing behavior.

Primary write scope: `../sase-core/crates/sase_core`, `../sase-core/crates/sase_gateway`, and read-only Python
comparison helpers in this repo.

Deliverables:

- File watchers using `notify` for:
  - project `.sase` and legacy `.gp` files;
  - agent artifact directories and marker files;
  - notifications JSONL and pending action files;
  - bead JSONL/config/SQLite cache inputs;
  - xprompt/config/memory catalogs;
  - explicit artifact index files and file-history stores.
- Debounced per-source update planning:
  - update one affected agent row on marker writes;
  - reparse one project file and patch affected ChangeSpec rows;
  - update notification rows/counts on JSONL append/rewrite;
  - update bead projections on store changes;
  - reconcile periodically for missed watcher events.
- Shadow-mode diff tooling:
  - compare daemon projections against existing Python loaders;
  - report missing/stale/extra rows with source paths;
  - emit no user-visible behavior changes.
- Backfill/rebuild commands:
  - rebuild all projections from current source files;
  - rebuild one project or one surface;
  - verify projection/source equivalence.

Suggested later phases:

- Phase 4A: ChangeSpec watcher and diff.
- Phase 4B: notification watcher and diff.
- Phase 4C: agent/artifact watcher and diff.
- Phase 4D: bead/workflow/xprompt watchers and diff.
- Phase 4E: reconciliation, throttling, and large-history soak tests.

Acceptance gates:

- Shadow indexes converge on existing state for large real histories.
- No full history hydration is needed after initial backfill for ordinary file changes.
- Watcher loss or reordering is repaired by reconciliation.

## Epic 5 - Daemon-Backed Read APIs for CLI, Editor, and ACE

Purpose: move hot read paths to paged daemon queries while keeping current Python behavior as fallback.

Primary write scope: Rust API in `sase_core`/`sase_gateway`; Python facades and clients in this repo.

Deliverables:

- Read APIs shaped around pages, cursors, snapshot IDs, facets, and delta subscriptions:
  - ChangeSpec list/search/detail;
  - agent active/recent/archive list/search/detail;
  - notification list/detail/counts/pending actions;
  - bead list/show/ready/blocked/stats;
  - xprompt and editor helper catalogs;
  - artifact association and file-history reads.
- Python daemon client facades under `src/sase/core/` or a dedicated `src/sase/daemon/` package.
- CLI routing for latency-sensitive read commands:
  - `sase agents`, selected `sase changespec`, `sase notify`, editor helper, and eventually common `sase bead` reads;
  - explicit `--no-daemon` and automatic fallback on daemon unavailable/corrupt projection.
- ACE data-provider adapter:
  - initial indexed snapshots for Agents, ChangeSpecs, Notifications;
  - row patches and count patches from delta streams;
  - lazy detail/artifact loads;
  - no navigation-time I/O.
- Contract tests comparing daemon-backed output to existing Python output.

Suggested later phases:

- Phase 5A: local client facade and `sase agents`/notification reads.
- Phase 5B: ChangeSpec list/search/detail reads.
- Phase 5C: editor helper and file-history reads.
- Phase 5D: ACE Agents tab indexed provider.
- Phase 5E: ACE ChangeSpecs/Notifications providers.
- Phase 5F: bead read routing once parity is proven.

Acceptance gates:

- Warm daemon reads meet p95 targets on large synthetic fixtures.
- CLI output stays byte-compatible or has recorded intentional differences.
- ACE no-change refresh stops firing broad load spans for daemon-backed tabs.

## Epic 6 - Transactional Write APIs and Source Export Compatibility

Purpose: move state mutations into Rust transactions while preserving auditable source artifacts.

Primary write scope: `sase_core` mutation planners/projections, `sase_gateway` RPC handlers, Python command adapters.

Deliverables:

- Daemon write APIs for:
  - notification mark-read/dismiss/action response;
  - ChangeSpec status transitions, comments, hooks/mentor state, archive/revert metadata;
  - agent dismiss/cleanup/revive metadata;
  - bead mutations;
  - workflow state transitions and pending actions.
- Compatibility writer strategy:
  - each mutation appends an event;
  - updates projections transactionally;
  - writes or exports current source files/JSONL where users and older tools expect them;
  - records enough audit metadata to rebuild/export after projection loss.
- Conflict and lock behavior:
  - file locks for source exports where legacy tools may write concurrently;
  - idempotency keys for retried client calls;
  - stale-source detection and doctor repair.
- Python adapters that route existing command handlers to daemon writes when safe and preserve current direct-write
  behavior as fallback during early rollout.

Suggested later phases:

- Phase 6A: notifications and pending actions.
- Phase 6B: ChangeSpec transitions and comments.
- Phase 6C: agent cleanup/dismiss/revive metadata.
- Phase 6D: bead mutations.
- Phase 6E: workflow state writes and source export.

Acceptance gates:

- For every migrated mutation, source files and daemon projections agree after restart and rebuild.
- Retried writes are idempotent.
- Existing tests for side-effecting commands continue to pass through daemon and no-daemon modes.

## Epic 7 - Scheduler, Agent Lifecycle, and Durable Workflow Execution

Purpose: make the daemon own background orchestration and "what is running?" state.

Primary write scope: Rust daemon scheduler plus Python host adapters for subprocess/provider calls.

Deliverables:

- Agent lifecycle state machine:
  - planned, queued, starting, running, waiting, completed, failed, killed, stale;
  - attempts and parent/child/workflow edges;
  - liveness reconciliation with process markers and artifacts.
- Batch launch RPC:
  - accepts N launch specs;
  - enqueues behind semaphore with configurable concurrency;
  - returns batch handle quickly;
  - streams per-agent state events;
  - reports queued position under backpressure.
- Durable workflow scheduler:
  - graph state stored as events;
  - retries and resume as graph operations;
  - HITL steps materialize pending actions;
  - shell/Python steps run out of process with bounded logs and indexed summaries.
- Axe integration:
  - daemon-managed scheduling ticks;
  - hook/mentor/workflow/cleanup/digest jobs as queued tasks;
  - non-blocking kill, dismiss, and bulk operations.
- Python host bridge:
  - provider/plugin/VCS/workspace calls remain out of the pure Rust core;
  - host returns structured side-effect results for daemon validation and event commit.

Suggested later phases:

- Phase 7A: lifecycle read model and reconciliation.
- Phase 7B: batch launch planning/enqueue with Python host execution.
- Phase 7C: workflow transition persistence and resume/retry.
- Phase 7D: axe scheduler migration.
- Phase 7E: kill/dismiss/cleanup fan-out and backpressure.

Acceptance gates:

- `sase run` and ACE/mobile launches keep current functionality.
- Launch fan-out no longer blocks the UI thread.
- Daemon restart reconstructs running/waiting/completed state from events and source artifacts.

## Epic 8 - Plugin and Provider Host Isolation

Purpose: keep extensibility without letting Python import graphs or plugin behavior slow every command.

Primary write scope: IPC contracts in Rust, Python host process implementation in this repo.

Deliverables:

- Stable provider/plugin IPC contract:
  - request/response schemas for LLM, VCS, workspace, config/resource, xprompt, and workflow-step calls;
  - side-effect intents validated by Rust before state mutation;
  - structured logs and typed errors.
- Python host process:
  - started on demand or kept warm by daemon policy;
  - no import on pure read-query paths;
  - per-call timeout, cancellation, and log capture.
- Resource limits:
  - wall-clock timeout default 30s;
  - RSS soft cap where available;
  - cgroup v2 CPU quota on Linux where available;
  - no network unless declared by plugin manifest;
  - seccomp/sandbox profile where practical.
- Future WASM host compatibility:
  - IPC contract designed so Extism/Wasmtime can replace subprocess Python later;
  - no v1 dependency on a WASM runtime.

Suggested later phases:

- Phase 8A: provider/plugin contract inventory.
- Phase 8B: Python host subprocess with timeouts/logs.
- Phase 8C: route one low-risk provider call through host IPC.
- Phase 8D: resource limits and manifest capability checks.
- Phase 8E: migrate high-traffic provider paths selectively.

Acceptance gates:

- Hot read commands do not import plugin packages.
- Existing provider behavior remains available.
- Misbehaving plugin calls cannot starve the daemon runtime.

## Epic 9 - Incremental ACE and UI Data Virtualization

Purpose: adapt ACE to the daemon contract without prematurely rewriting the TUI.

Primary write scope: Python/Textual ACE code in this repo; optional future Rust TUI remains separate.

Deliverables:

- ACE data provider abstraction over current Python loaders and daemon-backed loaders.
- Virtualized/paged list data for Agents, ChangeSpecs, Notifications, and archive/search views.
- Delta application model:
  - row insert/update/remove;
  - count/facet patches;
  - highlight-only navigation;
  - lazy detail/artifact loads keyed by selection generation;
  - cancellable background fetches.
- Worker discipline:
  - no blocking daemon calls on the UI thread;
  - no package barrels for leaf editor/helper paths;
  - full-detail rendering after debounce/idle.
- Perf gates integrated with existing TUI trace harness.
- Decision checkpoint for Ratatui:
  - only after backend contracts are stable;
  - treat as optional shell replacement, not a prerequisite for daemon benefits.

Suggested later phases:

- Phase 9A: data-provider abstraction and daemon snapshot plumbing.
- Phase 9B: Agents tab pages/deltas/lazy detail.
- Phase 9C: ChangeSpecs tab pages/deltas/query handles.
- Phase 9D: Notifications/artifacts/archive/search views.
- Phase 9E: remove broad refresh fallbacks and enforce perf gates.

Acceptance gates:

- j/k key-to-paint and highlight spans stay within current runbook targets.
- No-change auto-refresh performs no broad data reload for daemon-backed tabs.
- ACE remains functional when daemon is unavailable by falling back to current loaders.

## Epic 10 - Multi-Machine Sync, Recovery, and Operations

Purpose: make the daemon safe for users who sync `~/.sase/` and for histories that have years of artifacts.

Primary write scope: daemon storage layout, doctor/rebuild commands, docs.

Deliverables:

- Host-local runtime layout:
  - projections, WAL, lock files, high-volume logs under `~/.sase/run/<hostname>/` or equivalent;
  - synced source files remain in the existing user-visible tree;
  - clear exclusion guidance for Syncthing/rclone.
- Recovery tools:
  - `sase daemon doctor`;
  - `sase daemon rebuild`;
  - projection/source diff report;
  - stale lock repair;
  - backup restore from `VACUUM INTO` snapshots.
- Sync chaos tests:
  - corrupt lock file;
  - two hosts racing against a shared source tree;
  - projection deletion and rebuild;
  - reordered file events.
- Documentation:
  - storage model;
  - backup/rebuild;
  - multi-machine recommendations;
  - fallback/no-daemon usage.

Suggested later phases:

- Phase 10A: storage layout and docs.
- Phase 10B: doctor/rebuild/backup commands.
- Phase 10C: sync chaos tests.
- Phase 10D: migration guide and user-facing diagnostics.

Acceptance gates:

- No daemon writes SQLite databases into directories expected to sync across hosts.
- Projection corruption is recoverable without losing source artifacts.
- User-facing errors explain exactly which command repairs the problem.

## Epic 11 - Release Sequencing and Rollout Controls

Purpose: make adoption incremental and reversible.

Deliverables:

- Feature flags/config:
  - daemon disabled;
  - shadow mode;
  - read-through daemon;
  - write-through daemon;
  - daemon-authoritative.
- Version compatibility:
  - Python package checks daemon/core schema version;
  - daemon rejects incompatible clients with actionable errors;
  - migration steps are explicit and idempotent.
- Rollout milestones:
  - M0: daemon can shadow-index and report diffs.
  - M1: daemon read APIs power selected CLI/editor commands.
  - M2: ACE reads from daemon for Agents/Notifications/ChangeSpecs.
  - M3: selected writes move to daemon with source export.
  - M4: scheduler/launch/workflow state becomes daemon-owned.
  - M5: Python is provider/plugin/workflow host plus compatibility fallback.
- CI and release gates:
  - Rust unit/property tests;
  - Python compatibility tests;
  - end-to-end daemon/CLI tests;
  - perf benchmark snapshots;
  - mobile gateway contract snapshots.

Acceptance gates:

- Users can opt out or recover at each milestone.
- No milestone requires deleting existing state.
- Every authoritative migration has a preceding shadow parity phase.

## Dependency Order

1. Epic 1 must land first enough to provide fixtures and perf gates.
2. Epic 2 and Epic 3 can proceed in parallel once wire/versioning policy is agreed.
3. Epic 4 depends on initial storage and daemon lifecycle.
4. Epic 5 depends on shadow projections for the migrated surface.
5. Epic 6 depends on event transactions and read parity for each surface.
6. Epic 7 depends on write events and host IPC shape.
7. Epic 8 can start contract design early, but high-traffic migration should wait for daemon scheduling/backpressure.
8. Epic 9 should start after the daemon read API for a tab exists.
9. Epic 10 starts early for storage layout decisions and continues through all phases.
10. Epic 11 wraps every milestone.

## Cross-Epic Testing Strategy

- Unit tests for parser, planner, event, projection, and migration functions.
- Golden contract tests comparing Python and daemon outputs.
- Property tests for event replay equivalence.
- Deterministic daemon simulation tests with crash, slow I/O, reordered watcher events, and concurrent clients.
- Soak tests with at least:
  - 1M events;
  - 100k agents;
  - 5k ChangeSpecs;
  - large notification and artifact stores;
  - bounded FTS indexes.
- End-to-end perf gates aligned with `docs/perf_runbook.md`.
- Sync chaos tests for host-local projection safety.

## First Concrete Work Package

The first implementation work should not start by moving a user command. It should create the substrate needed for safe
parallelization:

1. Add Epic 1 fixtures/perf baselines and a daemon contract skeleton.
2. Add Epic 2 event envelope, projection metadata, and migration runner in `sase_core`.
3. Add Epic 3 daemon lifecycle/health/lock/local transport in `sase_gateway`.
4. Add a shadow ChangeSpec or notification projection as the first vertical slice.
5. Diff that projection against the current Python implementation before any read path uses it.

That vertical slice proves the architecture, migration mechanics, and testing approach without risking the full product
surface.

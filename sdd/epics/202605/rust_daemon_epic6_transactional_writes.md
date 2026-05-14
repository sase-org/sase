---
create_time: 2026-05-14 00:51:51
status: wip
prompt: sdd/prompts/202605/rust_daemon_epic6_transactional_writes.md
bead_id: sase-3e.6
tier: epic
legend_bead_id: sase-3e
---
# Plan - Rust Daemon Epic 6 Transactional Writes

## Context

Epic 6 from `sdd/legends/202605/rust_daemon_indexed_projections_1.md` moves selected SASE state mutations behind the
Rust daemon while preserving the source files and JSON stores that users and older tools still inspect directly.

Primary implementation scope spans two repositories:

- `../sase-core/crates/sase_core`: mutation planners, event payloads, projection application, source-export planning.
- `../sase-core/crates/sase_gateway`: local daemon write RPC handlers, capability advertising, metrics, contract
  snapshots.
- this repo: Python daemon write client/facades plus conservative command adapters with direct-write fallback.

Current useful substrate:

- `sase_core::projections` already has event envelopes, idempotency keys, projection migrations, replay, rebuild, and
  domain projection modules.
- `ProjectionDb::append_projected_event` already applies an event and projection update inside `BEGIN IMMEDIATE`.
- `sase_gateway::ProjectionService::write` already runs projection writes on the blocking pool.
- Local daemon framed JSON currently supports health, capabilities, reads, events, rebuild/verify/diff, and batch.
- Python read facades already have the desired fallback shape: try daemon when the capability exists, otherwise direct
  source-store behavior.

Important constraint: SQLite and filesystem source exports cannot be made a single atomic transaction. Epic 6 should
therefore introduce an explicit source-export journal/outbox and make daemon writes return success only after required
exports are applied or safely recorded for retry/doctor repair.

## Goals

- Route selected writes through daemon APIs without removing current direct-write fallbacks.
- Preserve human-readable source stores: notification JSONL, pending action JSON, `.sase`/`.gp`, dismissed agent files,
  bead stores, and workflow request/response/state files.
- Guarantee idempotent retries by client-provided idempotency keys and stable mutation payloads.
- Keep daemon projections, event log, and exported source files convergent after restart, rebuild, and doctor repair.
- Keep host side effects in Python where they belong: process kills, provider/plugin subprocesses, shell/Python workflow
  execution, and VCS side effects.

## Non-Goals

- Do not make daemon writes authoritative for every command in one phase.
- Do not delete direct Python source-store writers during Epic 6.
- Do not move provider, plugin, VCS, process-kill, or shell execution side effects into Rust.
- Do not route a write surface before that same surface has read parity and shadow/index verification from earlier
  epics.
- Do not rely on daemon-only SQLite state as the only recovery source.

## Cross-Phase Design

Every daemon write should follow the same shape:

1. Validate capability, schema version, request shape, actor/client metadata, and idempotency key.
2. Load current projection rows and source fingerprints needed by the mutation planner.
3. Plan one semantic domain event plus one or more source exports.
4. Under `BEGIN IMMEDIATE`, append the event, apply the projection, and record pending source-export rows with expected
   source fingerprints, target paths, export kind, content hash, and repair metadata.
5. Apply source exports under per-file locks using temp-file plus fsync/rename semantics or append-only locked writes as
   appropriate for the source store.
6. Mark export rows applied in a follow-up transaction. If this step crashes, retry/doctor must detect and complete the
   pending export.
7. Return a typed mutation response containing event seq, duplicate flag, changed flag, source export report, and any
   fallback/repair guidance.

Common wire concepts should be introduced once:

- `LocalDaemonWriteRequestWire` and `LocalDaemonWriteResponseWire`.
- `LocalDaemonMutationOutcomeWire` with `event_seq`, `event_type`, `duplicate`, `changed`, `resource_handle`,
  `source_exports`, and optional `projection_snapshot`.
- `MutationActorWire`, `MutationConflictWire`, `SourceFingerprintWire`, `SourceExportPlanWire`, and
  `SourceExportReportWire`.
- Error codes for `conflict_stale_source`, `export_pending_repair`, `idempotency_conflict`, `host_adapter_required`,
  `unsupported_mutation`, and `source_lock_busy`.

The source-export journal can live in projection storage as migration-owned tables:

- `source_export_outbox`
- `source_export_attempts`

The outbox is not a new source of truth. It is a recovery mechanism that lets retry, daemon startup repair, and
`sase daemon doctor` reconcile event/projection state with source files after a crash or legacy-writer race.

## Phase 6A - Write Contract, Outbox, And Python Facade

Owner: one agent.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/{event.rs,db.rs,migrations.rs,replay.rs,rebuild.rs}`
- new `../sase-core/crates/sase_core/src/projections/mutations.rs` or equivalent shared module
- `../sase-core/crates/sase_gateway/src/{wire.rs,local_transport.rs,contract.rs,projection_service.rs,metrics.rs}`
- new Python daemon write facade under `src/sase/daemon/`
- focused contract/unit tests only

Deliverables:

- Add local daemon write request/response wire types and contract snapshot entries.
- Add shared mutation outcome, source fingerprint, conflict, and source-export report records.
- Add source-export outbox migrations plus Rust helpers for enqueue, mark applied, mark failed, list pending, and retry
  one pending export.
- Add reusable locked source-export primitives for atomic JSON/JSONL/project-file writes, but do not yet use them for
  production command routing.
- Add `LocalDaemonClient.write_*` plumbing and a Python `write_or_fallback` helper mirroring the read facade.
- Advertise only a conservative foundation capability such as `writes.contract`; do not advertise surface write
  capabilities until their vertical phase lands.
- Add deterministic tests for idempotency, stale-source conflict shape, outbox retry after simulated crash, and contract
  snapshot stability.

Acceptance gates:

- Rust tests prove duplicate idempotency keys return the original mutation outcome.
- A simulated crash after event/projection commit but before export can be repaired by retrying the outbox.
- Unsupported write surfaces produce typed fallbackable errors.
- No existing production command is rerouted yet.

Suggested phase prompt:

> Implement Phase 6A from `sase_plan_rust_daemon_epic6_transactional_writes.md`: add the shared local-daemon write
> contract, source-export outbox, repair primitives, and Python write facade scaffolding. Do not route any production
> writes yet.

## Phase 6B - Notifications And Pending Actions

Owner: one agent after Phase 6A.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/notifications.rs`
- `../sase-core/crates/sase_core/src/notifications/{store.rs,pending_actions.rs,wire.rs}`
- `../sase-core/crates/sase_gateway/src/{local_transport.rs,wire.rs,contract.rs}`
- `src/sase/notifications/{store.py,pending_actions.py,daemon_writes.py}`
- notification CLI/mobile helper tests

Deliverables:

- Daemon write mutations for notification append, mark-read, dismiss, mute, snooze, expire-snoozes, bulk dismiss, and
  pending-action register/update/cleanup.
- Source exports for `~/.sase/notifications/notifications.jsonl` and `~/.sase/pending_actions/actions.json`, using
  existing Rust notification store behavior where possible.
- Python notification adapters that route through daemon only when `notifications.write` is advertised and fall back to
  current direct writes on daemon unavailable, unsupported capability, or explicit `--no-daemon`/`SASE_NO_DAEMON`.
- Pending-action response writes should preserve current plan/HITL/question side-effect files; this phase may record the
  action state mutation but should leave workflow execution side effects to Phase 6F.
- Contract tests comparing daemon write output, source files, and projected notification reads.

Acceptance gates:

- `mark_read`, `mark_dismissed`, bulk dismiss, snooze, and pending-action cleanup are idempotent.
- After daemon restart and projection rebuild, notification JSONL, pending action source JSON, and projection rows
  agree.
- Existing notification tests pass in no-daemon mode and daemon-write mode.

Suggested phase prompt:

> Implement Phase 6B from `sase_plan_rust_daemon_epic6_transactional_writes.md`: route notification and pending-action
> mutations through the daemon write contract with source export and direct fallback.

## Phase 6C - ChangeSpec Status And Comments

Owner: one agent after read parity exists for ChangeSpecs and Phase 6A lands.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/changespec.rs`
- relevant Rust status/project-spec helpers
- `../sase-core/crates/sase_gateway/src/{local_transport.rs,wire.rs,contract.rs}`
- `src/sase/status_state_machine/field_updates.py`
- `src/sase/ace/comments/operations.py`
- `src/sase/daemon/changespec_writes.py`
- ChangeSpec command/ACE tests

Deliverables:

- Daemon write mutations for status transitions, CL/parent/bug/description field updates, and comment section updates.
- A source-export planner for `.sase` and legacy `.gp` project files that preserves formatting where the current Python
  helpers preserve it and records intentional formatting differences.
- Python adapters for the existing status and comment write helpers.
- Conflict detection using source fingerprints and ChangeSpec identity handles, with direct fallback only when the
  daemon declines before appending an event.

Acceptance gates:

- Existing side-effecting ChangeSpec status/comment tests pass through daemon and no-daemon modes.
- Replayed events reproduce the same projected status/comment rows as live application.
- Stale project-file edits produce a typed conflict rather than overwriting legacy changes.

Suggested phase prompt:

> Implement Phase 6C from `sase_plan_rust_daemon_epic6_transactional_writes.md`: daemon-backed ChangeSpec status,
> metadata, and comment writes with `.sase`/`.gp` source export and fallback.

## Phase 6D - ChangeSpec Hooks, Mentors, Archive, And Revert Metadata

Owner: one agent after Phase 6C.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/changespec.rs`
- `src/sase/ace/hooks/{persistence.py,processes.py}`
- `src/sase/ace/mentors/status.py`
- `src/sase/ace/archive.py`
- `src/sase/ace/revert.py`
- focused tests for hooks, mentors, archive/revert metadata

Deliverables:

- Daemon mutations for hooks field updates, hook status suffix updates, mentor field updates, mentor read/acceptance
  metadata where it belongs in ChangeSpec source, archive moves, and revert metadata.
- Preserve Python host side effects for killing hook/mentor/comment agents; daemon writes only own durable metadata and
  projection events.
- Source exports for active/archive project files with lock ordering that avoids deadlocks when a mutation touches both.
- Adapters for ACE handlers that currently mutate hook/mentor/archive/revert metadata directly.

Acceptance gates:

- Archive and revert metadata remain recoverable from source files and projections after restart/rebuild.
- Hook/mentor process side effects are still performed by Python and are not hidden inside Rust transactions.
- Tests cover lock ordering for active/archive file pairs.

Suggested phase prompt:

> Implement Phase 6D from `sase_plan_rust_daemon_epic6_transactional_writes.md`: daemon-backed ChangeSpec hook, mentor,
> archive, and revert metadata writes while keeping process/VCS side effects in Python.

## Phase 6E - Agent Dismiss, Cleanup, Archive, And Revive Metadata

Owner: one agent after agent read parity exists and Phase 6A lands.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/agents.rs`
- Rust agent archive/dismissed records
- `../sase-core/crates/sase_gateway/src/{local_transport.rs,wire.rs,contract.rs}`
- `src/sase/ace/dismissed_agents*.py`
- `src/sase/core/agent_cleanup*.py`
- ACE agent dismiss/cleanup/revive tests

Deliverables:

- Daemon mutations for dismissed identity add/remove, dismissed bundle save/index/revive/purge metadata, artifact
  association metadata, and cleanup-result metadata.
- Keep actual process termination, workspace cleanup, and host filesystem deletion decisions in current Python host
  adapters unless they are already pure metadata writes.
- Source exports for `dismissed_agents.json`, dismissed bundle shards, explicit artifact index files, and any cleanup
  marker files covered by the mutation.
- Python adapters that use daemon writes when `agents.write` or narrower capabilities are advertised.

Acceptance gates:

- Dismiss/revive operations are idempotent across retries and daemon restarts.
- Existing dismissed bundle migration/index tests continue to pass.
- Daemon projections and dismissed source files agree after rebuild.

Suggested phase prompt:

> Implement Phase 6E from `sase_plan_rust_daemon_epic6_transactional_writes.md`: daemon-backed agent dismissal, cleanup,
> archive, revive, and artifact metadata writes with source export.

## Phase 6F - Bead Mutations

Owner: one agent after bead read parity exists and Phase 6A lands.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/beads.rs`
- `../sase-core/crates/sase_core/src/bead/{mutation.rs,jsonl.rs,wire.rs}`
- `../sase-core/crates/sase_gateway/src/{local_transport.rs,wire.rs,contract.rs}`
- `src/sase/core/bead_mutation_facade.py`
- `src/sase/bead/project.py`
- bead CLI/mobile helper tests

Deliverables:

- Daemon mutations for create, update, close, remove, dependency add/remove, ready-to-work changes, and preclaim epic
  work.
- Reuse current Rust bead mutation logic as the source exporter; do not reimplement bead semantics in Python or gateway.
- Record bead mutation events and update bead projections transactionally before exporting source JSONL/cache files.
- Route bead command helpers through daemon writes only when `beads.write` is advertised, with direct Rust binding
  fallback preserved.

Acceptance gates:

- Existing bead mutation tests pass through direct mode and daemon mode.
- Event replay yields the same bead projection as the current bead source store.
- Preclaim rollback metadata remains available for failed multi-agent phase assignment flows.

Suggested phase prompt:

> Implement Phase 6F from `sase_plan_rust_daemon_epic6_transactional_writes.md`: daemon-backed bead mutations using the
> existing Rust bead mutation engine plus source export and fallback.

## Phase 6G - Workflow State, HITL, Questions, And Action Responses

Owner: one agent after notification pending-action writes and workflow projections are stable.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/workflows.rs`
- workflow/action wire records in `sase_core`
- `../sase-core/crates/sase_gateway/src/{local_transport.rs,wire.rs,contract.rs,host_bridge.rs,routes.rs}`
- `src/sase/xprompt/workflow_*.py`
- `src/sase/notifications/pending_actions.py`
- workflow, plan approval, HITL, and question tests

Deliverables:

- Daemon mutations for workflow run created/updated, step transitioned, HITL paused/resumed, retry requested, terminal
  state reached, and pending-action response state.
- Source exports for workflow state files, HITL request/response files, plan response files, and question response
  files.
- Preserve script/provider execution in Python host adapters; Rust records durable workflow state and validates response
  transitions.
- Align mobile action endpoints and local daemon writes so they share the same mutation planner where practical.

Acceptance gates:

- Plan approval, HITL, and user-question responses remain idempotent and cannot be applied twice.
- A daemon restart during a workflow pause can recover pending action state and source response files.
- Existing workflow tests pass with direct fallback and daemon-write routing.

Suggested phase prompt:

> Implement Phase 6G from `sase_plan_rust_daemon_epic6_transactional_writes.md`: daemon-backed workflow state and
> action-response writes while keeping execution side effects in Python host adapters.

## Phase 6H - Rollout Gates, Doctor Repair, And Documentation

Owner: one final integration agent after Phases 6B-6G.

Primary write scope:

- `../sase-core/crates/sase_core/src/projections/{maintenance.rs,rebuild.rs}`
- `../sase-core/crates/sase_gateway/src/{local_transport.rs,contract.rs,daemon.rs}`
- `src/sase/integrations/daemon_lifecycle*.py`
- CLI docs/help, SDD close-out notes, and integration tests

Deliverables:

- `sase daemon doctor` and `sase daemon rebuild` output that reports pending/failed source exports by surface and can
  retry safe pending exports.
- A capability rollout matrix documenting which write surfaces are daemon-routed, fallbackable, or still direct-only.
- End-to-end tests for daemon unavailable, unsupported capability, stale source conflict, crash-before-export repair,
  and no-daemon escape hatch.
- Update contract snapshots and any operator docs that describe write-through daemon behavior.
- Performance sanity checks for common writes so no single write path introduces broad hydration.

Acceptance gates:

- Every migrated write has tests proving source/projection agreement after restart and rebuild.
- Doctor can explain and repair pending source exports or produce an actionable conflict report.
- Users can opt out with `--no-daemon`/`SASE_NO_DAEMON` for every migrated CLI surface during rollout.

Suggested phase prompt:

> Implement Phase 6H from `sase_plan_rust_daemon_epic6_transactional_writes.md`: close Epic 6 with doctor/rebuild repair
> gates, rollout documentation, contract updates, and cross-surface daemon/no-daemon verification.

## Dependency Graph

- Phase 6A is first and blocks all other Epic 6 work.
- Phase 6B can start immediately after 6A and is the recommended first vertical slice.
- Phase 6C and 6E can run in parallel after 6A if ChangeSpec and agent read parity exists; otherwise wait for the
  corresponding Epic 5 surface.
- Phase 6D depends on 6C because it shares ChangeSpec project-file export semantics.
- Phase 6F can run after 6A and bead read parity.
- Phase 6G depends on 6B and workflow projection/read readiness.
- Phase 6H runs last.

## Verification Strategy

Each phase should run the narrowest useful checks in both affected repos. For this repo, run `just install` before
repo-level checks if the workspace has not been prepared recently.

Minimum per vertical phase:

- Rust package tests for touched `sase_core` and `sase_gateway` modules.
- Python focused tests for the adapted command/helper surface.
- Contract snapshot tests when wire/capability shape changes.
- Daemon-mode and no-daemon/fallback tests for every Python adapter introduced in that phase.

Epic close-out should add or run:

- crash-before-export simulation;
- duplicate idempotency retry simulation;
- stale-source conflict simulation;
- restart and projection rebuild agreement checks;
- representative command tests for notifications, ChangeSpecs, agents, beads, and workflows.

## Risks

- Cross-store atomicity is impossible without the source-export outbox. Do not skip Phase 6A.
- Legacy writers may not all use the same file locks today. Each vertical phase should either update its direct writer
  to share the lock or mark the daemon route unsafe for that operation.
- Some current helpers mix metadata writes with host side effects. The phase agents must split these so Rust owns only
  durable metadata and Python keeps side effects.
- ChangeSpec project-file formatting compatibility is likely the hardest source-export problem. Keep status/comment work
  separate from hooks/mentors/archive so failures do not block lower-risk surfaces.
- Capability advertising must lag implementation until fallback and parity tests exist; otherwise Python adapters will
  accidentally route users onto incomplete daemon writes.

---
create_time: 2026-05-14 02:30:59
status: done
prompt: sdd/prompts/202605/epic7_daemon_scheduler_phases.md
bead_id: sase-3e.7
tier: epic
legend_bead_id: sase-3e
---
# Epic 7 Plan - Daemon Scheduler, Agent Lifecycle, and Durable Workflow Execution

## Context

Epic 7 from `sdd/legends/202605/rust_daemon_indexed_projections_1.md` makes the daemon own background orchestration and
"what is running?" state. It should not start by replacing every Python execution path. The existing codebase already
has important pieces to preserve:

- Rust projection/event scaffolding exists for agents and workflows in `../sase-core/crates/sase_core/src/projections/`.
- `sase_gateway` already has projection service plumbing, local transport write surfaces, mobile launch/kill/retry host
  bridge hooks, and workflow write handling.
- Python launch code already centralizes fan-out through `src/sase/agent/launch_executor.py`, low-level subprocess spawn
  through `src/sase/agent/launch_spawn.py`, and repeat/multi-prompt planning through Rust-backed facades.
- Workflow execution remains Python-owned and already writes `workflow_state.json` through daemon-backed helpers in
  `src/sase/xprompt/workflow_daemon_writes.py`.
- Axe orchestration still lives in Python under `src/sase/axe/` and `src/sase/ace/scheduler/`, with cross-process
  concurrency coordinated by files and PID/source markers.

The right migration shape is therefore a staged authority transfer: first make the daemon able to model and reconcile
lifecycle state, then enqueue launches through a durable batch contract while Python remains the host for subprocesses,
then make workflows and axe scheduling durable tasks, and only then route high-volume UI/mobile/CLI operations to the
daemon scheduler by default.

## Goals

- Preserve current `sase run`, ACE launches, mobile launches, retry/resume, HITL, workflow, axe, kill/dismiss/cleanup,
  and provider/plugin behavior throughout migration.
- Move lifecycle truth for queued/running/waiting/completed/failed/killed/stale state into daemon events and
  projections.
- Make launch fan-out non-blocking from CLI, ACE, and mobile by returning batch handles quickly and streaming per-agent
  state transitions.
- Replace file-counter based axe scheduling with daemon-managed task queues and backpressure.
- Keep Python as the host for provider, plugin, VCS, workspace, shell, and Python step side effects.
- Keep no-daemon fallback paths available until parity and recovery behavior are proven.

## Non-Goals

- Do not reimplement provider/plugin execution in Rust.
- Do not remove existing artifact/source files during this epic.
- Do not make ACE depend on scheduler migration before daemon-backed reads remain available.
- Do not collapse all agent/workflow/axe behavior into one giant phase; each phase must be independently handoffable.

## Phase 7A - Lifecycle Event Model, Read Model, and Reconciliation

Purpose: give later phases a durable lifecycle substrate without routing launches yet.

Primary ownership:

- `../sase-core/crates/sase_core/src/projections/agents.rs`
- `../sase-core/crates/sase_core/src/projections/workflows.rs`
- `../sase-core/crates/sase_gateway/src/projection_service.rs`
- focused Python comparison helpers under `src/sase/agents/` or `src/sase/daemon/`

Deliverables:

- Extend the agent projection model with explicit daemon-owned lifecycle transitions: `planned`, `queued`, `starting`,
  `running`, `waiting`, `completed`, `failed`, `killed`, and `stale`.
- Add attempt lineage and edge fields needed by scheduler-owned launch batches: batch id, queue id, parent agent,
  workflow id, retry/resume lineage, host id, pid, artifact dir, workspace claim identity, and last heartbeat/check
  time.
- Add workflow/agent edge projection support sufficient to reconstruct parent/child/workflow trees after daemon restart.
- Add liveness reconciliation APIs that compare projections with process markers, `running.json`, `waiting.json`,
  `done.json`, workspace claims, and `workflow_state.json`, then emit repair/stale events instead of silently patching
  in memory.
- Add read APIs for lifecycle pages and individual lifecycle records that are independent of ACE rendering models.
- Add shadow diff tests against current Python `list_running_agents()`, `list_all_agents()`, and workflow state loaders.
  - Python comparison helper: `compare_lifecycle_classifications`.

Acceptance gates:

- Rebuild from existing source artifacts produces the same running/waiting/done/failed classification as current Python
  loaders for Epic 1 fixtures and at least one larger synthetic fixture.
- Reconciliation is idempotent and emits no duplicate lifecycle events for unchanged state.
- Daemon restart can reconstruct lifecycle rows without importing Textual or scanning unrelated source surfaces.

## Phase 7B - Scheduler Queue Core and Batch Launch RPC Skeleton

Purpose: introduce daemon-owned queues, handles, backpressure, and event streaming without executing real agents yet.

Primary ownership:

- `../sase-core/crates/sase_core` scheduler wire/types and deterministic queue state transitions
- `../sase-core/crates/sase_gateway` local transport handlers, in-memory scheduler service, and projection integration
- Python client models under `src/sase/daemon/`

Deliverables:

- Define shared wire structs for launch specs, batch submission, batch status, queue position, cancellation request,
  scheduler task id, and scheduler event stream records.
- Add a durable scheduler queue model backed by events and projections:
  - batch submitted;
  - slot planned;
  - slot queued;
  - slot dequeued/starting;
  - slot running;
  - slot terminal;
  - slot cancelled/killed/stale.
- Add configurable scheduler concurrency settings with defaults mapped from existing agent/axe limits.
- Add a batch launch RPC that accepts N launch specs, records queued slots transactionally, returns a batch handle
  quickly, and publishes lifecycle deltas without spawning subprocesses yet.
- Add queue recovery on daemon restart: queued tasks remain queued, starting tasks are reconciled to stale unless a host
  bridge confirms a process, terminal tasks remain terminal.
- Add unit/simulation tests for queue ordering, backpressure, idempotent batch submit, cancellation, and restart replay.

Acceptance gates:

- Batch submit p95 is bounded by DB transaction time, not by number of eventual agents.
- Duplicate submit with the same idempotency key returns the same batch handle and does not duplicate queued slots.
- Queue status reports stable queued position under concurrency pressure.

## Phase 7C - Python Host Execution Bridge for Agent Launches

Purpose: connect daemon queue slots to the existing Python subprocess launch implementation while keeping side effects
in Python.

Primary ownership:

- `../sase-core/crates/sase_gateway/src/host_bridge.rs` or a new scheduler host bridge module
- `src/sase/agent/launch_executor.py`
- `src/sase/agent/launch_spawn.py`
- `src/sase/integrations/_mobile_agent_launch.py`
- `src/sase/daemon/` Python scheduler client/bridge helpers

Deliverables:

- Add a host bridge operation for `prepare-launch-slot` and `execute-launch-slot` that calls existing Python launch
  planning/spawn code and returns structured results: pid, workspace claim, artifact dir, output path, workflow name,
  timestamp, agent name when known, and typed failure information.
- Ensure the daemon commits lifecycle events only after validating host results against the submitted slot and expected
  source/export plans.
- Preserve existing workspace claim, deferred workspace, retry transfer, planned-name, `%wait`, `%resume`, `%repeat`,
  and `%alt` behavior by reusing existing Python planners instead of duplicating them in Rust.
- Add kill/cancel handoff from daemon scheduler to Python process management while keeping the existing direct
  `kill_named_agent()` path as fallback.
- Add contract tests with fake host bridge implementations, plus Python tests that daemon launch requests produce the
  same `LaunchSpawnRequest`/`AgentLaunchResult` shape as direct launch.

Acceptance gates:

- A daemon-queued single-agent launch reaches `running` and then terminal state with the same artifact/source files as a
  direct launch.
- Host launch failure produces a durable failed lifecycle event with enough details for CLI/mobile/ACE display.
- Existing mobile launch/kill/retry routes can use the scheduler host bridge in shadow or opt-in mode.

## Phase 7D - Route `sase run`, ACE, and Mobile Launches Through Batch Scheduler

Purpose: move user-facing launch fan-out to daemon queues behind rollout flags, while preserving direct fallback.

Primary ownership:

- `src/sase/main/` run and mobile bridge handlers
- `src/sase/agent/launch_cwd.py`, `multi_prompt_launcher.py`, `repeat_launcher.py`, and launch facades
- ACE launch action code under `src/sase/ace/tui/`
- daemon client/read/write modules under `src/sase/daemon/`

Deliverables:

- Add feature flags/config for direct, shadow, and daemon-authoritative scheduler modes.
- Route `sase run` batch launch plans to daemon submit when enabled; keep direct execution as fallback for unavailable
  daemon, unsupported request shape, or recovery mode.
- Route ACE launch actions through the same batch client without blocking the UI thread; ACE receives a batch handle and
  lifecycle deltas instead of waiting for every subprocess spawn.
- Route mobile text/image launch through the scheduler batch path and return handle/status fields compatible with
  current mobile responses.
- Preserve rollback on partial multi-prompt launch: in daemon mode, partial failure becomes batch terminal state plus
  per-slot kill/cancel events rather than ad hoc cleanup in the caller.
- Add end-to-end tests for direct vs daemon launch parity across single prompt, multi-prompt, repeat, `%alt`/`%model`,
  `%wait`, retry, and mobile launch.

Acceptance gates:

- Launch fan-out no longer blocks ACE or mobile request handlers on N subprocess spawns.
- Existing command output and artifact layout remain compatible, or intentional differences are recorded in tests.
- Turning the scheduler flag off restores current direct launch behavior.

## Phase 7E - Durable Workflow Transition Scheduler and HITL Resume/Retry

Purpose: make workflow graph state durable scheduler state while Python continues executing steps.

Primary ownership:

- `../sase-core/crates/sase_core/src/projections/workflows.rs`
- `../sase-core/crates/sase_gateway` workflow scheduler/task handlers
- `src/sase/xprompt/workflow_executor*.py`
- `src/sase/xprompt/workflow_daemon_writes.py`
- `src/sase/xprompt/workflow_hitl.py`

Deliverables:

- Extend workflow events so every step transition has an explicit scheduler cause and stable workflow id/step id.
- Add daemon task records for workflow run, step start, step complete, HITL pause, HITL response, retry request, resume
  request, and terminal state.
- Make `TUIHITLHandler` materialize pending actions through daemon write APIs before falling back to response files.
- Add workflow resume/retry operations as graph operations, not just process/file re-launches.
- Add bounded log capture and indexed summaries for shell/Python steps while keeping actual shell/Python execution in a
  host process.
- Add deterministic replay tests for workflow graphs with success, failed step, finally step, HITL pause/resume,
  feedback/rerun, and retry.

Acceptance gates:

- Daemon restart reconstructs running, waiting, paused, completed, and failed workflow state from events plus source
  artifacts.
- HITL pending actions survive daemon restart and are resolved exactly once.
- Workflow direct mode still functions when daemon workflow scheduling is disabled.

## Phase 7F - Axe Scheduler Migration

Purpose: replace the Python multi-process axe supervisor/counter loop with daemon-managed scheduled tasks while reusing
existing chop, hook, mentor, workflow, cleanup, and digest execution functions.

Primary ownership:

- `../sase-core/crates/sase_gateway` scheduled task service
- `src/sase/axe/orchestrator.py`, `src/sase/axe/chop_runner.py`, `src/sase/axe/runner_pool.py`
- `src/sase/ace/scheduler/`
- `src/sase/ace/hooks/`
- `src/sase/workflows/mentor.py`

Deliverables:

- Model axe ticks, lumberjack checks, chops, hook jobs, mentor checks, cleanup jobs, and digest jobs as daemon scheduler
  tasks with typed task keys and dedupe policies.
- Replace file-based runner counters with daemon queue backpressure and durable per-task state.
- Add host bridge operations that call existing `run_configured_chop_once()`, hook execution, workflow
  starter/completer, mentor, cleanup, and digest code.
- Preserve `sase axe start|stop|status`, initially as wrappers around daemon scheduler enable/disable/status with direct
  orchestrator fallback.
- Make manual ACE/CLI chop runs submit one scheduler task and render task state from daemon projections.
- Add migration tests for scheduled chop dedupe, script timeout, agent chop launch, stale runner recovery, lumberjack
  restart semantics, and `sase axe stop`.

Acceptance gates:

- Existing axe CLI/TUI behavior remains available.
- Scheduled jobs are not double-started across daemon restart or concurrent clients.
- Backpressure is visible in scheduler status instead of silently skipping work.

## Phase 7G - Kill, Dismiss, Cleanup, Revive, and Bulk Operations

Purpose: move high-fan-out lifecycle mutations onto scheduler events and queues.

Primary ownership:

- `../sase-core/crates/sase_core/src/agent_cleanup/`
- `../sase-core/crates/sase_core/src/projections/agents.rs`
- `../sase-core/crates/sase_gateway` scheduler/write handlers
- `src/sase/agents/cli_kill.py`, `src/sase/daemon/agent_writes.py`
- ACE agent action handlers and cleanup modals

Deliverables:

- Add daemon scheduler operations for kill, dismiss, cleanup, revive, and bulk kill/dismiss.
- Ensure non-blocking bulk operations enqueue one task per target with aggregate batch status and per-target errors.
- Route existing source export compatibility through daemon writes for dismissed identities, cleanup results, archive
  bundles, and revive metadata.
- Add reconciliation for "kill requested but process already exited" and "cleanup requested but source already gone".
- Add ACE/mobile/CLI tests for exact-name kill, group kill, dismissal persistence, archive/revive, cleanup previews, and
  partial failures.

Acceptance gates:

- Bulk lifecycle operations do not block the UI thread.
- Retried lifecycle mutations are idempotent.
- Source files, projection rows, and rebuilt state agree after restart.

## Phase 7H - Rollout, Observability, Perf, and Recovery Gates

Purpose: make Epic 7 safe to turn on incrementally.

Primary ownership:

- `../sase-core/crates/sase_gateway` metrics/tracing/doctor/rebuild integration
- `src/sase/main/parser_daemon.py`, `src/sase/main/daemon_handler.py`
- daemon and perf tests under `tests/` and `tests/perf/`
- docs/runbook updates

Deliverables:

- Add scheduler health to `sase daemon status` and `doctor`: queue depth, running task counts, blocked tasks, stale
  starts, host bridge availability, projection lag, and failed source exports.
- Add tracing spans and metrics for batch submit, queue wait, host bridge execution, lifecycle transition, kill latency,
  workflow step duration, axe task duration, and reconciliation repairs.
- Add perf harnesses for launch fan-out, ACE launch responsiveness, mobile launch latency, scheduler restart recovery,
  bulk kill, and axe tick throughput.
- Add recovery commands for stuck queued/starting tasks, stale host bridge tasks, projection rebuild, and direct-mode
  escape hatch.
- Document rollout flags and operator workflow for switching between direct, shadow, and daemon-authoritative scheduler
  modes.

Acceptance gates:

- Warm batch submit and status queries meet the legend's daemon-read latency targets for realistic fixture sizes.
- A killed or restarted daemon recovers queued/running/waiting/completed state without losing source artifacts.
- Users can opt out of daemon scheduling and still use direct launch/workflow/axe paths.

## Recommended Execution Order

1. 7A must land first because it defines the lifecycle truth table and reconciliation behavior every later phase uses.
2. 7B and 7C should follow as a vertical queue-plus-host bridge slice before routing any user command.
3. 7D should route launch surfaces behind flags only after 7B/7C pass parity tests.
4. 7E can start once workflow event IDs and scheduler task IDs are stable from 7B.
5. 7F should wait until host bridge execution and backpressure are proven by agent launches.
6. 7G should wait until lifecycle projections and kill/cancel semantics are stable.
7. 7H starts early for metrics shape but finishes last as the rollout gate.

## Cross-Phase Testing Strategy

- Rust unit tests for scheduler transition planners, projection application, replay, idempotency, and queue ordering.
- Rust daemon integration tests with fake host bridges for success, failure, slow host, cancellation, restart, and stale
  process scenarios.
- Python contract tests comparing direct launch/workflow/axe behavior to daemon-routed behavior.
- End-to-end tests for `sase run`, ACE launch, mobile launch/kill/retry, workflow HITL, and axe scheduled jobs.
- Perf tests for launch fan-out and UI responsiveness before enabling daemon-authoritative mode.
- Rebuild/doctor tests that delete projections and reconstruct lifecycle/workflow state from source artifacts.

## Handoff Requirements for Each Agent Phase

Each phase should leave:

- a short handoff note under the appropriate SDD epic/tale path describing changed files, flags, and remaining risks;
- tests that can run independently of later phases;
- no default routing change unless the phase explicitly owns rollout;
- fallback behavior preserved for daemon unavailable, projection degraded, and direct recovery mode;
- source/export compatibility documented for any migrated mutation or lifecycle state.

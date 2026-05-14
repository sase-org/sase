---
create_time: 2026-05-13 18:55:53
status: done
prompt: sdd/prompts/202605/rust_daemon_epic3_daemon_runtime.md
bead_id: sase-3e.3
tier: epic
legend_bead_id: sase-3e
---
# Epic 3 Plan - Daemon Runtime, Ownership, and Local Transport

## Source

This plan implements Epic 3, "Daemon Runtime, Ownership, and Local Transport", from
`sdd/legends/202605/rust_daemon_indexed_projections_1.md`.

Epic 3 purpose: turn `../sase-core/crates/sase_gateway` into the single SASE daemon process, while preserving the
existing mobile gateway API and adding local process ownership, Unix-socket framed JSON RPC, subscriptions,
observability, and Python lifecycle/client glue.

## Current State

- `../sase-core/crates/sase_gateway` is already a Rust binary/library that serves the loopback mobile HTTP API and
  authenticated SSE stream.
- `sase_gateway` already has a committed local daemon wire contract snapshot at
  `../sase-core/crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json`.
- `sase_gateway::wire` already defines local daemon request/response records for health, capabilities, list, events,
  batch, fallback, and typed errors.
- Epic 2 appears to have introduced `sase_core::projections`, including `ProjectionDb`, event log, replay, migrations,
  domain projection modules, maintenance helpers, and query helpers.
- Python already has mobile gateway lifecycle glue under `src/sase/integrations/mobile_gateway.py`, but no top-level
  `sase daemon ...` command yet.
- The existing `sase run -d/--daemon` means "launch a detached background agent" and should not be conflated with the
  new local state daemon.

## Architectural Decisions

- Extend the existing `sase_gateway` binary instead of creating a second Rust daemon binary.
- Keep the existing mobile HTTP gateway behavior compatible. Default `sase_gateway` invocation should continue to serve
  the mobile API unless an intentional CLI migration is explicitly approved later.
- Add a distinct Rust daemon mode, preferably `sase_gateway daemon`, which starts:
  - mobile HTTP routes when configured, preserving the current loopback/mobile contract;
  - a Unix-domain socket local RPC server;
  - shared runtime state, event hub, projection DB manager, metrics, and tracing.
- Use host-local runtime state under `~/.sase/run/<hostname>/` for lock files, sockets, logs, metrics metadata, and
  projections. Do not put daemon SQLite/WAL/lock/socket files in sync-prone global directories.
- Keep SQLite operations behind a small blocking boundary. The daemon runtime should never run long SQLite or parsing
  work on async reactor tasks.
- Treat local daemon read/list APIs in Epic 3 as contract and smoke surfaces only. Full indexed ChangeSpec/agent/bead
  read migration remains Epic 5.
- Python command adapters should be lifecycle/client glue only. Shared backend behavior stays in Rust.

## Non-Goals

- Do not migrate ACE, CLI, editor, or mobile read paths to daemon-backed indexed projections in this epic.
- Do not make daemon writes authoritative for ChangeSpecs, agents, notifications, beads, or workflows.
- Do not add file watchers or shadow indexers; that is Epic 4.
- Do not remove direct Python fallback paths.
- Do not rewrite the mobile gateway threat model beyond preserving its existing loopback/non-loopback guardrails.

## Phase 3A - Rust Daemon Mode Skeleton And Runtime Config

Owner: one agent.

Primary write scope:

- `../sase-core/crates/sase_gateway/src/main.rs`
- `../sase-core/crates/sase_gateway/src/server.rs`
- new `../sase-core/crates/sase_gateway/src/daemon.rs`
- `../sase-core/crates/sase_gateway/src/lib.rs`
- focused Rust tests in the touched modules

Deliverables:

- Add an explicit daemon-mode entry point to the `sase_gateway` binary.
- Define `DaemonConfig` separately from `GatewayConfig`, while reusing the mobile gateway config where appropriate.
- Preserve existing `sase_gateway --bind ...` mobile behavior.
- Add daemon-mode flags for:
  - `--sase-home`;
  - `--run-root` override for tests;
  - `--socket-path` override for tests;
  - `--foreground`;
  - existing mobile bind/non-loopback/push/bridge options when mobile HTTP is enabled;
  - `--disable-mobile-http` for local-only test and recovery modes.
- Introduce a `DaemonRuntime`/`DaemonState` shell that owns shared build/version, host identity, runtime paths, shutdown
  token, and existing mobile gateway state.
- Add unit tests for CLI parsing, default path derivation, and mobile default preservation.

Acceptance gates:

- `cargo test -p sase_gateway daemon` passes.
- Existing mobile gateway tests still pass.
- `sase_gateway --help` and `sase_gateway daemon --help` make the two modes unambiguous.
- No Python command is routed to the daemon yet.

## Phase 3B - Host-Local Ownership Lock And Stale Recovery

Owner: one agent after 3A.

Primary write scope:

- `../sase-core/crates/sase_gateway/src/daemon.rs`
- new `../sase-core/crates/sase_gateway/src/ownership.rs`
- `../sase-core/crates/sase_gateway/src/lib.rs`
- Rust tests for lock acquisition/release/stale cases

Deliverables:

- Create host-local runtime directory layout under `~/.sase/run/<hostname>/`.
- Add lock metadata record with PID, hostname, boot/session hint when available, executable path, socket path,
  started-at timestamp, SASE home, schema version, and build version.
- Enforce single local daemon ownership with an OS file lock plus human-readable metadata.
- Refuse startup when another live daemon owns the same host-local state directory.
- Detect stale locks and produce actionable recovery messaging.
- Treat hostname mismatch or synced-conflict metadata as a conflict, not as a lock to silently overwrite.
- Clean up socket and lock on graceful shutdown; leave enough metadata for doctor/status to explain abnormal exits.

Acceptance gates:

- Two daemon starts against the same run root cannot both succeed.
- Stale PID metadata can be diagnosed and recovered through a typed path, not by blind deletion.
- Tests cover live lock, stale lock, malformed lock metadata, hostname mismatch, and clean shutdown.

## Phase 3C - Python `sase daemon` Lifecycle Wrapper

Owner: one agent after 3A and 3B.

Primary write scope:

- new `src/sase/main/parser_daemon.py`
- `src/sase/main/parser.py`
- `src/sase/main/entry.py`
- new `src/sase/main/daemon_handler.py`
- new `src/sase/integrations/daemon_lifecycle.py`
- new/updated tests under `tests/`

Deliverables:

- Add top-level `sase daemon {start,stop,status,doctor,rebuild}`.
- Implement `start` by resolving and launching `sase_gateway daemon` safely without a shell.
- Support `sase daemon start --foreground` for tests and explicit terminal ownership.
- Support background start with bounded readiness polling through the local socket once Phase 3D lands; until then, poll
  lock/socket metadata conservatively and return clear "started but RPC unavailable" messaging.
- Implement `status` using lock metadata first, then local health RPC when available.
- Implement `stop` using local RPC if available, falling back to PID signal only when ownership metadata matches this
  host.
- Stub `doctor` and `rebuild` as daemon lifecycle commands that report "transport/storage not available yet" until later
  phases wire them to Rust functionality.
- Add parser and lifecycle tests modelled on the existing mobile gateway tests.

Acceptance gates:

- `sase daemon start --foreground` runs the Rust daemon mode.
- `sase daemon status` is useful when the daemon is running, stopped, stale, or incompatible.
- `sase daemon stop` does not kill unrelated processes with stale or mismatched metadata.
- Existing `sase run -d/--daemon` behavior is unchanged.

## Phase 3D - Unix-Socket Framed JSON RPC Server And Python Client

Owner: one agent after 3A and 3B. This can run in parallel with 3C only if the Python wrapper agent owns CLI files and
this agent owns the Rust transport plus a low-level Python client module.

Primary write scope:

- new `../sase-core/crates/sase_gateway/src/local_transport.rs`
- `../sase-core/crates/sase_gateway/src/daemon.rs`
- `../sase-core/crates/sase_gateway/src/wire.rs`
- `../sase-core/crates/sase_gateway/src/contract.rs`
- `../sase-core/crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json`
- new `src/sase/daemon/client.py`
- tests in both repos

Deliverables:

- Implement Unix-domain socket framed JSON request/response.
- Use a simple length-prefixed frame, with `LOCAL_DAEMON_MAX_PAYLOAD_BYTES` enforced before allocation-heavy parsing.
- Implement local RPC handlers for:
  - `health`;
  - `capabilities`;
  - `batch`;
  - `list` returning bounded mock/empty responses until Epic 5 wires real indexed read surfaces;
  - typed errors for unsupported client schema, invalid request, payload too large, unavailable, and internal failures.
- Return `daemon_started=true` for live daemon health and include fallback details when degraded.
- Add snapshot/contract tests for the framed local daemon protocol and regenerate the committed local daemon contract
  only when the wire contract changes intentionally.
- Add a thin Python client facade that can:
  - derive the default socket path;
  - send one request;
  - handle timeouts and typed fallback reasons;
  - expose `health()`, `capabilities()`, and `batch()`.

Acceptance gates:

- A local client can query health without importing Textual or heavyweight Python modules.
- Bad schema versions and oversized payloads return typed errors.
- Contract tests prove request/response JSON shapes stay stable.
- Existing mobile HTTP contract tests remain green.

## Phase 3E - Projection DB Manager And Blocking Work Boundary

Owner: one agent after 3D and Epic 2 projection APIs.

Primary write scope:

- `../sase-core/crates/sase_gateway/src/daemon.rs`
- new `../sase-core/crates/sase_gateway/src/projection_service.rs`
- `../sase-core/crates/sase_gateway/src/local_transport.rs`
- focused tests in `../sase-core`

Deliverables:

- Open the Epic 2 `sase_core::projections::ProjectionDb` from the daemon runtime using a host-local projection path.
- Add a connection/operation manager that serializes SQLite writes and runs blocking SQLite/parsing calls through
  `tokio::task::spawn_blocking` or an equivalent bounded blocking executor.
- Add startup repair checks:
  - run migrations;
  - detect event/projection sequence gaps;
  - expose degraded health when repair is needed but not yet performed.
- Wire `health` to include projection DB open/migration status in a compact, non-secret details payload.
- Add daemon-internal APIs for future Epic 4/5 services to run read queries and append projection events without
  touching transport code.

Acceptance gates:

- Daemon health reports `ok` with an initialized projection DB and `degraded` with actionable details when the DB cannot
  open.
- SQLite work does not run directly in async socket accept/read tasks.
- Tests exercise projection open, migration, degraded DB path, and concurrent health requests.

## Phase 3F - Local Delta Stream And Subscription Contract

Owner: one agent after 3D. This can run before or after 3E if it uses mock/heartbeat events first and later accepts
projection-backed publishers.

Primary write scope:

- `../sase-core/crates/sase_gateway/src/local_transport.rs`
- `../sase-core/crates/sase_gateway/src/daemon.rs`
- `../sase-core/crates/sase_gateway/src/wire.rs`
- Python client additions under `src/sase/daemon/client.py`
- tests in both repos

Deliverables:

- Implement local subscription semantics for `LocalDaemonRequestPayloadWire::Events`.
- Provide heartbeat records and replay/resync semantics compatible with the committed local daemon event contract.
- Support collection filters and `after_event_id` for future ChangeSpec/agent/notification/bead deltas.
- Share event publication infrastructure with the existing mobile SSE hub where practical, while keeping mobile auth and
  local socket behavior separate.
- Add Python client iteration helpers for bounded event reads and heartbeat smoke tests.

Acceptance gates:

- A local client can subscribe to heartbeats over the Unix socket.
- Multiple local subscribers do not block one another.
- Slow or disconnected subscribers are bounded and cleaned up.
- Mobile SSE behavior remains unchanged.

## Phase 3G - Observability, Metrics, And Developer Diagnostics

Owner: one agent after 3D and preferably after 3E.

Primary write scope:

- `../sase-core/crates/sase_gateway/Cargo.toml`
- `../sase-core/crates/sase_gateway/src/daemon.rs`
- `../sase-core/crates/sase_gateway/src/server.rs`
- `../sase-core/crates/sase_gateway/src/local_transport.rs`
- `../sase-core/crates/sase_gateway/src/projection_service.rs`
- Python `sase daemon status/doctor` display enhancements

Deliverables:

- Add structured `tracing` spans for:
  - daemon startup/shutdown;
  - lock acquire/release;
  - local RPC accept/read/dispatch/write;
  - projection DB open/query/event append;
  - mobile HTTP route requests, preserving existing behavior.
- Add Prometheus metrics on loopback, either integrated into the existing HTTP server or a dedicated loopback-only
  metrics route in daemon mode.
- Include counters/histograms for RPC latency, active connections, payload rejection, projection query latency,
  projection event append latency, subscription count, dropped events, and health status.
- Add opt-in dev `tokio-console` support behind a Cargo feature or CLI flag that is inactive by default.
- Surface metrics endpoint and log path in `sase daemon status --json`.

Acceptance gates:

- Metrics bind only to loopback unless explicitly configured otherwise.
- Health/status output includes enough diagnostic fields to debug startup and socket issues.
- Tests cover metrics route availability and non-loopback refusal/defaults.

## Phase 3H - Doctor, Rebuild, Fallback, And End-To-End Hardening

Owner: one agent after 3C, 3D, and 3E.

Primary write scope:

- `src/sase/integrations/daemon_lifecycle.py`
- `src/sase/daemon/client.py`
- `src/sase/main/daemon_handler.py`
- `../sase-core/crates/sase_gateway/src/daemon.rs`
- `../sase-core/crates/sase_gateway/src/projection_service.rs`
- Rust and Python integration tests

Deliverables:

- Make `sase daemon doctor` perform local checks:
  - lock metadata validity;
  - process liveness;
  - socket connect/RPC health;
  - projection DB open/migration status;
  - mobile HTTP status when enabled;
  - stale lock and synced-conflict diagnosis.
- Make `sase daemon rebuild` call a Rust daemon operation that runs projection rebuild/repair scaffolding from Epic 2.
  If domain source rebuild is incomplete until Epic 4, report explicit "storage reset/replay only" limitations.
- Define Python fallback behavior:
  - typed daemon-unavailable exceptions;
  - explicit `--no-daemon` hooks for future commands;
  - recovery-mode messaging when lock/DB/socket state is corrupt.
- Add end-to-end tests that start a foreground daemon against a temp SASE home, query health/capabilities, subscribe to
  a heartbeat, inspect status, and stop cleanly.
- Add docs/runbook notes for daemon lifecycle and recovery.

Acceptance gates:

- `sase daemon doctor` distinguishes stopped, healthy, degraded, stale lock, incompatible client, and corrupt projection
  cases.
- `sase daemon rebuild` is safe to run while stopped or through a live daemon, with clear locking semantics.
- End-to-end tests do not require Textual and do not route production CLI/TUI reads to daemon projections.

## Suggested Execution Order

1. 3A - Rust daemon mode skeleton and config.
2. 3B - ownership lock and stale recovery.
3. 3D - Unix-socket framed JSON transport and Python client.
4. 3C - Python `sase daemon` lifecycle wrapper, rebased onto the 3D client if needed.
5. 3E - projection DB manager and blocking boundary.
6. 3F - local delta stream and heartbeat subscription.
7. 3G - observability and metrics.
8. 3H - doctor/rebuild/fallback end-to-end hardening.

3C can start after 3B with metadata-only status, but it should be finalized after 3D so lifecycle readiness uses the
real local transport. 3F can start from mock/heartbeat events after 3D, then accept projection publishers after 3E.

## Cross-Repo Verification

Rust core/gateway:

```bash
cd ../sase-core
cargo test -p sase_gateway
cargo test -p sase_core projections::
```

Python repo:

```bash
just install
pytest tests/test_mobile_gateway.py
pytest tests/test_daemon_lifecycle.py tests/test_daemon_client.py
just check
```

For phases that only touch `../sase-core`, run the Rust checks and at least the Python parser/client tests if any Python
wire or lifecycle assumptions changed. For phases that touch this repo, run `just install` first in the current
workspace and `just check` before handing off.

## Final Epic Acceptance Gates

- Only one local daemon can own a host-local state directory.
- Existing mobile gateway routes and contract tests still pass.
- A local client can query daemon health and subscribe to heartbeats without importing Textual or broad Python modules.
- The daemon has a projection DB manager with bounded blocking behavior, even though production read-path migration is
  deferred.
- `sase daemon start|stop|status|doctor|rebuild` exist and produce actionable recovery messages.
- Metrics and tracing exist for RPC, query, event append, projection update, and lifecycle operations.
- Direct/no-daemon fallback remains available for future CLI/ACE/editor migrations.

---
create_time: 2026-05-14 08:48:24
status: wip
prompt: sdd/prompts/202605/rust_daemon_epic10_sync_recovery_ops.md
---
# Plan - Rust Daemon Epic 10 Multi-Machine Sync, Recovery, and Operations

## Context

Epic 10 from `sdd/legends/202605/rust_daemon_indexed_projections_1.md` makes the daemon safe for users who sync
`~/.sase/` and for large histories with years of artifacts. It is intentionally operational and cross-cutting: storage
layout decisions must land early, while doctor/rebuild/backup diagnostics, chaos tests, and docs keep tightening as
daemon reads, writes, scheduling, and ACE virtualization become more authoritative.

Current useful substrate in this checkout:

- Rust daemon mode already derives host-local paths under `~/.sase/run/<hostname>/`, with `sase-daemon.sock`,
  `daemon.lock`, `daemon.lock.json`, `daemon.log`, and `projections/projection.sqlite`.
- Python lifecycle glue already exposes `sase daemon start|stop|status|doctor|rebuild|verify|diff` and resolves the same
  runtime paths through `src/sase/integrations/_daemon_lifecycle_config.py`.
- Rust ownership guards already use exclusive file locks, metadata schema/version checks, same-host stale metadata
  handling, and host-conflict refusal.
- Projection service health already reports `path_kind: host_local`, schema/migration state, repair flags, event gaps,
  source-export health, indexing health, scheduler health, provider-host health, and metrics/log paths.
- Projection maintenance already has WAL checkpoint decisions, `wal_checkpoint`, `VACUUM INTO` backup primitives,
  ephemeral event compaction, and reconciliation planning.
- Shadow indexing already has verify/diff/rebuild surfaces and watcher/reconciliation tests for missed or reordered
  source changes.
- `docs/rust_backend.md` documents current daemon routing, fallback/no-daemon controls, and the diagnostic commands.

The remaining Epic 10 work should harden these pieces into an explicit operations contract. Future agents should avoid
large unrelated daemon rewrites; each phase below is a bounded, testable operational slice.

## Goals

- Ensure no daemon-owned SQLite database, WAL, socket, lock, or high-volume log is accidentally treated as synced source
  state.
- Make `sase daemon doctor` produce actionable repair commands for stopped, stale, conflicting, corrupt, degraded, and
  unsafe-layout states.
- Make `sase daemon rebuild` and backup restore safe, scoped, auditable, and understandable in both live-daemon and
  one-shot recovery modes.
- Add deterministic sync chaos tests covering the failure modes named by the legend: corrupt locks, two hosts racing
  against shared source stores, projection deletion/rebuild, and reordered/missed file events.
- Document the storage model, backup/rebuild flows, multi-machine sync recommendations, and no-daemon fallback so users
  can recover without knowing internal Rust/Python module boundaries.

## Non-Goals

- Do not make projections the source of truth. Source files, JSONL stores, and explicit artifacts remain authoritative
  unless a later write-through phase has recorded a narrower contract.
- Do not remove direct Python fallback paths or `--no-daemon`/`SASE_NO_DAEMON`.
- Do not migrate provider/plugin/workflow side effects into Rust in this epic.
- Do not solve cross-host distributed locking for synced source stores. The daemon should detect and explain unsafe
  concurrent situations, not pretend synced filesystems provide transactional semantics.
- Do not rewrite ACE, daemon read APIs, or scheduler internals except where operational health and repair surfaces need
  small status fields.

## Cross-Phase Design

Use one storage vocabulary in Rust, Python, health JSON, tests, and docs:

- `sase_home`: user-visible source root, defaulting to `~/.sase`.
- `source_roots`: synced/human-readable stores such as `projects`, notifications, pending actions, artifacts, chats,
  beads, repos metadata, workflow state, and explicit artifact indexes that remain compatibility surfaces.
- `run_root`: host-local daemon runtime root, defaulting to `sase_home/run/<sanitized-hostname>`.
- `runtime_files`: socket, lock files, logs, projection SQLite/WAL/SHM, checkpoints, backup snapshots, transient queues,
  and high-volume daemon event/log material.
- `layout_policy`: computed diagnostics describing whether runtime files are under the default host subdir, an override,
  a likely synced directory, or a path that should be refused/warned.
- `repair_action`: stable machine-readable action entries with command, severity, destructive-risk label, and human
  explanation.

Operational commands should share the same repair vocabulary:

- `doctor` reports state and recommended commands, but does not mutate without an explicit repair flag.
- `rebuild` repairs projections from source stores through the live daemon by default; `--reset-storage` remains the
  stopped one-shot retained-event replay path.
- `verify` and `diff` remain read-only parity tools.
- Backup restore must be explicit, should never overwrite source stores, and should prefer restoring projection
  snapshots only under `run_root`.

## Phase 10A - Storage Layout Contract and Sync Guidance

Purpose: make daemon-owned runtime state and user-visible source state explicit before adding more repair behavior.

Primary ownership:

- `../sase-core/crates/sase_gateway/src/daemon.rs`
- `../sase-core/crates/sase_gateway/src/projection_service.rs`
- `src/sase/integrations/_daemon_lifecycle_config.py`
- `src/sase/daemon/paths.py`
- `docs/rust_backend.md`, `docs/configuration.md`, and optionally a new `docs/daemon_operations.md`

Deliverables:

- Add a small shared storage-layout diagnostic model to daemon health and Python status/doctor output:
  - `sase_home`, `run_root`, `socket_path`, `projection_db_path`, and `log_path`;
  - `path_kind` for each path, using stable values such as `source_root`, `host_local_default`, `host_local_override`,
    `unsafe_synced_candidate`, and `unknown`;
  - a list of `runtime_files` that users should exclude from Syncthing/rclone/git-style sync.
- Confirm Rust and Python derive identical default paths for normal hosts, empty/malformed hostnames, and explicit
  overrides.
- Add diagnostics for suspicious layout overrides, for example a `run_root` outside the default host subdir, a
  projection path under a known source-store subdirectory, or a socket path outside `run_root`.
- Document the storage model and practical sync exclusions:
  - keep source stores synced if desired;
  - exclude `~/.sase/run/`;
  - never sync `projection.sqlite`, `projection.sqlite-wal`, sockets, locks, or daemon logs;
  - use one daemon per host-local run root.

Acceptance gates:

- Contract/unit tests prove Rust and Python path derivation match.
- `sase daemon doctor --json` includes enough layout data for downstream tools to identify runtime files.
- Docs clearly distinguish rebuildable runtime projections from authoritative source artifacts.
- No production routing behavior changes.

Suggested phase prompt:

> Implement Phase 10A from `sase_plan_rust_daemon_epic10_sync_recovery_ops.md`: add daemon storage-layout diagnostics,
> Rust/Python path parity tests, unsafe layout warnings, and user docs for excluding host-local runtime files from sync.

## Phase 10B - Doctor Repair Actions and Stale Lock Recovery UX

Purpose: make lifecycle diagnostics actionable, especially when locks or metadata are stale, corrupt, or from another
host.

Primary ownership:

- `../sase-core/crates/sase_gateway/src/ownership.rs`
- `src/sase/integrations/_daemon_lifecycle_inspection.py`
- `src/sase/integrations/_daemon_lifecycle_diagnostics.py`
- `src/sase/main/parser_daemon.py`
- lifecycle tests under `tests/`

Deliverables:

- Add structured `repair_actions` to doctor JSON and human output. Each action should include:
  - stable id such as `daemon_stop`, `daemon_start`, `daemon_rebuild_reset_storage`, `daemon_verify`,
    `remove_stale_lock`, `inspect_host_conflict`, or `move_run_root`;
  - exact command text where safe;
  - risk level `read_only`, `runtime_only`, or `requires_manual_review`;
  - short explanation.
- Improve stale lock diagnostics for:
  - malformed `daemon.lock.json`;
  - missing metadata with lock file present;
  - dead same-host PID;
  - live same-host PID with mismatched executable;
  - different-host metadata that suggests a synced run directory.
- Add an explicit repair path only for same-host runtime-only stale state, gated by a clear flag such as
  `sase daemon doctor --repair-stale-lock` or a dedicated narrow subcommand. It must not delete source files.
- Keep different-host conflicts non-mutating by default and guide the user to exclude/move `run_root`.
- Ensure human output names the command that repairs the problem instead of only reporting internal state.

Acceptance gates:

- Tests cover stale, corrupt, stopped, running, live-conflict, and host-conflict states.
- Different-host metadata is never silently overwritten.
- Repair actions are stable enough for ACE/mobile/editor surfaces to display later.

Suggested phase prompt:

> Implement Phase 10B from `sase_plan_rust_daemon_epic10_sync_recovery_ops.md`: add structured daemon doctor repair
> actions, improve stale/corrupt/host-conflict lock diagnostics, and add an explicit same-host stale-lock repair path.

## Phase 10C - Backup, Checkpoint, and Restore Operations

Purpose: turn existing WAL/checkpoint/`VACUUM INTO` primitives into user-facing operational commands and tests.

Primary ownership:

- `../sase-core/crates/sase_core/src/projections/maintenance.rs`
- `../sase-core/crates/sase_gateway/src/projection_service.rs`
- `../sase-core/crates/sase_gateway/src/wire.rs` and `contract.rs`
- `src/sase/daemon/client.py`
- `src/sase/integrations/daemon_lifecycle.py` and parser glue
- docs and focused Rust/Python command tests

Deliverables:

- Add daemon RPCs and CLI wrappers for:
  - checkpointing the projection WAL with an explicit mode;
  - creating a projection backup snapshot under `run_root/backups/` by default;
  - listing recent projection backups;
  - restoring a projection backup into `run_root/projections/` with the daemon stopped or through a guarded live-daemon
    recovery mode.
- Make restore projection-only: it must never modify source stores, JSONL files, project specs, artifact files, or
  external repos.
- Include backup metadata:
  - schema version, daemon/core version, host identity, source `sase_home`, created timestamp, projection schema, event
    max sequence, source-export summary, and original DB path.
- Validate restore compatibility and report actionable errors for incompatible schema, host mismatch, missing WAL/SHM
  expectations, unreadable snapshot, or active daemon ownership.
- Add docs describing when to prefer `rebuild` over `restore`:
  - use rebuild for projection corruption when source stores are healthy;
  - use restore for faster rollback of runtime projections or investigation snapshots;
  - verify after either path.

Acceptance gates:

- A test can create a projection backup, delete/corrupt the active projection DB, restore the backup, and run health.
- Restore refuses to run when it would overwrite a live daemon-owned DB without the proper guard.
- Contract snapshots cover backup/restore request and response schemas.

Suggested phase prompt:

> Implement Phase 10C from `sase_plan_rust_daemon_epic10_sync_recovery_ops.md`: expose projection checkpoint, backup,
> list-backups, and restore operations through daemon RPC/CLI with guarded projection-only semantics and docs.

## Phase 10D - Rebuild, Verify, Diff, and Source-Export Repair Hardening

Purpose: make existing rebuild/verify/diff commands robust enough for large histories and write-through source-export
recovery.

Primary ownership:

- `../sase-core/crates/sase_gateway/src/indexer.rs`
- `../sase-core/crates/sase_gateway/src/projection_service.rs`
- `../sase-core/crates/sase_core/src/projections/rebuild.rs`
- `../sase-core/crates/sase_core/src/projections/mutations.rs`
- Python lifecycle command output and tests

Deliverables:

- Make `sase daemon rebuild --surface ...` report scoped progress and bounded summaries for large stores:
  - scanned sources, indexed rows, skipped rows, parse failures, source-export retries, pending/failed/conflict counts,
    elapsed timings, and next suggested command.
- Ensure source-export outbox retry behavior is explicit during live rebuild and startup:
  - safe pending/failed exports retried;
  - conflicts preserved with target path, surface, and error;
  - doctor reports unresolved conflicts with `sase daemon diff` or manual-review guidance.
- Add bounded diff paging tests for large synthetic diff sets and stable cursors.
- Add rebuild idempotency tests for each available surface: ChangeSpecs, notifications, agents, beads, catalogs, and
  `all`.
- Preserve one-shot `--reset-storage` semantics and make its limitation text impossible to miss in human output.

Acceptance gates:

- Rebuild/verify/diff return stable JSON for both healthy and degraded projections.
- Re-running rebuild is idempotent and does not duplicate projected events or source-export rows.
- Large diff output is bounded and points users at the next page or repair command.

Suggested phase prompt:

> Implement Phase 10D from `sase_plan_rust_daemon_epic10_sync_recovery_ops.md`: harden daemon rebuild/verify/diff
> output, source-export retry diagnostics, idempotency, bounded diff paging, and large-history repair guidance.

## Phase 10E - Sync Chaos Test Harness

Purpose: add deterministic tests for the multi-machine and sync failure modes from the legend.

Primary ownership:

- Rust tests in `../sase-core/crates/sase_gateway` and `../sase-core/crates/sase_core/tests/`
- Python lifecycle tests under `tests/`
- Shared fixtures for synthetic `sase_home` and host-local `run_root`

Deliverables:

- Add a small chaos fixture builder that creates:
  - a shared `sase_home` source tree;
  - two host identities with separate default `run_root`s;
  - optional intentionally unsafe shared `run_root`;
  - source stores for ChangeSpecs, notifications, agents, beads, and catalogs as needed by existing indexers.
- Cover required scenarios:
  - corrupt lock metadata;
  - two hosts racing against a shared source tree with separate run roots;
  - two hosts accidentally sharing the same runtime directory;
  - projection DB deletion followed by rebuild;
  - WAL/SHM deletion or partial projection corruption;
  - reordered/missed file events repaired by reconciliation;
  - source file rewrite while a rebuild is running, if the existing indexer can model it deterministically.
- Make chaos tests hermetic. They must not touch real `~/.sase`.
- Mark slow or soak-style variants appropriately, but keep a representative fast subset in normal test runs.

Acceptance gates:

- Tests prove separate host-local run roots can observe the same source tree without sharing projection DBs or locks.
- Unsafe shared runtime state is detected and explained.
- Projection deletion/corruption recovers through documented rebuild or restore commands.

Suggested phase prompt:

> Implement Phase 10E from `sase_plan_rust_daemon_epic10_sync_recovery_ops.md`: add hermetic sync chaos fixtures and
> tests for corrupt locks, two-host source sharing, unsafe shared runtime directories, projection deletion/rebuild, and
> reordered file-event reconciliation.

## Phase 10F - User-Facing Migration Guide and Diagnostics Polish

Purpose: make the completed operational model understandable to users and support surfaces.

Primary ownership:

- `docs/rust_backend.md`
- `docs/configuration.md`
- `docs/troubleshooting/` or new daemon operations docs
- CLI help text and human output snapshots/tests

Deliverables:

- Add a daemon operations guide covering:
  - what is safe to sync;
  - what must remain host-local;
  - recommended Syncthing/rclone exclusions;
  - how to inspect daemon status;
  - when to use doctor, verify, diff, rebuild, backup, and restore;
  - how to force fallback/no-daemon mode;
  - how to recover from stale locks, host conflicts, projection corruption, and source-export conflicts.
- Update `sase daemon --help` and subcommand help text so recovery commands are discoverable.
- Add example JSON snippets for automation consumers and concise human examples for terminal users.
- Ensure diagnostic messages avoid internal-only phrasing and name exact commands.
- Cross-link ACE/mobile docs only where they expose daemon health or recovery actions.

Acceptance gates:

- A user can follow docs to recover from projection corruption without deleting source artifacts.
- CLI help and human doctor output match the documented command names.
- Docs state that direct fallback remains available via `--no-daemon` and `SASE_NO_DAEMON=1`.

Suggested phase prompt:

> Implement Phase 10F from `sase_plan_rust_daemon_epic10_sync_recovery_ops.md`: write the daemon operations and
> migration docs, polish CLI help and human diagnostics, and add output/help tests that keep repair commands
> discoverable.

## Recommended Phase Order

1. Phase 10A first, because storage vocabulary and sync guidance should constrain every later repair command.
2. Phase 10B next, because stale lock and unsafe layout diagnostics protect future agents while they test daemon work.
3. Phase 10C can run after 10A; it touches backup/restore RPC and command surfaces.
4. Phase 10D should follow the current rebuild/verify/diff substrate and can proceed in parallel with 10C if write
   scopes are coordinated.
5. Phase 10E should start once 10A and 10B diagnostics exist, then expand as 10C and 10D add restore/rebuild behavior.
6. Phase 10F should finish last, after command names and JSON schemas stabilize, but early doc stubs from 10A are
   useful.

## Cross-Phase Verification

- Rust: run focused `cargo test` in `../sase-core` for `sase_core` projection maintenance and `sase_gateway` daemon,
  ownership, indexer, local transport, and contract tests.
- Python: run focused tests for daemon lifecycle/config/diagnostics/client behavior, then `just check` from this repo
  after Python/doc-facing changes.
- Contract: update and review local daemon contract snapshots whenever RPC schema changes.
- Manual smoke, when relevant:
  - start daemon with a temporary `SASE_HOME`;
  - run `sase daemon status --json`;
  - run `sase daemon doctor --json`;
  - run `sase daemon rebuild --surface all --json`;
  - run `sase daemon verify --surface all --json`;
  - stop daemon and validate stopped/one-shot recovery behavior.

## Rollout Notes

- Keep all recovery operations projection/runtime scoped unless explicitly documented otherwise.
- Prefer additive diagnostics and commands over changing existing defaults.
- Every destructive or potentially confusing action must print the exact path scope it touches.
- Every error that blocks startup, rebuild, restore, or read-through routing should include a next command such as
  `sase daemon doctor`, `sase daemon rebuild`, `sase daemon verify`, or `SASE_NO_DAEMON=1`.
- Do not introduce runtime-specific agent behavior. Claude, Gemini, Codex, Qwen, and OpenCode remain uniform daemon
  clients from this epic's perspective.

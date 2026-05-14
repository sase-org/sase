# Local Daemon

The local SASE daemon is an optional host-local Rust process. Users normally start it with `sase daemon start`, which
launches `sase_gateway daemon` under the hood. It provides a Unix-socket JSON RPC surface for health checks, projection
maintenance, daemon-backed reads, durable write-through events, scheduler rollout, provider-host routing, and mobile
HTTP serving.

Source stores remain authoritative. Project files, notifications, pending actions, artifacts, chats, beads, repo
metadata, and workflow state live under the SASE home directory, defaulting to `~/.sase`. The daemon stores rebuildable
runtime state under a host-local `run_root`, defaulting to `~/.sase/run/<host>/`.

A projection is the daemon's rebuildable SQLite view of those source stores. If the daemon is stopped or disabled,
daemon-capable read/write paths fall back to direct source-store behavior, while scheduler paths fall back to direct
Python host behavior where that surface supports fallback. The local daemon is separate from AXE, which is the
background automation scheduler documented in [AXE Automation](axe.md).

## Runtime Layout

Use one daemon per host-local `run_root`.

| Path           | Default                                            | Guidance                                                             |
| -------------- | -------------------------------------------------- | -------------------------------------------------------------------- |
| SASE home      | `~/.sase`                                          | Authoritative user-visible stores; may be synced if you choose.      |
| Run root       | `~/.sase/run/<sanitized-hostname>`                 | Host-local runtime state; do not sync.                               |
| Socket         | `<run_root>/sase-daemon.sock`                      | Host-local IPC; do not sync.                                         |
| Projection DB  | `<run_root>/projections/projection.sqlite`         | Rebuildable SQLite projection; do not sync.                          |
| Lock/log files | `<run_root>/daemon.lock*`, `<run_root>/daemon.log` | Host ownership and diagnostics; do not sync.                         |
| Backups        | `<run_root>/backups/`                              | Projection-only snapshots; do not confuse with source-store backups. |

Exclude `~/.sase/run/` from Syncthing, rclone, Git, cloud-drive sync, and similar tools. `sase daemon status --json` and
`sase daemon doctor --json` include `storage_layout` diagnostics with stable path-kind tokens and a runtime-file
exclusion list.

## Lifecycle Commands

```bash
sase daemon start
sase daemon status
sase daemon doctor
sase daemon stop
```

Common options:

| Option                   | Commands                                       | Purpose                                            |
| ------------------------ | ---------------------------------------------- | -------------------------------------------------- |
| `-H, --sase-home <path>` | all daemon commands                            | Override the source-store root for one invocation. |
| `--run-root <path>`      | all daemon commands                            | Override the host-local runtime root.              |
| `--socket-path <path>`   | all daemon commands                            | Override the Unix socket path.                     |
| `--json`                 | status, doctor, scheduler, projection commands | Emit machine-readable output.                      |

For nested scheduler commands, put runtime path overrides before the scheduler action:

```bash
sase daemon scheduler --run-root /tmp/sase-run status --project <project> --batch <batch>
```

`sase daemon doctor` reports stopped, running, degraded projection, stale lock, incompatible metadata, and host-conflict
states. When doctor confirms that a same-host lock is stale and no live process owns it, run:

```bash
sase daemon doctor --repair-stale-lock
```

That repair removes stale host-local lock, metadata, and socket files only. It does not remove live locks, cross-host
locks, incompatible metadata, source stores, or projection data.

## Read And Write Routing

Daemon-backed reads are read-through accelerators. If the daemon is stopped, lacks a capability, returns a degraded or
expired projection response, or is disabled by rollout config, callers use direct source-store loaders.

Supported read rollout groups:

| Group                                                                                       | Example surfaces                                                         |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `changespecs`                                                                               | ChangeSpec list/search/detail                                            |
| `notifications`                                                                             | Notification list/detail/counts/pending actions                          |
| `agents`                                                                                    | Active/recent/archive/search/detail agent reads                          |
| `beads`                                                                                     | Bead list/show/ready/blocked/stats                                       |
| `catalogs`                                                                                  | XPrompt, editor, snippet, and file-history catalogs                      |
| `ace_agents`, `ace_changespecs`, `ace_notifications`, `ace_artifacts`, `ace_archive_search` | ACE-specific provider surfaces, defaulting off while rollout is measured |

Immediate direct-mode controls:

```bash
sase changespec search --no-daemon 'status:ready'
SASE_NO_DAEMON=1 sase ace
SASE_DAEMON_M1_READ_THROUGH=0 sase changespec search 'status:ready'
```

Config controls live under `daemon.reads`; see the [configuration reference](configuration.md#daemon). Stable fallback
reason tokens include `daemon_disabled`, `daemon_reads_disabled`, `force_direct`, `surface_disabled`,
`m1_read_through_disabled`, `daemon_not_running`, `unsupported_capability`, `unsupported_client_version`,
`unsupported_server_version`, `projection_schema_mismatch`, `projection_degraded`, `cursor_expired`, `snapshot_expired`,
`payload_too_large`, and `resource_not_found`.

M0 and M1 can be rolled back independently. `daemon.rollout.milestones.m0_shadow_indexing: false` or
`SASE_DAEMON_M0_SHADOW_INDEXING=0` disables shadow-indexing readiness in rollout diagnostics without changing source
stores. `daemon.rollout.milestones.m1_read_through: false` or `SASE_DAEMON_M1_READ_THROUGH=0` routes CLI/editor read
surfaces directly while leaving M0 rebuild, verify, and diff diagnostics available.

When a write is routed through the daemon, it appends projection events and source-export outbox rows before updating
human-readable source files. The currently routed durable write surfaces are notifications, ChangeSpec metadata, agent
metadata, bead mutations, and workflow state/response files. Host side effects such as process kills, provider
subprocesses, shell/Python workflow execution, and VCS operations remain direct host actions.

## Scheduler And Provider Host Rollout

The daemon scheduler can shadow or own launches, lifecycle mutations, and axe task routing:

| Config                            | Environment override                   | Values                       |
| --------------------------------- | -------------------------------------- | ---------------------------- |
| `daemon.scheduler.launch_mode`    | `SASE_DAEMON_SCHEDULER_LAUNCH_MODE`    | `direct`, `shadow`, `daemon` |
| `daemon.scheduler.lifecycle_mode` | `SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE` | `direct`, `shadow`, `daemon` |
| `daemon.scheduler.axe_mode`       | `SASE_DAEMON_SCHEDULER_AXE_MODE`       | `direct`, `daemon`           |

Inspect or recover scheduler work with:

```bash
sase daemon scheduler status --project <project> --batch <batch>
sase daemon scheduler cancel --project <project> --batch <batch> [--slot <slot>]
```

Provider-host routing sends selected provider/plugin operations through the daemon's host-call path. Low-risk metadata,
catalog, query, and reference-resolution paths default to `host-preferred`, which uses the host path when the daemon is
running and capable, then falls back direct. Mutation-heavy paths remain direct. Use `SASE_PROVIDER_HOST_MODE=direct` or
set `SASE_DISABLE_PROVIDER_HOST_ROUTING=1` as global rollback switches.

## Projection Maintenance

Use rebuild and verify when the source stores are healthy and daemon projections need to catch up. A source backfill
rebuild, verify, and diff require a running daemon with local RPC available:

```bash
sase daemon rebuild --surface all
sase daemon verify --surface all
sase daemon diff --surface all --limit 100
```

`--surface` accepts `changespecs`, `notifications`, `agents`, `beads`, `catalogs`, or `all`. Use `--project` when the
selected surface supports project-scoped input. `diff --json --cursor <cursor>` pages through bounded diff records.

If the daemon is stopped or stale, the only rebuild mode is `sase daemon rebuild --reset-storage`, which resets
projection tables and replays retained projection events instead of backfilling from source stores.

Use checkpoint, backup, and restore for projection storage recovery. Checkpoint, backup, and list-backups require a
running daemon. Restore can run offline when the daemon is stopped or stale; when the daemon is running it requires
`--live-recovery`.

```bash
sase daemon checkpoint --mode truncate
sase daemon backup
sase daemon list-backups
sase daemon restore <backup.sqlite>
```

Backups are projection-only SQLite snapshots with JSON sidecar metadata. Restore replaces
`<run_root>/projections/projection.sqlite` and removes WAL/SHM sidecars, but never edits source stores, project files,
artifacts, external repositories, or JSONL files. A running daemon requires `--live-recovery`; restoring a snapshot from
another host requires `--allow-host-mismatch`.

Prefer `sase daemon rebuild --surface all` for corrupt or missing projections when source stores are authoritative and
healthy. Use `restore` when you need a fast rollback to a prior projected state or want to inspect a previous runtime
projection snapshot. Run `sase daemon verify` after either operation when shadow-index parity matters.

## Related References

- [Rust backend](rust_backend.md#local-daemon) documents the Python/Rust boundary and current daemon-backed operations.
- [Configuration](configuration.md#daemon) lists config defaults, rollout knobs, and environment overrides.
- [Performance runbook](perf_runbook.md#rust-daemon-epic-5-rollout-gates) records daemon read and scheduler rollout gate
  checks.

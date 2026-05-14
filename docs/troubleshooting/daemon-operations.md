# Daemon Operations

This guide is for operating the local Rust daemon when you sync `~/.sase/` across machines, recover from projection
corruption, or need a terminal-friendly checklist for daemon diagnostics.

The key rule is simple: source stores are authoritative; daemon runtime files are rebuildable or transient.

## Storage Model

`sase_home` is the user-visible state root, defaulting to `~/.sase`. It contains source stores that users may choose to
sync: `projects`, notifications, pending actions, artifacts, chats, beads, repo metadata, workflow state, and mobile
gateway state.

`run_root` is host-local daemon runtime state, defaulting to `~/.sase/run/<sanitized-hostname>`. Run one daemon per
host-local `run_root`. Do not share a `run_root` between machines.

Safe to sync, if your normal workflow already syncs SASE state:

- `~/.sase/projects/`
- `~/.sase/notifications/`
- `~/.sase/pending_actions/`
- `~/.sase/artifacts/`
- `~/.sase/chats/`
- project-local `sdd/beads/`
- repo metadata and workflow state that your integration documents as source state

Keep host-local and exclude from Syncthing, rclone, Git, cloud drives, and similar tools:

- `~/.sase/run/`
- `sase-daemon.sock`
- `daemon.lock`
- `daemon.lock.json`
- `daemon.log`
- `projections/projection.sqlite`
- `projection.sqlite-wal`
- `projection.sqlite-shm`
- `checkpoints/`
- `backups/`
- transient queues

Example exclusions:

```gitignore
~/.sase/run/
**/sase-daemon.sock
**/daemon.lock
**/daemon.lock.json
**/daemon.log
**/projection.sqlite
**/projection.sqlite-wal
**/projection.sqlite-shm
```

## First Checks

Start with status, then doctor:

```bash
sase daemon status
sase daemon doctor
```

Use JSON when an editor, mobile surface, script, or support bundle needs stable fields:

```bash
sase daemon status --json
sase daemon doctor --json
```

A stopped daemon is not automatically data loss. Direct Python readers remain available, and daemon-capable read
commands can force direct mode with `--no-daemon`. To force direct reads for a whole shell process:

```bash
SASE_NO_DAEMON=1 sase agents status
```

## Diagnostic JSON

`sase daemon doctor --json` includes `storage_layout`, `doctor.checks`, and `repair_actions`. Automation consumers
should prefer `repair_actions[*].id`, `risk`, and `command` instead of parsing human text.

Example shape:

```json
{
  "doctor": {
    "state": "degraded",
    "checks": [
      {
        "name": "projection_db",
        "state": "degraded",
        "message": "repair_needed=true, gaps=1"
      }
    ]
  },
  "repair_actions": [
    {
      "id": "daemon_rebuild_reset_storage",
      "risk": "runtime_only",
      "command": "sase daemon rebuild --reset-storage",
      "explanation": "Reset and replay daemon projection storage; source stores are not modified."
    }
  ]
}
```

Risk labels mean:

| Risk                     | Meaning                                                                |
| ------------------------ | ---------------------------------------------------------------------- |
| `read_only`              | Reads status, health, diffs, or verification data only.                |
| `runtime_only`           | Mutates daemon runtime files under `run_root`; source stores are safe. |
| `requires_manual_review` | Operator must inspect paths or ownership before taking further action. |

## Command Guide

Use `doctor` when the daemon is stopped, stale, conflicting, degraded, or confusing:

```bash
sase daemon doctor
```

Live projection backfill, verify, diff, backup, and list-backups use the daemon RPC path and require a running daemon.
Offline recovery is limited to stopped/stale restore and `sase daemon rebuild --reset-storage`.

Use `verify` after a rebuild, restore, or suspected projection drift:

```bash
sase daemon verify --surface all
```

Use `diff` to inspect bounded projection differences:

```bash
sase daemon diff --surface all --limit 100
sase daemon diff --surface all --cursor <next-cursor>
```

Use live rebuild when source stores are healthy and projections are missing, corrupt, or stale:

```bash
sase daemon rebuild --surface all
```

Use reset-storage only for the explicit projection-table reset/replay path. It is runtime scoped and does not delete
source stores:

```bash
sase daemon rebuild --reset-storage
```

Use backup and restore for runtime projection snapshots:

```bash
sase daemon backup
sase daemon list-backups
sase daemon restore ~/.sase/run/<host>/backups/projection-<timestamp>.sqlite
```

If the daemon is running, restore requires an explicit live recovery flag:

```bash
sase daemon restore ~/.sase/run/<host>/backups/projection-<timestamp>.sqlite --live-recovery
```

Prefer rebuild over restore when source stores are healthy. Restore is useful for fast rollback or inspecting an older
runtime projection snapshot. Restore never edits source stores, JSONL files, ProjectSpec files, artifacts, or external
repos.

## Recovery Recipes

Projection database missing or corrupt:

1. Run `sase daemon doctor`.
2. Run `sase daemon rebuild --surface all` if the daemon is running.
3. If the daemon cannot run but retained events are available, run `sase daemon rebuild --reset-storage`.
4. Run `sase daemon verify --surface all`.

Stale same-host lock:

1. Run `sase daemon doctor`.
2. Confirm the repair action is `remove_stale_lock` and `risk` is `runtime_only`.
3. Run `sase daemon doctor --repair-stale-lock`.
4. Run `sase daemon start`.

Host conflict or shared runtime directory:

1. Run `sase daemon status --json`.
2. Do not run stale-lock repair.
3. Move the affected machine back to its own host-local `run_root`.
4. Exclude `~/.sase/run/` from sync.
5. Run `sase daemon doctor`.

Source-export conflicts:

1. Run `sase daemon doctor --json` and inspect the `source_exports` check.
2. Run `sase daemon diff --surface all --json`.
3. Repair the named source file manually.
4. Run `sase daemon rebuild --surface all`.
5. Run `sase daemon verify --surface all`.

Need to keep working without daemon reads:

```bash
SASE_NO_DAEMON=1 sase agents status
```

Use the per-command `--no-daemon` flag where the read command exposes it.

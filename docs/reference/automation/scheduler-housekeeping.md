---
title: Scheduler housekeeping
description: Tasks handled by the scheduler's housekeeping routine.
---

# Scheduler housekeeping

This page describes the scheduler housekeeping routine.

## housekeeping (1-hour interval) {#housekeeping-1-hour-interval}

Periodic maintenance:

| Job                          | Description                                                                      |
| ---------------------------- | -------------------------------------------------------------------------------- |
| `error_digest`               | Send error notification digests (creates `ViewErrorReport` notification action)  |
| `notification_store_compact` | Archive old dismissed notifications out of the live JSONL store                  |
| `managed_tmp_reap`           | Prune stale scratch under every registered managed SASE temp root                |
| `proc_runtime_sweep`         | Prune stale rowless proc runtime directories                                     |
| `disk_pressure`              | Notify on disk pressure and run owner-safe cleanup early                         |
| `bead_stale_cleanup`         | Sweep stale sub-threshold ready task beads into one `BeadStaleCleanup` gate      |
| `gate_turn_reclaim`          | Settle pending gate turns whose gates answered, canceled, expired, or vanished   |
| `artifact_link_backfill`     | Derive and reconcile artifact links, drain reads, and repair refs after a rename |
| `artifact_run_prune`         | Preview old ace-run directories and empty shard cleanup                          |

The `error_digest` job summarizes recent errors into a digest file stored at
`~/.sase/axe/error_digests/digest_<timestamp>.txt`. The notification includes a
`ViewErrorReport` action that opens the digest in `$EDITOR` when selected in sase's TUI
notification modal. For failed script subprocesses, the digest includes the job run ID,
exit code, source log path, and a bounded subprocess output excerpt captured at failure
time. The excerpt is redacted, stripped of terminal control sequences, and retained in
`recent_errors.json`, so the digest remains useful even after per-run logs are pruned.
Silent, missing, unreadable, malformed, and truncated output are called out explicitly
instead of being reported as a Python traceback.

The `notification_store_compact` job bounds `~/.sase/notifications/notifications.jsonl`
by moving dismissed rows older than 3 days into `notifications-archive.jsonl`. Unread
and still-actionable rows stay in the live file. sase's TUI snapshot reads are memoized
against an mtime+size token, so this pass lives on `housekeeping` rather than the TUI
refresh cadence.

The `managed_tmp_reap` job bounds every managed SASE temp root writers actually used.
Each `get_sase_managed_tmpdir()` call registers its resolved root (`$SASE_TMPDIR`, else
`~/.sase/tmp`) in a Rust-owned registry at `$SASE_HOME/managed_tmp/roots.json`
(`sase-core`'s `managed_tmp_roots` module), and this job reaps the effective root plus
every registered root that still exists instead of only the root its own environment
resolves. A root nested inside another covered root is folded into it, so a per-launch
root registered under an already-registered ancestor is not reaped or counted twice. The
actual age/pressure decision runs in `sase_core_rs` (`sase-core`'s `managed_tmp` crate);
this Python job resolves the configured horizons and thresholds and calls that binding
once per root. Horizons are per subdirectory: command scratch (`editors/`, `wrappers/`,
`viewers/`, `commit-messages/`, `agent-tmp/`, …) goes after 12 hours by default, handoff
files (`handoff/`, `gh-diffs/`, `muse-prompts/` — a provider re-reads the latter
mid-run) after 3 days, build targets (`cargo-targets/`, `build-targets/`) after 1 day,
and artifacts sase's TUI and screenshot tooling reads back (`launch-prompts/`,
`screenshots/`, `workflow-artifacts/`) after 14 days. Launched agents default
`TMPDIR`/`TMP`/`TEMP`, `CARGO_TARGET_DIR`, and `CARGO_BUILD_BUILD_DIR` to per-launch
directories under those managed buckets, so shell scratch and Cargo targets do not fall
back to host-global `/tmp`. Launched agents also get line-tables-only debug info for the
dev and test Cargo profiles, which keeps per-launch targets small. They get
`CARGO_INCREMENTAL=0` by default, or `CARGO_INCREMENTAL=1` when
[`managed_tmp.agent_cargo_incremental`](../config/runtime-and-storage.md#managedtmp) is
enabled (athena only, where the splitting rustc wrapper runs metadata-only units
incrementally direct and strips incremental from codegen units before sccache). A runner
also removes its own launch-assigned `agent-tmp/` and `cargo-targets/` children at exit
when they still match its exported `TMPDIR` and `CARGO_TARGET_DIR` and it can prove,
through procfs, that no live process still references either tree (by environment or
working directory). That removal goes through the same Rust reaper as the hourly pass.
Monitor handoffs skip runner-exit cleanup. When the monitor settles, it reads the
starter's recorded scratch key and reaps only the starter's `cargo-targets/` child if
procfs proves the observation complete and no live process holds it. It leaves
`agent-tmp/` alone because the follow-up may read files from the starter's `$TMPDIR`.
Gate handoffs still leave cleanup to the hourly pass. That pass runs a dead-launch
backstop over the launch-keyed buckets (`agent-tmp/`, `cargo-targets/`,
`build-targets/`): entries whose newest descendant write predates
`managed_tmp.dead_launch.grace_seconds` (2 hours by default) and that the batch procfs
observer reports as held by no live process are removed largest-first within the removal
budget. Held and incomplete-observation entries are preserved and counted
(`dead_launch_preserved_live`, `dead_launch_preserved_incomplete`), and hosts without
readable procfs report `dead_launch_observer: unobservable` and leave the age horizons
as the fallback. A zombie or dead process has already released its address space and
cwd, so it is never counted as a holder or as an incomplete observation.

Each run removes at most 2,000 entries by default so a long-neglected root converges
over several passes instead of stalling one. The reaper also runs a pressure pass when
the managed root grows beyond 16 GiB by default, or when the filesystem holding it falls
below SASE's shared disk-pressure warn threshold: the larger of 3 GiB and
[`disk.pressure.warn_free_percent`](../config/runtime-and-storage.md#disk) (5% by
default) of that filesystem. Under pressure, aged entries of at least 64 MiB in
regenerable build-output buckets (`cargo-targets/`, plus `build-targets/`), and
cargo/core target-shaped top-level residue, are removed largest-first until the root is
estimated below 8 GiB, available space is estimated back above that same warn threshold,
or the removal budget is reached. Pressure pruning is liveness-aware while the procfs
observer is available: a held entry is never removed, an entry whose liveness is
incomplete is preserved, and an unheld entry needs only the dead-launch grace rather
than the pressure minimum age. Pressure pruning otherwise waits 12 hours, but once the
free-space floor is breached it uses the lower configured low-space age, 1 hour by
default, without weakening the fresh-descendant check. The horizons, removal budget,
root-size limits, pressure ages, and minimum pressure entry size are configurable under
`managed_tmp` in `sase.yml`; see
[Configuration](../config/runtime-and-storage.md#managedtmp). The housekeeping job,
`disk_pressure`, and `sase disk reap` all derive the free-space floor and recovery
target from the `disk.pressure` policy rather than from
`managed_tmp.pressure.min_available_bytes` and `recovery_available_bytes`. Generic agent
scratch, handoff buckets, artifact buckets, unknown buckets, symlinks, and build trees
with fresh descendants are not early pressure candidates. The job summary reports
`scanned`, `selected`, and `removed` counts with their byte totals, the same counts
split into `ordinary_*`, `launch_*`, `dead_launch_*`, and `pressure_*` passes,
`dead_launch_observer`, `dead_launch_preserved_live`,
`dead_launch_preserved_incomplete`, `pressure_trigger`, `pressure_available_bytes`,
`pressure_recovery_available_bytes`, `pressure_min_age_seconds`, `deindexed`, `skipped`,
`failed`, `incomplete_observations`, and `capped=1` when it hit that budget, plus the
`roots` it scanned and their count as `roots_scanned`. Every run logs one line per root
it scanned plus an informational line listing all scanned roots. A mismatch between the
effective root and the default `$SASE_HOME/tmp` is harmless — both are reaped — so there
is no warning for it. Reaped directories are dropped from the agent artifact index too,
since a workflow launched without an explicit `artifacts_dir` gets one under
`workflow-artifacts/`. It lives on `housekeeping` rather than an interactive path
because the first pass over a neglected root walks tens of thousands of entries.

The `proc_runtime_sweep` job bounds `~/.sase/procs/runtime`. Both halves of proc runtime
retention run in the Rust proc runtime-retention owner. Proc-row retention deletes
runtime directories for rows it actually pruned in the same operation as log cleanup.
This hourly sweep handles historical rowless runtime directories separately: it removes
only canonical proc-id directories that are direct, non-symlink children of the runtime
root, older than the configured `procs.runtime_orphan_horizon_seconds`, absent from the
proc store after a locked re-read, and within `procs.runtime_orphan_max_removals`.
Fresh, invalidly named, symlinked, active, or otherwise retained entries are preserved.
The summary reports `scanned`, `selected`, `removed`, `skipped`, `errors`,
`reclaimable_bytes`, `reclaimed_bytes`, and `capped`.

The `disk_pressure` job measures the filesystems that hold the managed temp root and
`~/.sase` (once per distinct filesystem) and classifies them through the Rust
disk-pressure policy: a filesystem is under pressure when its free space falls below the
larger of 3 GiB and
[`disk.pressure.warn_free_percent`](../config/runtime-and-storage.md#disk) of its size.
With no pressure, the job exits with reason `space_ok` without scanning the disk
footprint. Under pressure, it logs the largest owners from `sase disk list` and, when
any qualify, sends a notification naming them; when the inventory's `unattributed` row
(filesystem used minus attributed bytes on the `SASE_HOME` filesystem) exceeds the
largest attributed owner, the notification leads with that row instead of pointing at a
small owner. The job then runs unattended owner-safe cleanup early: the managed-temp
reaper, using the measured free space and warn threshold as its pressure floor and
recovery target (with the same dead-launch backstop and liveness-aware pressure the
hourly pass runs), and the proc cleanup owner (proc-row and log retention plus the
rowless runtime sweep). Those owners encode their own deletion policy, and one owner's
failure is reported without skipping the next. Workspace Git-object compaction is left
to an explicit `sase disk reap --apply`, and artifact run directories, backups, and
unowned Cargo-shaped strays are reported for human action; this job never touches them.
The summary reports the free percentage, effective warn threshold, owner and step
counts, and how many steps changed or failed.

The `bead_stale_cleanup` job is the other half of the task-bead `+1` bar. Ready task
beads that never clear their
[effective `+1` bar](../work-units/beads.md#per-type-triage-bar) stay `ready` (the
five-minute `bead_task_triage` job withholds their `TaskTriage` gate) and would
otherwise accumulate forever. Once at least
[`bead.task_triage.stale_cleanup_min_beads`](../config/automation-behavior.md#bead) of
them have sat below that bar for
[`bead.task_triage.stale_after_days`](../config/automation-behavior.md#bead) days, this
hourly pass raises one human-only `BeadStaleCleanup` gate for the whole backlog — one
gate across every enabled project, not one per project. The offered roster is capped at
50 beads, oldest first, with a `(project, bead_id)` tie-break; any remainder is named in
the preview as `omitted_count` and is offered on a later tick. Lane state holds the
pending request, a generation counter, and a fingerprint over the offered roster plus
the three thresholds (not the pinned `stale_as_of` date), so an unchanged roster leaves
the pending gate alone and a changed roster replaces it. When the backlog drops below
the bar the pending gate is canceled. A project whose store cannot be read is skipped
and cannot cancel a healthy pending gate, because the true roster is then unknown. Run
`sase axe job run bead_stale_cleanup` to raise or refresh that gate without waiting for
the hour.

The `gate_turn_reclaim` job is the backstop for
[gate turns](notification-gates.md#gate-turns-and-continuation). It scans gate-turn
session members across projects, settles turns whose gate bundle is already terminal,
cancels gates that reached their own deadline, and force-settles a turn as `lost` once
`gate.turn.reclaim_grace_seconds` (one hour by default) has passed after that deadline.
Reclaim skips a turn whose gate creation is still running (its session's gate-creation
lock is held), so an `%auto` gate that is still executing its selected commands is never
marked lost; a turn whose creator died before recording a bundle is still settled lost
on a later pass. It then diagnoses settled gates whose requested successor never
recorded, reading the agent artifact index once per pass and resuming from a per-project
cursor. Work left when the pass-wide time budget runs out is deferred to the next tick.

The `artifact_link_backfill` job runs four bounded jobs per enabled project. It sweeps
older documents for deterministic derived links, resuming from a per-project checkpoint
when one tick's budget is exhausted; drains audited-read outbox rows whose agents have
since published; reconciles cross-workspace local aggregates; and repairs dangling refs
from Git rename history. A large derivation backlog converges over several hourly ticks
instead of rescanning the full corpus each time. Run
`sase axe job run artifact_link_backfill` for an immediate pass. The link model and
doctor counters are documented in [Artifact Links](../artifact-links.md).

The `artifact_run_prune` job is a read-only preview for old `artifacts/ace-run/`
directories. Protection facts are gathered in Python, while the preview classification,
symlink safety check, and empty-shard walk run in the Rust run-retention owner. The
preview keeps the newest `artifacts.retention.keep_recent_run_months` calendar months
whole and protects runs that are incomplete, running, waiting, or asking a question;
runs referenced by artifact-file rows, text refs, agent names, or continuation ancestry;
runs tied to non-closed beads; and symlinked run directories. If continuation retention
planning fails, every candidate is protected (`continuation_unavailable`) instead of the
job crashing. The summary reports `candidates`, `selected` run directories,
`empty_shards` outside sase's TUI startup watch window, reclaimable `bytes`,
`protected`, and `unavailable` protection sources; any unavailable source turns the run
into `check_error`. Whenever the preview finds candidates or protection problems, the
job upserts an Axe `ViewReport` notification that names the preview command
(`sase artifact prune-runs`). The notification is deduplicated by a fingerprint of the
findings, so an unchanged preview adds a `+1` note to the existing notification rather
than a new one. Artifact-run deletion is currently preview-only; apply requests fail
closed before any run directory, empty shard, or artifact-index row is removed.

## Related

- [Default scheduler routines](scheduler-default-routines.md)
- [Scheduler](scheduler.md)

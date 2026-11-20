---
title: Scheduler housekeeping
description: Tasks handled by the scheduler's housekeeping routine.
---

# Scheduler housekeeping

This page describes the scheduler housekeeping routine.

## housekeeping (1-hour interval) {#housekeeping-1-hour-interval}

Periodic maintenance:

| Job                          | Description                                                                                                           |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `error_digest`               | Send error notification digests (creates `ViewErrorReport` notification action)                                       |
| `footprint_fold`             | Fold local Footprint spool records into the daily census ledger                                                       |
| `notification_store_compact` | Archive old dismissed notifications out of the live JSONL store                                                       |
| `managed_tmp_reap`           | Prune stale scratch under every registered managed SASE temp root                                                     |
| `proc_runtime_sweep`         | Prune stale rowless proc runtime directories                                                                          |
| `state_retention`            | Apply ToolRun log retention on a schedule, remove emptied run dirs, and reap proc log-lock and registry temp backlogs |
| `disk_pressure`              | Notify on disk pressure and run owner-safe cleanup early                                                              |
| `bead_stale_cleanup`         | Sweep stale sub-threshold ready task beads into one `BeadStaleCleanup` gate                                           |
| `gate_turn_reclaim`          | Settle pending gate turns whose gates answered, canceled, expired, or vanished                                        |
| `staged_handoff_reconcile`   | Recover finalized handoffs and notify once on recorded holds                                                          |
| `artifact_link_backfill`     | Derive and reconcile artifact links, drain reads, and repair refs after a rename                                      |
| `artifact_retention`         | Enforce indexed artifact-file retention and purge expired trash                                                       |
| `artifact_run_prune`         | Preview old ace-run directories and empty shard cleanup                                                               |

The `staged_handoff_reconcile` job recovers staged handoffs after the originating
process dies and host finalization is complete. Each pass attempts at most 32 candidates
and stops starting further candidates after a 60-second budget; an in-flight attempt can
outlast that budget. Discovery and pending candidates are saved for the next pass. The
scan includes finished turns and historical artifacts. Recovery reuses recorded
destinations and does not rerun the originating provider or finalizers. Recorded holds
require [`sase agent readopt`](../agents/agent-sessions.md#handoff-recovery); a new hold
recorded by this job sends a notification with that command, deduplicated by origin,
stage, and cause. Live or unobservable runners, killed or discarded stages, and
incomplete finalization prevent automatic activation.

## publication (15-second interval)

| Job                 | Description                                                  |
| ------------------- | ------------------------------------------------------------ |
| `agent_publication` | Drain queued hood, artifact-link, and Referenced By requests |

The routine watches `~/.sase/projects/*/agent_publication/doorbell` and also runs on a
five-minute backstop. It handles hinted hood requests first, then drains the oldest
remaining hood requests and publishes link-outbox rows for all hinted agents in one
pass. It converts active legacy Referenced By requests to `cites` events in fenced
projects and refreshes them in unfenced projects. A pass has a four-minute work budget.
The publisher rings again for publishable hood work, active Referenced By requests, lock
contention, or work deferred by the budget; a raised or deferred link drain keeps its
hint and rings again. Rows retained by a completed link drain stay durable for the
hourly `artifact_link_backfill` routine and do not keep their hint. A project without a
usable agents sidecar is skipped without an error unless it has queued publication rows,
and the job never rings the doorbell for it. The job writes per-project queue counts,
oldest request age, and its last outcome—including the retained link-row count—to
`~/.sase/agent_publication/heartbeat.json`.

The `error_digest` job snapshots the durable interval counter and writes a grouped
digest file at `~/.sase/axe/error_digests/digest_<timestamp>.txt`. The header states the
true total, cause count, samples kept, and coverage interval
(`312 errors from 7 causes (100 samples kept), 14:02–15:02`). A delayed digest covers
the whole interval since the previous snapshot, including downtime. Failed writes or a
corrupt file set aside make the total `≥N` and name that count. Each cause gets one line
(count, routine/job, first/last time, truncated sample) plus a detail block with the
existing traceback and subprocess-output rendering. The notification note is
`312 errors from 7 causes since 14:02` and still uses `ViewErrorReport` with
`error_report_path`. A crash after snapshot and before notify re-sends the pending
interval exactly once, keyed by interval id. The job prunes digest files older than 30
days, always keeping the newest 50, at most once per day. Missing digest files already
degrade gracefully in ViewErrorReport and mobile attachments. Silent, missing,
unreadable, malformed, and truncated output are called out explicitly instead of being
reported as a Python traceback.

The `notification_store_compact` job bounds `~/.sase/notifications/notifications.jsonl`
by moving dismissed rows older than 3 days into `notifications-archive.jsonl`. Unread
and still-actionable rows stay in the live file. sase's TUI snapshot reads are memoized
against an mtime+size token, so this pass lives on `housekeeping` rather than the TUI
refresh cadence.

The `footprint_fold` job ingests a changed catalog, folds pending local usage records,
applies spool retention, and prunes daily aggregates older than
[`footprint.retention_days`](../config/runtime.md#footprint). After the fold it
refreshes derived census rows from macro launches, skill-use logs, the current
config-override snapshot, and AXE cycle telemetry. It runs hourly because the spool is
append-only on CLI and TUI paths. A busy ledger skips the pass so an interactive status
read can continue with the existing snapshot.

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
as the fallback. An unreadable SSH or Tailscale session can be exempted only when its
procfs ancestry reaches an init-started process in `/system.slice/`, every ancestor has
no same-uid identity, and pid start times are consistent. Orphans, same-uid or sudo
ancestors, missing or malformed proc files, cgroup v1, ancestry cycles, and walks past
the depth limit remain incomplete. A zombie or dead process has already released its
address space and cwd, so it is never counted as a holder or as an incomplete
observation. Incomplete skip diagnostics name the blocking pid, command, and parent pid;
the Rust reaper keeps up to eight lines per reason and reports any remainder.

When directory deletion fails with `PermissionDenied`, the Rust reaper adds owner write
and execute permission to current-user-owned real directories inside that candidate and
retries once. It never follows symlinks or repairs the parent bucket. Removal errors
remain visible in the job log. `managed_tmp_reap` logs up to five removal errors and
five skip reasons per root, then reports `check_error` with `reason=removal_failed` if
any removal failed. An incomplete liveness observation by itself does not make this job
an error.

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

The `state_retention` job applies the existing `tool_run_retention` owner — the same
step as [`sase disk reap`](../disk-cleanup.md) and `disk_pressure` — at most once per
[`tool_runs.housekeeping_interval_seconds`](../config/runtime-and-storage.md#toolruns)
(default one hour), whether or not the filesystem is under pressure. It then removes
empty run directories under `~/.sase/tools/logs` without following symlinks. It adds no
second tool-run policy. `clutter_reapers` adds two further owner steps to this same
chop, running on every pass: `proc_log_lock_sweep` reaps orphaned `.log.lock` files
under `~/.sase/procs/logs` (no log sibling, no referencing proc row, older than
`procs.log_lock_orphan_horizon_seconds`), and `registry_tmp_sweep` reaps stale
agent-name registry temp files (older than `agent_names.registry_tmp_horizon_seconds`).
Agent-index `*.bak` backups are report-only and never reaped.

The `disk_pressure` job measures the filesystems that hold the managed temp root and
`~/.sase` (once per distinct filesystem) and classifies them through the Rust
disk-pressure policy: a filesystem is under pressure when its free space falls below the
larger of 3 GiB and
[`disk.pressure.warn_free_percent`](../config/runtime-and-storage.md#disk) of its size.
With no pressure, the job exits with reason `space_ok` without scanning the disk
footprint and ends any active pressure episode. Under pressure it reaps first
(managed-temp, using measured free space and the warn threshold as its pressure floor
and recovery target, plus proc-row/log retention and the rowless runtime sweep, plus the
proc log-lock and registry temp sweeps, plus tool-run retention). Hourly
`state_retention` applies that same tool-run owner without waiting for pressure.
Inventory collection runs afterward under a 20s fail-open cap: an exception or timeout
becomes "attribution unavailable" in the notice and never skips or delays recovery. The
notice leads with free space and the recovery result, names unmeasured owners, lists
only measured top owners, and labels the residual the way
[`sase disk list`](../disk-cleanup.md) does. Upserts use an episode-scoped key
`disk_pressure:<filesystem>:<episode>` so later passes in the same pressure episode +1
the same row; `space_ok` ends the episode and the next pressure event creates a new row.
When available space after the reap is still below the recovery target, a distinct
escalation row (`…:escalation`) states the target, reclaimed bytes, available-after
bytes, blocked or incomplete owners with reason counts, and the largest measured owners
this job does not reap (workspaces, artifact runs, the rust-prebuild cache) with their
reclaim commands. A notification exception is logged on one bounded stderr line and does
not undo the reap.

Afterward, the job remeasures available bytes on the pressured filesystem with
`statvfs`. Its status is `no_op` with `space_ok` when no pressure was present;
`check_error` when an owner failed, the notification failed, or the free-space recheck
failed; `check_error` with `recovery_blocked` when pressure remains and an owner was
blocked or incomplete; `check_error` with `recovery_missed` when the target is missed
without a blocked or incomplete owner; `ok` when an owner changed state and the target
was met; and `no_op` with `nothing_eligible` when nothing changed and no owner was
blocked. Incomplete owners are judged by their normalized cleanup status, not by a
step's broad failure flag. Workspace Git-object compaction is left to an explicit
`sase disk reap --apply`, and artifact run directories, backups, and unowned
Cargo-shaped strays are reported for human action; this job never touches them. The
summary includes changed and failed owner names, reclaimed and post-reap available
bytes, the recovery target, and notification outcome.

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
cursor. An eligible interrupted launch waits 120 seconds for indexing, then gets one
supervised resume attempt. If reclaim already submitted that attempt or submission
fails, it sends one notification with the resume command. Work left when the pass-wide
time budget runs out is deferred to the next tick.

The `artifact_link_backfill` job runs four bounded jobs per enabled project. It sweeps
older documents for deterministic derived links, resuming from a per-project checkpoint
when one tick's budget is exhausted; drains audited-read outbox rows whose agents have
since published; parks operations whose bead endpoints are removed, absent, or foreign
onto a replayable parked ledger (re-checked at most once every 24 hours); reconciles
cross-workspace local aggregates; and repairs dangling refs from Git rename history. A
document counts as swept once each of its derived candidates is durable or parked, so an
error on one document no longer holds back the rest of its chunk. The drain moves
never-published rows of long-finished agents into the dropped audit at most once per 24
hours per project, and every project in a tick shares one agent catalog build for that
check. Each drain logs per-phase timings
(`drain phases: read=… evidence=… eligibility=… catalog=… publish=… rewrite=…`).
Reconcile starts only when its learned duration fits the remaining budget; the first
project of a tick always reconciles. Drain or reconcile work deferred for budget is
logged as a warning, and that project goes first on the next tick. Counters include
`bead_projection_failed`, `parked_new`, `parked_total`, `transient`, and
`stale_checked_projects`. A hard bead projection failure this tick sets status
`check_error` with reason `bead_projection_failed` even if traversal completed; parked
operations alone are not an error. A large derivation backlog converges over several
hourly ticks instead of rescanning the full corpus each time. Run
`sase axe job run artifact_link_backfill` for an immediate pass. The link model and
doctor counters are documented in [Artifact Links](../artifact-links.md).

The `artifact_retention` job owns indexed artifact-file retention. It runs the same
bounded pass that used to sit on every agent finalization: plan with
[`artifacts.retention`](../config/artifacts.md#artifacts) plus the protection scan,
trash selected automatic captures, and purge trash past the grace period. Every
completed pass writes `~/.sase/artifact_retention.json` with the time and outcome,
including a skip because retention is disabled or a protection source is unavailable. A
non-blocking exclusive lock excludes overlapping passes. Agent finalization only runs
the same pass when that stamp is missing or older than 24 hours, so a machine without a
scheduler still enforces retention at least daily, and it skips immediately when the
lock is busy. Run `sase axe job run artifact_retention` for an immediate pass. See
[SASE disk cleanup](../disk-cleanup.md) and
[Store Lifecycle](../agent-attachments.md#store-lifecycle).

The `artifact_run_prune` job first purges expired run-trash batches, restoring any runs
that gained a protection reference. It then previews old `artifacts/ace-run/`
directories. Protection facts are gathered in Python, while the preview classification,
symlink safety check, and empty-shard walk run in the Rust run-retention owner. The
preview keeps the newest `artifacts.retention.keep_recent_run_months` calendar months
whole and protects runs that are incomplete, running, waiting, or asking a question;
runs referenced by artifact-file rows, text refs, agent names, or continuation ancestry;
runs tied to non-closed beads; runs an unresolved
[Agent Hijack](../agents/agent-sessions.md#hijack-recovery) still holds for recovery,
including expired holds; and symlinked run directories. If continuation retention
planning fails, every candidate is protected (`continuation_unavailable`) instead of the
job crashing. The summary reports `candidates`, `selected` run directories,
`empty_shards` outside sase's TUI startup watch window, reclaimable `bytes`,
`protected`, and `unavailable` protection sources; any unavailable source turns the run
into `check_error`. When the preview finds protection problems, empty shards, or a run
selection worth a nudge, the job writes a review snapshot and upserts an actionable Axe
`ViewReport` notification. A run selection is worth a nudge only when its reclaimable
bytes reach `artifacts.retention.run_prune_notify_min_bytes` (default 1 GiB) or the
runs' filesystem is under the same managed disk-pressure thresholds as the
`disk_pressure` job; a smaller selection on a roomy disk retires any live preview
instead. The notification is episode-deduplicated: a repeat of the current preview adds
a `+1` note; any change, including a return to an earlier fingerprint, starts a fresh
row and retires older preview rows; a clean nothing-to-prune run retires them too. Enter
opens the snapshot review. In a ready review, `y` quarantines the reviewed runs into
journaled, restorable trash (`sase artifact prune-runs --apply`, optionally restricted
with `--snapshot`). When protections were unreadable or the snapshot is missing, `y`
starts a durable re-check that republishes the preview
(`sase artifact prune-runs --publish-preview`). Protections are re-verified before every
move, and unattended apply paths still refuse. The hourly job permanently purges batches
after the configured `artifacts.retention.trash_grace_days` period; runs that gain a
protection reference are restored instead.

The review panel shows the snapshot age, selected run count and bytes, protected count,
retained month window, and project totals. A preview older than 24 hours is marked
stale; apply still rechecks the captured selection. `r` opens the full report. In a
ready review, `y` confirms **Move to trash**. When protections were unreadable or the
snapshot is missing, `y` starts a re-check that republishes the preview. `n` or `Esc`
cancels. Confirmation is disabled while the snapshot is being checked or while a prune
or re-check is already running. Cancel has initial focus.

Confirmation starts a background process using the snapshot's selection identifier
(fingerprint), so closing the TUI does not cancel the operation. Its result reports
moved, kept, and failed runs and any index errors. See
[Run directory retention](../artifact-references.md#run-directory-retention) for batch
restoration and purge behavior.

## Related

- [Default scheduler routines](scheduler-default-routines.md)
- [Scheduler](scheduler.md)

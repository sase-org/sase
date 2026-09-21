# Scheduler — Background Automation

## Overview

The scheduler is the background automation subsystem of sase. It watches Patches (the
per-PR records that sase uses to track work) and periodically runs lifecycle jobs such
as hook completion, mentor launch, workflow cleanup, comment polling, `%wait` dependency
checks, and error digests. AXE is its former name and remains an accepted alias:
`sase axe start|stop|restart|status` is the same command as
`sase scheduler start|stop|restart|status`.

The scheduler uses a multi-process architecture: an **Orchestrator** spawns multiple
**Routines**, and each routine runs a subset of jobs on its own schedule.

Two commands own two different layers:

- **`sase service`** owns the **service host**: the per-machine host process
  (`sase service run`) that starts, restarts, and stops that machine's service procs.
  `sase service init` registers it as a platform unit — a systemd user unit on Linux, a
  launchd LaunchAgent on macOS — so it starts at boot or login.
- **`sase scheduler`** owns the **scheduler service proc**: the builtin service proc
  that runs the automation. Its start, stop, restart, and status commands route through
  the `scheduler` service proc on the service host; `sase scheduler run` execs the
  foreground orchestrator that the service host itself runs.

The `sase axe` surface remains for the routine/job tree (`sase axe job`,
`sase axe routine`, `sase axe maintenance`) alongside the four lifecycle aliases.

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                              Orchestrator                             │
│                    (spawns & monitors all routines)                   │
├───────────┬──────────┬────────────┬───────────┬──────────┬────────────┤
│ hooks     │ waits    │ checks     │ external_ │ comments │ housekeep- │
│ (5s)      │ (10s)    │ (5min)     │ mirror    │ (1min)   │ ing (1hr)  │
│           │          │            │ (15min)   │          │            │
│ hook_     │ wait_    │ bead_task_ │ external_ │ comment_ │ error_     │
│ checks    │ checks   │ triage     │ issue_    │ checks   │ digest     │
│ mentor_   │ bead_    │ pr_sub-    │ mirror    │          │ managed_   │
│ checks    │ claim_   │ mitted_    │ external_ │          │ tmp_reap   │
│ workflow_ │ checks   │ checks     │ pr_mirror │          │ disk_      │
│ checks    │ ...      │ ...        │           │          │ pressure   │
│ ...       │          │            │           │          │ ...        │
└───────────┴──────────┴────────────┴───────────┴──────────┴────────────┘
```

### Key Concepts

- **Orchestrator**: Parent process that spawns and monitors all routine processes.
  Detects crashes and restarts failed routines automatically. Holds the axe lifecycle
  lock while running and forwards SIGTERM to all children on shutdown.

- **Routine**: Individual scheduler loop that runs a subset of jobs on a fixed interval.
  Each routine has a name (e.g., "hooks", "checks"), runs one or more jobs per cycle,
  and maintains independent state and metrics.

- **Job**: A single script-only job unit executed by a routine. The executable reads
  context JSON and may return a structured result containing validated agent-launch
  proposals. The runner, never the script, launches those agents. Jobs can declare
  cadence, triggers, guards, target fan-out, environment, and dedupe policy.

- **Candidate Patches**: Every cycle (checks, jobs, and the routine job list) first
  filters out Patches with [`PR_ORIGIN: external`](change_spec.md#pr_origin) before any
  job evaluates them. Axe never acts on a Patch adopted from a PR it didn't create.

## CLI Commands

`sase axe job` and `sase axe routine` default to their `list` views when invoked without
a nested subcommand.

| Command                                | Description                                                           |
| -------------------------------------- | --------------------------------------------------------------------- |
| `sase scheduler`                       | Show scheduler status through the `scheduler` service proc            |
| `sase scheduler start`                 | Start the `scheduler` service proc                                    |
| `sase scheduler stop`                  | Stop the `scheduler` service proc                                     |
| `sase scheduler restart`               | Restart the `scheduler` service proc                                  |
| `sase scheduler run`                   | Run the scheduler orchestrator in the foreground                      |
| `sase axe start`                       | Alias of `sase scheduler start`                                       |
| `sase axe stop`                        | Alias of `sase scheduler stop`                                        |
| `sase axe restart`                     | Alias of `sase scheduler restart`                                     |
| `sase axe status`                      | Alias of `sase scheduler status`                                      |
| `sase axe status --json`               | Emit the `scheduler` service proc record as JSON                      |
| `sase axe job list`                    | List configured jobs with status (`-a` adds discoverable scripts)     |
| `sase axe job list -v`                 | Add full descriptions, resolution paths, and search-directory detail  |
| `sase axe job list --json`             | Emit the job inventory as a schema-version-2 JSON object              |
| `sase axe job doctor`                  | Diagnose configured/available jobs and Telegram setup (`-j` for JSON) |
| `sase axe job run <name>`              | Run a single job in the foreground                                    |
| `sase axe job run <name> -L <routine>` | Run a single job attributed to a specific routine                     |
| `sase axe routine list`                | List configured routines and their enabled jobs                       |
| `sase axe routine list -v`             | Add each routine's full description under `details`                   |
| `sase axe routine run <name>`          | Run a single routine in the foreground                                |
| `sase axe routine status`              | Show status of all routines                                           |
| `sase axe maintenance enter -r <text>` | Pause routine ticks until maintenance exits                           |
| `sase axe maintenance exit`            | Clear the maintenance marker                                          |
| `sase axe maintenance status`          | Show whether maintenance mode is active                               |

### Compatibility aliases

Current commands, configuration, examples, and public JSON use routine/job terms. The
older names remain accepted as compatibility aliases where existing installations may
still send them:

| Legacy spelling                                                   | Current spelling                                       | Notes                                                                    |
| ----------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------ |
| `sase axe lumberjack ...`                                         | `sase axe routine ...`                                 | Hidden CLI alias; completions and help advertise `routine`.              |
| `sase axe chop ...`                                               | `sase axe job ...`                                     | Hidden CLI alias; legacy invocations keep schema-version-1 JSON.         |
| `axe.lumberjacks.<name>.chops`                                    | `axe.routines.<name>.jobs`                             | Accepted on input; effective config and new examples use canonical keys. |
| `chop_script_dirs`, `chop_timeout`                                | `job_script_dirs`, `job_timeout`                       | The old keys remain input aliases.                                       |
| `lumberjack_log_*`, `lumberjack_restart_backoff_max_seconds`      | `routine_log_*`, `routine_restart_backoff_max_seconds` | The old keys remain input aliases.                                       |
| `verbose_lumberjack_diagnostics`                                  | `verbose_routine_diagnostics`                          | The old key remains an input alias.                                      |
| `SASE_CHOP_*`, `sase_chop_*`, `sase.chops`                        | `SASE_JOB_*`, `sase_job_*`, `sase.jobs`                | Script authors should use the job-named entrypoints and SDK facade.      |
| `sase_chop_tg_inbound`, `sase_chop_tg_outbound` (`sase-telegram`) | `sase_job_tg_inbound`, `sase_job_tg_outbound`          | `sase axe job doctor` warns when only the legacy entrypoints are found.  |
| `chop:<routine>/<job>` artifact references                        | `job:<routine>/<job>` artifact references              | Both resolve to the same stored link identity.                           |
| `sase doctor -C axe.chops`                                        | `sase doctor -C axe.jobs`                              | The old check ID remains a selection alias.                              |
| Stored `chop` agent tribe                                         | `job` tribe                                            | See [Structured Results](#structured-results-and-launch-proposals).      |

The `axe_routine_job_contract` [feature flag](configuration.md#feature_flags), a sunset
flag that is on by default, controls the public projection. While it is on, canonical
commands such as `sase axe job list --json` and `sase axe job doctor --json` emit
schema-version-2 JSON with routine/job field names (for example `routines`,
`routine_name`, `configured_jobs`, and `jobs`), and `sase config show` prints the AXE
block with canonical keys. Hidden legacy `chop` commands, and every command while the
flag is off, keep the schema-version-1 envelopes. Runtime state paths and durable
registries are not migrated: directories under `~/.sase/axe/lumberjacks/`, per-job
`chops/` subdirectories, and `agent_chops.json` remain intentionally legacy-named
storage.

### Examples

```bash
# Start/stop the scheduler service proc (`sase axe start|stop` is the same command)
sase scheduler start
sase scheduler stop

# Ask the host to stop and start the scheduler proc; returns once recorded
sase scheduler restart

# Show the scheduler service proc's status
sase scheduler status
sase scheduler status --json

# Run the foreground orchestrator against only matching Patches
sase scheduler run --query '!!! OR @@@'

# Inspect routines
sase axe routine list
sase axe routine list --verbose  # also print each description body
sase axe routine status

# Run a single routine for debugging
sase axe routine run hooks

# Inspect configured jobs and discoverable scripts
sase axe job list
sase axe job list --available --verbose
sase axe job doctor            # exits 1 if a configured script job cannot be resolved

# Run a single job once
sase axe job run hook_checks

# Preview a proposal-emitting job without launching agents
sase axe job run 'refresh_docs[sase]' -L docs --dry-run --job-verbose

# Disambiguate when the same job name appears in multiple routines
sase axe job run hook_checks --routine hooks   # -L is the short form

# Pause/resume scheduled routine work
sase axe maintenance enter --reason "install plugin update"
sase axe maintenance status
sase axe maintenance exit
```

## Scheduler Status

`sase scheduler status` shows the `scheduler` service proc's status through the service
host: name and summary, source, effective enablement, desired and runtime state,
launcher, and log path. It changes no host state. `sase scheduler status -j`
(equivalently `--json`) emits that same proc record as a stable JSON object, with
deterministic formatting and no Rich markup or ANSI escapes.

Use these related commands according to intent:

- `sase scheduler status` is the read-only first look at the scheduler proc.
- `sase scheduler restart` is the explicit operator action: it asks the host to stop and
  start the proc and returns once the request is recorded. When the scheduler is down
  unexpectedly, recovery is the service host's `Restart=on-failure` plus `sase doctor`;
  see [Supervision and Recovery](#supervision-and-recovery).
- `sase doctor --deep` runs broader, slower diagnostics when the status evidence needs
  deeper investigation.
- `sase axe maintenance status` remains the compatibility/debugging view of only the
  maintenance marker.
- `sase axe routine status` remains the compatibility/debugging process view for
  individual routines.

## Default Routines

The scheduler ships with six default routines:

### hooks (5-second interval)

High-frequency hook lifecycle management:

| Job                     | Description                                    |
| ----------------------- | ---------------------------------------------- |
| `hook_checks`           | Complete finished hooks, start stale ones      |
| `mentor_checks`         | Start mentors once hook prerequisites are met  |
| `workflow_checks`       | Complete/start CRS and fix-hook workflows      |
| `pending_checks_poll`   | Poll background check results                  |
| `comment_zombie_checks` | Mark old comment threads as ZOMBIE             |
| `suffix_transforms`     | Strip stale suffixes, update mail-readiness    |
| `orphan_cleanup`        | Release workspace claims for dead processes    |
| `stale_running_cleanup` | Release claims and proc rows of dead processes |

Every job above except `stale_running_cleanup` ships with an `fs` trigger so an idle
tick costs a handful of `stat()` calls instead of a subprocess spawn: the six
Patch-driven jobs watch every enabled project's ProjectSpec file
(`paths: [{path: projects, glob: "*/*.sase"}, {path: projects, glob: "*/*.gp"}]`), and
`pending_checks_poll` watches the sharded `~/.sase/checks/` output directory. Each
carries `max_quiet: "120s"`, so a missed observation only delays a fire by up to two
minutes. `stale_running_cleanup` keeps the default `always` trigger: its actual input is
process liveness (a claim's owning PID dying), which has no filesystem proxy — a dead
PID does not touch any project, claim, or artifact file.

### waits (10-second interval)

Fast-polling agent dependency resolution:

| Job                 | Description                                                            |
| ------------------- | ---------------------------------------------------------------------- |
| `bead_claim_checks` | Acquire/release bead claims for pre-launch agents                      |
| `epic_launch_flush` | Flush planner completions orphaned by unsettled epic launches          |
| `sidecar_auto_sync` | Fetch/fast-forward opted-in primary sidecar clones (plans, beads, ...) |
| `wait_checks`       | Resolve successful agent and closed-bead waits; write `ready.json`     |

`bead_claim_checks` and `wait_checks` both ship with an `fs` trigger watching the
agent-artifact tree (`paths: [{path: projects, glob: "*/artifacts/ace-run/*"}]`,
`max_quiet: "120s"`), so an idle tick only re-scans when a project gains a new agent
artifact. `epic_launch_flush` and `sidecar_auto_sync` are untouched by that guard; they
already throttle via `run_every: "30s"`.

`wait_checks` unblocks a named dependency when the newest matching agent, or the newest
matching workflow root and all of its children, has a successful terminal `done.json`
outcome: `"completed"`, `"noop"`, `"epic_approved"`, or `"plan_committed"`. A wait on an
epic-approved planner waits for that planner, not for the host-owned epic it launched;
use bead waits or a wait on the launched epic clan for that. `"noop"` agents can also
satisfy waits even though they are hidden from normal done-agent lists. Failed, killed,
stopped, crashed, still-running, malformed, or missing `done.json` artifacts do not
satisfy `%wait`; the dependent agent remains parked until a later successful run of the
same dependency name appears. `"plan_rejected"` is deliberately identity-terminal for
exact artifact waits but does not satisfy a named `%wait`.

If an unresolved dependency already has a terminal `done.json` outcome that wait
resolution does not recognize, `wait_checks` increments `unknown_outcome` and logs the
artifact directory plus the offending outcome. The job also emits a bounded sample of
waiters blocked by terminal dependencies so permanent stalls are diagnosable without
spamming ordinary live waiters.

Markers may also carry `wait_for_beads`, emitted by `%wait(bead=<bead-id>)`.
`wait_checks` reads the waiting agent's project bead store once per cycle and releases
the marker only when every named bead is closed as well as every agent or artifact
dependency being satisfied. Missing beads, unavailable stores, and read failures
deliberately fail closed and leave the agent parked; sase's TUI run-now action remains
the manual escape hatch. While live bead waits are outstanding, `sidecar_auto_sync`
hints their projects' `beads` role every 30 seconds — even when that role has not opted
into `auto_sync` — so the one conservative fetch/fast-forward sync policy converges it
promptly instead of a competing managed-integration refresh path. The waiting runner
also marks the same hint on a coarser ten-minute cadence as an outage backstop, in case
a job failure ever leaves the tick-driven hint unconsumed. Setting
`sdd.bead_refresh.mode: off` disables both hint paths.

### checks (5-minute interval)

Lower-frequency status checks:

| Job                     | Description                                                  |
| ----------------------- | ------------------------------------------------------------ |
| `bead_task_triage`      | Reconcile the one pending gate each task bead owns           |
| `plugins_required`      | Raise one `PluginsRequired` gate per project missing plugins |
| `pr_submitted_checks`   | Start PR submission status checks                            |
| `stale_running_cleanup` | Backstop dead-process claim and proc-row cleanup             |
| `usage_refresh`         | Submit due subscription-usage refreshes                      |

**A live task bead has at most one pending gate**, and `bead_task_triage` is the single
owner of that invariant. It scans enabled non-home projects for task beads and derives
one of three gate kinds from that one issue type: a ready task gets a `TaskTriage` gate,
a snoozed one gets a `BeadSnooze` gate, and a task bead of type `flag` whose status is
`open` and whose date and release removal thresholds have both passed gets a
`FlagTriage` gate. All three kinds are reconciled in the same pass, under one lock and
one lane state, so no second job can race this one into giving a bead two gates. The
bead-to-request mapping — including which kind each bead currently holds — lives in the
checks routine's state directory. This scan does not call the dependency-aware
`sase bead ready` query, so a stored-ready task with an active blocker still receives a
gate. A flag task bead's due-ness is derived through the one shared `flag_removal_due`
predicate, never recomputed here.

A ready task bead additionally needs at least its
[effective `+1` bar](beads.md#per-type-triage-bar) of independent `+1` reports before it
earns a `TaskTriage` gate: its own task type's `triage.min_plus_ones` (`0` for `ci`,
`feature`, and `memory`; `1` for `bug`; `3` for `flake`), or
[`bead.task_triage.min_plus_ones`](configuration.md#bead) when the bead is untyped or
its type is not registered on this machine. A sub-threshold bead is withheld from triage
without any change to its stored status — it stays `ready` and stays visible to
`sase bead list`, `sase bead ready`, sase's TUI Beads panel, and its bead page — and a
`TaskTriage` gate already raised for a bead that later falls below the bar is canceled
(reason `task_bead_below_plus_one_threshold`) and its notification dismissed on the
job's next tick. Snoozed beads and `flag` task beads are never subject to this bar.

A still-pending gate is skipped on later ticks, preventing repeated notifications. If a
bead leaves its gateable status or type through a launch, close, extension, or manual
retraction, the job cancels its pending gate. If a gate becomes terminal or its bundle
disappears while the bead is still gateable, the next tick replaces it, except while
that bead has an active detached launch in flight. A persistent generation counter gives
each replacement a new deterministic request ID, whether the bead kept its status or
left and came back.

After project discovery succeeds and returns a non-empty inventory, the same
reconciliation also cancels pending gates when their project leaves the active
inventory, and cancels producer-owned gates no longer represented in the routine's lane
state. An unavailable inventory fails closed without sweeping anything. A project whose
bead store is temporarily unreadable is likewise preserved for retry rather than being
mistaken for an inactive project and swept.

Two things also force a replacement. A gate of the wrong kind for the bead's current
status is canceled as `bead_status_changed` and replaced in the same tick — a bead that
was snoozed while its triage gate was pending is asking a different question now, so
that check outranks the presentation comparison below. Otherwise the job compares a
presentation and gate-contract fingerprint over every stored field the gate renders:
status, the whole snooze record, title, description, notes, size, creation time, refs,
+1 evidence, close history, and (for a `flag` task bead) its key, kind, thresholds, and
due state, plus explicit renderer and option-contract versions. A mismatch cancels the
gate as `task_triage_presentation_changed` and re-raises it, so an edited description, a
re-snooze, an extended threshold, or an obsolete interaction contract never leaves a
gate advertising stale content, the old wake time, or superseded controls. While a
`BeadSnooze` gate stays pending and unchanged, the job also re-snoozes its notification
to match the bead's wake time (whenever that wake time is still in the future), keeping
a snoozed bead's notification snoozed alongside it even after a crash or a manual
unmute.

The `TaskTriage` gate presents the task title, description, and notes, and offers three
options. **Launch** (the primary branch) accepts optional feedback and submits a
deduplicated global unattributed proc for `sase bead work <task-id> --yes-to-all`;
**Close** requires a reason and closes the bead as `canceled`; **Snooze** collects one
required `duration` line and defers the task, moving it to `snoozed` so the next tick
reconciles it into a `BeadSnooze` gate instead. The line takes the same
`"<wake-time> [+<N>]"` vocabulary sase's TUI snooze modal takes — for example `3d`,
`2026-08-09T09:00:00-04:00`, or `3d +2` — combining the CLI's `-u` duration and `-p` +1
target into one expression. See
[TaskTriage notifications](notifications.md#command-backed-interaction-gates), the
[snooze workflow](beads.md#snoozing-a-task-bead) for what a `BeadSnooze` gate then asks,
and the [standalone task workflow](beads.md#standalone-task-workflow) for the
human-facing lifecycle.

The `FlagTriage` gate presents the flag's key, kind, both-branch prose, `remove_when`,
both removal thresholds, its countdown, and the registry definition's description (or a
callout when no definition names the key), and offers four options. **Remove** (the
primary branch) deletes the Off branch and makes the On branch unconditional; it
collects a required `winner` choice (`enabled` or `disabled`) for the worker brief and
submits the same deduplicated `sase bead work <flag-id> --yes-to-all` proc; **Extend**
requires a reason plus a new date and release line, pushes both thresholds out, and
leaves the bead `open` so the next tick finds it no longer due and cancels the gate as
stale; **Keep** requires a reason and launches a worker to convert the behavior into an
ordinary config field, then close the bead — it was never a feature flag; **Close**
requires a reason and abandons the removal by closing the bead as `canceled`, leaving
`tools/check_feature_flags`' closed-bead-with-surviving-definition check to catch the
orphan if the flag itself survives.

The `plugins_required` job is the human install offer that agent and non-interactive
contexts deliberately do not get. It scans enabled non-home projects, compares each
project's `plugins.required` list against installed distributions, and raises at most
one `PluginsRequired` gate per project per distinct missing or version-mismatched set.
**Install** performs one combined install for every missing requirement from the
answering surface. The combined planner shares a bounded public-index probe, resolves
each plugin from the index unless public PyPI returns a definitive 404, and uses git
only for those definitive misses; when planning or the `uv` mutation fails, including
when sase is not a `uv tool` install, the gate stays pending with the same actionable
message `sase plugin install` already prints where applicable. A successful install
restarts the scheduler service proc. **Dismiss** records the decision so the same
missing set is not re-offered until it changes. The job cancels the gate when the set
becomes satisfied. Lane state holds the pending request, a generation counter, and a
fingerprint over the missing set, so a re-run does not duplicate a notification. Run
`sase axe job run plugins_required` to raise or refresh those gates without waiting for
the next five-minute checks tick.

The `usage_refresh` job checks machine-local due and backoff state and submits coalesced
work to the same durable subscription-usage refresh service the CLI and sase's TUI use;
it does not poll per agent or per project. Collection stays gated by
`llm_provider.usage_metrics.enabled`; see
[Subscription usage extension](llms.md#subscription-usage-extension).

### external_mirror (15-minute interval)

Isolated remote-tracker polling:

| Job                     | Description                                    |
| ----------------------- | ---------------------------------------------- |
| `external_issue_mirror` | Mirror external tracker issues into task beads |
| `external_pr_mirror`    | Adopt remote pull requests as local Patches    |

Both jobs are the same class of work — one bounded remote poll per project — so they
share a single generously paced lane instead of two. A healthy full pass is 1–3.5
seconds, so the 900-second interval leaves wide headroom, and a 5-minute per-job timeout
means the worst-case cycle (`interval + job_timeout`) stays a bounded 20 minutes without
ever delaying the faster `checks` lane's PR-submission and workspace-claim work.

`external_issue_mirror` expands to one instance per enabled project via
`for_each: {source: projects, vcs: [git, gh]}` (`external_issue_mirror[<project>]`), the
first production use of `for_each`. Each pass diffs that project's tracker against local
beads on `external_ref` and creates explicitly `small`, `open` (never `ready`) task
beads for uncovered issues, so no `TaskTriage` gate fires on a first-pass backlog. The
issue-listing seam has no page cursor or ordering guarantee, so every pass lists the
tracker's full inventory (`state="all"`, `limit=0`); the per-pass bound instead caps
local writes — at most 25 bead creations and 50 notes per pass, within a wall-clock work
budget derived from the lane's configured `job_timeout`. A pass that hits the creation
cap does not advance its watermark, so a large first backlog converges over several
15-minute passes; run `sase bead sync-external` to accelerate it manually. Persistent
exponential backoff (capped at one hour) keeps one unreachable tracker from stalling
every pass.

When an issue linked by `external_ref` closes or reopens upstream, the mirror closes or
reopens the mirrored bead and appends one attributed note. It leaves status unchanged
and appends the note only when the local bead merely references the issue with a `bug:`
ref, an agent is working or claiming the bead, the bead has unclosed descendants, or the
bead already matches the upstream state. Disappearances also remain note-only because
there is no safe status target. Once a transition is recorded in durable
`upstream_states`, the same transition is never re-noted. The Beads pane's drift badge
therefore narrows to unreconciled cases: guard-skipped mirrored links, referenced-only
links, and title drift.

The [`external_mirror.issues.filters`](configuration.md#external_mirror) surface (empty
by default) excludes tracker issues from mirroring by author, label, title, or state; a
non-empty filter means the bead list is no longer a strict superset of the issue list.
Filters gate creation only — clearing a filter re-examines the issues it previously
dropped, but a filter never deletes a bead that already exists. Records a filter drops
count toward `sase bead sync-external`'s `filtered=<n>` per-project summary.

Two machines reconciling stale copies of a hosted bead sidecar can independently import
the same issue before either has seen the other's copy. The local partial-unique index
on `external_ref` prevents a single store from ever holding two beads for one issue; the
canonical Rust bead event reducer additionally collapses a genuine cross-machine
duplicate deterministically at integration/read time (keeping the earliest-created bead,
by `created_at` then id) rather than making the merged store unreadable. Direct local
create/update/import conflicts still fail atomically — only the very rare cross-machine
race collapses.

Run `sase doctor -C axe.external_mirror` to check detached tracker auth: the AXE
daemon's environment is not the interactive TUI's, and a silent `gh` auth failure there
would look exactly like "no issues." The check reports the job's own persisted evidence
rather than attempting an interactive provider call.

See [Builtin `external_pr_mirror`](#builtin-external_pr_mirror) below for that job's own
behavior, including where its cursor and backoff state live.

### comments (1-minute interval)

Comment polling:

| Job              | Description                   |
| ---------------- | ----------------------------- |
| `comment_checks` | Start critique comment checks |

### housekeeping (1-hour interval)

Periodic maintenance:

| Job                          | Description                                                                     |
| ---------------------------- | ------------------------------------------------------------------------------- |
| `error_digest`               | Send error notification digests (creates `ViewErrorReport` notification action) |
| `notification_store_compact` | Archive old dismissed notifications out of the live JSONL store                 |
| `managed_tmp_reap`           | Prune stale scratch under the managed SASE temp root                            |
| `proc_runtime_sweep`         | Prune stale rowless proc runtime directories                                    |
| `disk_pressure`              | Notify on disk pressure and run owner-safe cleanup early                        |
| `bead_stale_cleanup`         | Sweep stale sub-threshold ready task beads into one `BeadStaleCleanup` gate     |
| `gate_shell_reclaim`         | Settle pending gate shells whose gates answered, canceled, expired, or vanished |
| `artifact_link_backfill`     | Derive and reconcile artifact links, drain reads, and repair renamed refs       |
| `artifact_run_prune`         | Preview old ace-run directories and empty shard cleanup                         |

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
by moving dismissed rows older than 14 days into `notifications-archive.jsonl`. Unread
and still-actionable rows stay in the live file. sase's TUI snapshot reads are memoized
against an mtime+size token, so this pass lives on `housekeeping` rather than the TUI
refresh cadence that previously re-parsed the whole store every tick.

The `managed_tmp_reap` job bounds the managed SASE temp root (`$SASE_TMPDIR`, else
`~/.sase/tmp`) that `get_sase_managed_tmpdir()` hands out. The actual age/pressure
decision runs in `sase_core_rs` (`sase-core`'s `managed_tmp` crate); this Python job
resolves the configured horizons and thresholds and calls that binding. Horizons are per
subdirectory: command scratch (`editors/`, `wrappers/`, `viewers/`, `commit-messages/`,
`agent-tmp/`, …) goes after 12 hours by default, handoff files (`handoff/`, `gh-diffs/`,
`muse-prompts/` — a provider re-reads the latter mid-run) after 3 days, build targets
(`cargo-targets/`) after 3 days, and artifacts sase's TUI and screenshot tooling reads
back (`launch-prompts/`, `screenshots/`, `workflow-artifacts/`) after 14 days. Launched
agents default `TMPDIR`/`TMP`/`TEMP`, `CARGO_TARGET_DIR`, and `CARGO_BUILD_BUILD_DIR` to
per-launch directories under those managed buckets, so shell scratch and Cargo targets
no longer fall back to host-global `/tmp`. Launched agents also get
`CARGO_INCREMENTAL=0` and line-tables-only debug info for the dev and test Cargo
profiles, which keeps per-launch targets small. A runner also removes its own
launch-assigned `agent-tmp/` and `cargo-targets/` children at exit when they still match
its exported `TMPDIR` and `CARGO_TARGET_DIR` and it can prove, through procfs, that no
live process still references either tree (by environment or working directory). That
removal goes through the same Rust reaper as the hourly pass. Monitor/gate handoffs and
hosts without readable procfs leave cleanup to the reaper.

Each run removes at most 2,000 entries by default so a long-neglected root converges
over several passes instead of stalling one. The reaper also runs a pressure pass when
the managed root grows beyond 16 GiB by default, or when the filesystem holding it falls
below SASE's shared disk-pressure warn threshold: the larger of 3 GiB and
[`disk.pressure.warn_free_percent`](configuration.md#disk) (5% by default) of that
filesystem. Under pressure, aged entries of at least 1 GiB in regenerable build-output
buckets (`cargo-targets/`, plus the legacy `build-targets/`), and cargo/core
target-shaped top-level residue, are removed largest-first until the root is estimated
below 8 GiB, available space is estimated back above that same warn threshold, or the
removal budget is reached. Pressure pruning normally waits 12 hours, but once the
free-space floor is breached it uses the lower configured low-space age, 1 hour by
default, without weakening the fresh-descendant check. The horizons, removal budget,
root-size limits, pressure ages, and minimum pressure entry size are configurable under
`managed_tmp` in `sase.yml`; see [Configuration](configuration.md#managed_tmp). The
housekeeping job, `disk_pressure`, and `sase disk reap` all derive the free-space floor
and recovery target from the `disk.pressure` policy rather than from
`managed_tmp.pressure.min_available_bytes` and `recovery_available_bytes`. Generic agent
scratch, handoff buckets, artifact buckets, unknown buckets, symlinks, and build trees
with fresh descendants are not early pressure candidates. The job summary reports
`scanned`, `selected`, and `removed` counts with their byte totals, the same counts
split into `ordinary_*`, `launch_*`, and `pressure_*` passes, `pressure_trigger`,
`pressure_available_bytes`, `pressure_recovery_available_bytes`,
`pressure_min_age_seconds`, `deindexed`, `skipped`, `failed`, `incomplete_observations`,
and `capped=1` when it hit that budget. Reaped directories are dropped from the agent
artifact index too, since a workflow launched without an explicit `artifacts_dir` gets
one under `workflow-artifacts/`. It lives on `housekeeping` rather than an interactive
path because the first pass over a neglected root walks tens of thousands of entries.

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
larger of 3 GiB and [`disk.pressure.warn_free_percent`](configuration.md#disk) of its
size. With no pressure, the job exits with reason `space_ok` without scanning the disk
footprint. Under pressure, it logs the largest owners from `sase disk list` and, when
any qualify, sends a notification naming them; it then runs unattended owner-safe
cleanup early: the managed-temp reaper, using the measured free space and warn threshold
as its pressure floor and recovery target, and the proc cleanup owner (proc-row and log
retention plus the rowless runtime sweep). Those owners encode their own deletion
policy, and one owner's failure is reported without skipping the next. Workspace
Git-object compaction is left to an explicit `sase disk reap --apply`, and artifact run
directories, backups, and unowned Cargo-shaped strays are reported for human action;
this job never touches them. The summary reports the free percentage, effective warn
threshold, owner and step counts, and how many steps changed or failed.

The `bead_stale_cleanup` job is the other half of the task-bead `+1` bar. Ready task
beads that never clear their [effective `+1` bar](beads.md#per-type-triage-bar) stay
`ready` (the five-minute `bead_task_triage` job withholds their `TaskTriage` gate) and
would otherwise accumulate forever. Once at least
[`bead.task_triage.stale_cleanup_min_beads`](configuration.md#bead) of them have sat
below that bar for [`bead.task_triage.stale_after_days`](configuration.md#bead) days,
this hourly pass raises one human-only `BeadStaleCleanup` gate for the whole backlog —
one gate across every enabled project, not one per project. The offered roster is capped
at 50 beads, oldest first, with a `(project, bead_id)` tie-break; any remainder is named
in the preview as `omitted_count` and is offered on a later tick. Lane state holds the
pending request, a generation counter, and a fingerprint over the offered roster plus
the three thresholds (not the pinned `stale_as_of` date), so an unchanged roster leaves
the pending gate alone and a changed roster replaces it. When the backlog drops below
the bar the pending gate is canceled. A project whose store cannot be read is skipped
and cannot cancel a healthy pending gate, because the true roster is then unknown. Run
`sase axe job run bead_stale_cleanup` to raise or refresh that gate without waiting for
the hour.

The `gate_shell_reclaim` job is the backstop for
[gate shells](notifications.md#gate-shells-and-continuation). It scans gate-shell family
members across projects, settles shells whose gate bundle is already terminal, cancels
gates that reached their own deadline, and force-settles a shell as `lost` once
`gate.shell.reclaim_grace_seconds` (one hour by default) has passed after that deadline.
It then diagnoses settled gates whose requested successor never recorded, reading the
agent artifact index once per pass and resuming from a per-project cursor. Work left
when the pass-wide time budget runs out is deferred to the next tick.

The `artifact_link_backfill` job runs four bounded jobs per enabled project. It sweeps
older documents for deterministic derived links, resuming from a per-project checkpoint
when one tick's budget is exhausted; drains audited-read outbox rows whose agents have
since published; reconciles cross-workspace local aggregates; and repairs dangling refs
from Git rename history. A large derivation backlog converges over several hourly ticks
instead of rescanning the full corpus each time. Run
`sase axe job run artifact_link_backfill` for an immediate pass. The link model and
doctor counters are documented in [Artifact Links](artifact_links.md).

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

## Configuration

Axe is configured in `sase.yml` under the `axe:` section. See
[`docs/configuration.md`](configuration.md) for the full configuration reference.

### Global Settings

| Setting                               | Default  | Description                                               |
| ------------------------------------- | -------- | --------------------------------------------------------- |
| `max_hook_runners`                    | 3        | Concurrent hook runners allowed globally                  |
| `max_agent_runners`                   | 3        | Concurrent agent runners allowed globally                 |
| `zombie_timeout_seconds`              | 7200     | Timeout for marking jobs as zombie                        |
| `query`                               | `""`     | Optional query filter for all Patches                     |
| `job_script_dirs`                     | `[]`     | Directories to search for job scripts                     |
| `routine_log_max_bytes`               | 52428800 | Maximum bytes retained for each bounded routine log       |
| `routine_log_temp_max_age_seconds`    | 300      | Age before orphaned log-rotation temp files may be reaped |
| `routine_restart_backoff_max_seconds` | 60       | Maximum delay between retries for a crashing routine      |
| `verbose_routine_diagnostics`         | false    | Include verbose diagnostics in job script context JSON    |

The `query` setting uses the same Patch query language as sase's TUI. CLI flags on
`sase scheduler run` and `sase axe routine run` override the configured query, runner
limits, and zombie timeout for that process.

### Routine Configuration

```yaml
axe:
  routines:
    my_routine:
      description: |-
        Run project-scoped custom checks once a minute

        Use this lane for inexpensive checks that should react within a minute. Individual jobs may use run_every to
        reduce their own cadence; long-running maintenance and high-frequency lifecycle checks belong in separate
        routines.
      interval: 60 # Seconds between cycles
      job_timeout: "60s" # Default timeout for all jobs in this routine
      wait_runners: 1 # Emitted as %queue(capacity=1): lane agents run alone
      env: # Inherited by every job; individual job env wins
        API_TOKEN: { env: MY_API_TOKEN }
      jobs:
        my_job:
          script: my_job_executable # Optional; defaults to name
          description: |-
            Run a custom validation after meaningful repository changes

            Creates one instance per enabled Git or GitHub project and runs at most once every 1h30m after ten new
            commits. A successful action advances the trigger checkpoint; an active toobig agent clan inhibits the
            check, and the per-job timeout limits each run to 30 seconds.
          run_every: "1h30m" # Run at most once per compound duration
          timeout: "30s" # Per-job timeout (overrides job_timeout)
          env:
            MY_VAR: "value" # Custom environment variables
          inhibit_if:
            agent_clan: { name_prefix: toobig- }
          trigger:
            git.commits_since:
              project: "{target.name}"
              threshold: 10
              checkpoint: on_action_success
          once_per: "{target.name}:{proposal.id}"
          for_each:
            source: projects # One stable my_job[project] instance per enabled project
            vcs: [git, gh]
```

Every routine requires a `description` explaining the lane's cadence and the class of
work it owns, and every job requires one explaining what that job does. Both follow the
summary/body grammar in [Description Grammar](#description-grammar).

#### Routine Fields

| Field          | Type                   | Required | Description                                                                                                                   |
| -------------- | ---------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `description`  | `str`                  | yes      | Summary line, then a blank line, then an optional body (see [Description Grammar](#description-grammar))                      |
| `interval`     | `int`                  | no       | Seconds between job polling cycles; defaults to `1`                                                                           |
| `job_timeout`  | `str \| null`          | no       | Default positive compound duration for jobs in this routine                                                                   |
| `wait_runners` | `int \| null`          | no       | Per-launch capacity budget for lane agents, emitted as `%queue(capacity=N)`; omitting it uses only the global capacity budget |
| `env`          | `dict[str, env-value]` | no       | Values inherited by every job; individual job env wins                                                                        |
| `jobs`         | list or map            | no       | Composable job definitions                                                                                                    |

`wait_runners` applies only to agents emitted through a script job's
`proposed_launches`; it does not gate mentor, hook, or CRS workflow launchers. The
runner prepends it to each proposed prompt as `%queue(capacity=N)` unless the prompt
already authors its own `%queue` capacity, so it follows the
[per-launch capacity budget](xprompt.md#agent-names-waits-and-queue-admission) rules:
the agent starts when the occupied weighted load plus its own weight fits within `N`,
and `1` makes a default-weight lane agent run alone. While the default-on
`queue_capacity_budget` flag is enabled, `N` must be at least `1`; `wait_runners: 0`
produces a `%queue(capacity=0)` that is rejected at launch. When a job proposes a clan,
every member carries the budget and waits independently, so a low budget can serialize
the clan.

#### Job Fields

| Field         | Type                   | Required  | Description                                                                                                                |
| ------------- | ---------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------- |
| `name`        | `str`                  | list only | Job identity in object-list form; map form uses the mapping key                                                            |
| `description` | `str`                  | yes       | Summary line, then a blank line, then an optional body (see [Description Grammar](#description-grammar))                   |
| `script`      | `str \| null`          | no        | Exact executable name; defaults to the job identity                                                                        |
| `enabled`     | `bool`                 | no        | Soft-disable a keyed entry without deleting the packaged/base configuration                                                |
| `run_every`   | `str \| null`          | no        | Positive compound duration (e.g., `"5m"`, `"1h30m"`, `"1d"`)                                                               |
| `timeout`     | `str \| null`          | no        | Per-job timeout duration (overrides the routine's `job_timeout`)                                                           |
| `env`         | `dict[str, env-value]` | no        | Values merged over routine env; literals or `{env:}`, `{file:}`, `{pass:}` refs                                            |
| `inhibit_if`  | list or map            | no        | `patch` / `agent_hood` / `agent_clan` / `agent_runners` guards evaluated before the script; `changespec` is a legacy alias |
| `trigger`     | string or map          | no        | `always`, `git.commits_since`, or `fs`; scheduled runs fire only when it accepts                                           |
| `once_per`    | string or object       | no        | Bounded per-proposal dedupe-key template                                                                                   |
| `for_each`    | list or source         | no        | Literal target objects or `source: projects`, expanded to stable per-target instances                                      |
| `vars`        | `dict`                 | no        | Non-secret configuration copied into the script context                                                                    |

Map-form jobs compose by identity across config layers. A higher-priority layer can
patch a single field or set `enabled: false` while retaining the rest of a packaged
entry. Object-list form remains accepted, but bare-string list entries are invalid
because they cannot provide the required description. Target instances use names such as
`my_job[sase-core]`, with independent cadence, run history, checkpoints, and dedupe
state. Literal targets may include an `overrides:` object for per-target fields such as
`run_every`; the `projects` source accepts `name`/`names` and `vcs` filters.

Configuration is validated fail-closed. Unknown fields, duplicate job identities, and
invalid or non-positive durations produce actionable errors with their config paths.
Secret references resolve at dispatch and fail closed with provider-specific
diagnostics. Legacy `agent:` and `xprompt:` job fields are rejected: scheduled agent
work must originate from a script's structured launch proposals.

### Description Grammar

Both `axe.routines.<name>.description` and every job `description` use one grammar,
borrowed from the shape of a Git commit message:

```
<summary>
<blank line>
<body…>
```

- Line 1 is the **summary**: non-blank, at most 100 characters, no leading or trailing
  whitespace.
- If anything follows the summary, line 2 **must be blank**. That single rule makes the
  split unambiguous.
- Everything from line 3 on is the **body**: free-form prose. Blank lines separate
  blocks, and a block whose first line starts with `-`, `*`, or `•` is rendered as a
  bullet list.
- The whole description is at most 2000 characters.
- A single-line description is still completely valid and simply has an empty body.

The split is owned by the shared Rust config authority (`split_axe_description`), so the
sase's TUI Services tab, both CLI listings, and the entry editor always agree on where
the summary ends. It is computed once per entity when the config is parsed, never on a
render or keystroke path.

Author multi-line descriptions as YAML literal block scalars (`|-`), hand-wrapping
source lines to keep the file inside the configured Markdown prose width
(`markdown.print_width`, `88` by default):

```yaml
description: |-
  Complete finished hooks and start stale ones, with zombie detection

  Scans every Patch matching the axe query, completes hooks whose runner exited, and starts the next
  stale hook when a runner slot is free.

  - Honors max_hook_runners; a full slot table defers work to the next tick rather than queueing.
  - Hooks still running past zombie_timeout_seconds are marked ZOMBIE and stop holding a slot.
```

Hard wraps in the source are stored verbatim, and the renderer reflows: consecutive
non-blank, non-bullet lines in a block are joined with single spaces and re-wrapped to
the available width. A description authored at 110 columns therefore still fills a
200-column pane and still reads correctly at 60.

#### Diagnostics

Shape violations are reported by the config authority with `severity: "error"` at the
offending field's config path. At most one code is emitted per description, checked in
this order:

| Code                                  | Condition                               | Message                                                                     |
| ------------------------------------- | --------------------------------------- | --------------------------------------------------------------------------- |
| `description_summary_blank`           | line 1 is empty or whitespace-only      | `description must start with a non-blank summary line`                      |
| `description_summary_too_long`        | the summary exceeds 100 characters      | `description summary line must be at most 100 characters (found <n>)`       |
| `description_body_separator_required` | a line 2 exists and is not blank        | `description must leave line 2 blank to separate the summary from the body` |
| `description_too_long`                | the description exceeds 2000 characters | `description must be at most 2000 characters (found <n>)`                   |

A blank description is still reported as `blank_value`, and a missing one as
`required_missing`, exactly as before. The four shape checks are gated behind a
`require_description_shape` request flag that defaults to off on the wire; SASE turns it
on for both config composition and AXE entry edits, so they always apply to configs SASE
loads.

#### Authoring Style Guide

**Summary (line 1)**

- One line, at most 100 characters, target 80. Sentence case, no trailing period.
- Present tense, active voice, describing what the entity _does_, not what it is.
- Must stand alone: the collapsed Services-tab panel, both CLI listings, and the entry
  editor's preview show only this line.

**Body**

- One to three short paragraphs and/or one bullet list. Aim for six to ten rendered
  lines.
- Answer, in this order, only what is true and non-obvious: what it actually does, when
  it fires, what state it reads or mutates, and the one thing an operator most needs to
  know (a failure mode, a safety property, a cost, a limit).
- Name the config knobs that matter when they are set (`interval`, `job_timeout`,
  `run_every`, `trigger`, `inhibit_if`, `for_each`, `env`).
- Do not restate the summary, do not narrate the implementation line by line, and do not
  document SASE concepts that belong elsewhere in `docs/`.

**Routine bodies additionally** state the cadence in words and why that cadence is right
for the lane, and say what belongs in the lane and what deliberately does not, so a
reader knows where to add a new job.

**Mechanics**: bullets start with `- ` at the block's base indentation and continuation
lines indent two further spaces; no trailing whitespace, no tabs, and no blank line at
the end of the block.

### Script Jobs

Every job is an external executable. Axe resolves the exact configured `script` value
(or `name` when `script` is omitted) in this order:

1. An exact-name executable in one of `axe.job_script_dirs`.
2. An exact-name executable beside the running Python interpreter.
3. An exact-name executable on `$PATH`.

No prefix is added automatically. Builtin jobs therefore declare names such as
`script: sase_job_hook_checks` explicitly. As a discovery convenience, the
available-script inventory (`sase axe job list -a`) lists every executable in
`axe.job_script_dirs` plus `sase_job_*` executables beside the interpreter and on
`$PATH`. Legacy `sase_chop_*` executables are still installed and discovered, but when
both spellings resolve to the same file or console-script entry point the inventory
shows only the `sase_job_*` name. Resolution always uses the configured full name.

Axe runs script jobs as:

```bash
<script> --context <context.json>
```

The context file contains the effective runner limits, zombie timeout, query, routine
name, routine state directory, paths to legacy-named serialized `all_changespecs.json`
and `filtered_changespecs.json` files, the current `target`, configured `vars`, the run
source (`scheduled`, `manual`, or `oneshot`), the `dry_run` flag, and the run-local
result path. The result path is also exported as `SASE_JOB_RESULT_FILE`; the source and
dry-run flag are mirrored as `SASE_JOB_SOURCE` and `SASE_JOB_DRY_RUN` (`1` for true, `0`
for false). `SASE_JOB_VERBOSE` enables opt-in debug output. Target fields are exported
as `SASE_JOB_TARGET_<FIELD>` along with `SASE_JOB_TARGET_KEY`. Each of these variables
is also mirrored under its legacy `SASE_CHOP_*` spelling for older scripts; configuring
both spellings with different values is rejected. Scripts with direct side effects must
honor `dry_run` before mutating external state; runner-level dry-run only previews
launch proposals. Scheduled script jobs within one routine tick run concurrently; use
`timeout` or `job_timeout` to keep a slow script from blocking later ticks indefinitely.

Script job stdout and stderr are streamed to the job's per-run log file while the
subprocess is still alive (see [Job Run History](#job-run-history) below). The
Services-tab dashboard tails that file so a long-running job's output becomes visible
immediately rather than only after process exit.

Job output is part of the operator contract. Every actual job run should write a
compact, human-readable summary for both no-op and action paths. At minimum, include the
job identity or run scope, counts of inspected/skipped/updated or launched items, an
explicit no-op reason, and bounded identifiers for any affected items. Avoid tokens,
full notification bodies, full prompts, and unbounded command output in ordinary AXE
logs. A job with a meaningful structured story should also publish a report while
keeping this compact stdout summary unchanged; logs and notifications continue to use
the summary line.

#### Structured Results and Launch Proposals

Exit-code-only scripts remain supported: exit zero means `success`, a non-zero exit
means `failure`, and no result file is required. A proposal-emitting script atomically
writes a schema-versioned JSON document to `SASE_JOB_RESULT_FILE`:

```json
{
  "schema_version": 1,
  "status": "ok",
  "summary": "refresh_docs: targets=1 proposals=2",
  "counters": { "targets": 1, "proposals": 2 },
  "proposed_launches": [
    {
      "id": "update",
      "prompt": "Refresh the user documentation.",
      "workspace": "gh:sase-org/sase"
    },
    {
      "id": "polish",
      "prompt": "Fact-check and polish the documentation update.",
      "workspace": "gh:sase-org/sase",
      "wait_on": "update"
    }
  ]
}
```

Result `status` is `ok`, `no_op`, or `check_error`. Results can also carry a `reason`,
integer `counters`, and relative `evidence` file paths. Each proposal requires `prompt`
and `workspace`; optional fields are `id`, `agent_name`, `clan`, `clan_summary`,
`tribe`, `model`, `effort`, `env`, `dedupe_key`, and `wait_on` (an earlier proposal
index or ID). With `clan`, `agent_name` is the member ID and the runner owns concrete
clan allocation plus the full `<clan>.<member>` identity. Clan proposals cannot also set
`tribe`; the first accepted member declares the clan with the default job tribe.

The built-in job tribe is stored under its historical `chop` identity and displayed as
`job` on public surfaces. A proposal that sets `tribe: job` (or omits `tribe`) resolves
to that stored identity before anything is written, so scaffolded directives read
`tribe=chop`. Tribe resolution is provenance-aware: agents whose stored tribe is already
a literal `job` keep it, and configuring display entries for both `ace.tribes.job` and
`ace.tribes.chop` is reported as an alias-collision diagnostic.

`clan` and `agent_name` may each carry at most one `@` auto-name template marker, so a
composed clan-member identity holds up to two. The runner resolves them in two stages:
it picks one clan token for the whole group first, then allocates each templated member
name inside that concrete clan, so `clan="toobig-@"` with
`agent_name="split_file.src.pkg.large.@"` plans to
`toobig-0.split_file.src.pkg.large.0`. Two members sharing one template therefore land
on `.0` and `.1` instead of colliding. A clan token is taken only when the clan name and
every member identity in the group are free together; otherwise the whole group moves to
the next clan token and the member tokens tried under the rejected one are discarded.

`clan_summary` is an optional literal Rich-markup summary and is valid only with `clan`.
Every non-null summary attached to the same raw clan template must be identical; members
that omit it inherit that agreed value before once-per filtering. The first accepted
member therefore retains and declares the summary even when an earlier member is
deduplicated. Different raw clan templates may have different summaries. A summary must
be nonblank, contain no NUL byte, fit within 32 KiB of UTF-8, and avoid both the `]]`
text-block terminator and `+` (which xprompt argument decoding would turn into a space).

A proposal that also carries an active `%if` predicate is admitted through the typed
launch path (see [Agent Launch Flow](architecture.md#agent-launch-flow)), so a member
statically planned to declare the clan can still be skipped at admission time. That
promotion works the same way once-per filtering already promotes the first accepted
member: admission-time filtering promotes the first surviving (eligible, dispatched)
member of an undeclared clan to declarer regardless of which member was planned to
declare it, carrying the group's agreed `tribe` and `clan_summary` with it. A skipped or
condition-errored member never claims the role, and an all-skipped batch declares no
clan. The declarer claim is recorded durably before that member's launch attempt runs,
so a launch failure cannot let a later member declare the same clan a second time, and a
detached coordinator resuming in a fresh process still honors an earlier claim.

`report` is an optional structured document rendered with the result on sase's TUI
Services tab. Job authors supply semantic tones rather than colors, and the frontend
owns the palette and width-responsive layout. The public SDK keeps report construction
typed and validates the finished result through the Rust contract:

```python
from sase.jobs import JobReport, JobResultBuilder

report = JobReport(title="CI WATCH")
report.headline("4 green · 1 red · 1 fix proposed", tone="warn")
report.heading("REPOSITORIES")
rows = report.rows(columns=("REPOSITORY", "STATE", "EVIDENCE"))
rows.row(("sase-org/sase", "red", "ci / test · streak 2/2"), tone="error")
rows.row(("sase-org/sase-core", "green", "a1b2c3d"), tone="ok")
report.divider().kv({"mode": "dry run"}, tone="muted")

JobResultBuilder(
    status="ok",
    summary="ci_watch: repos=5 green=4 red=1",
    report=report,
).write(context=invocation.context)
```

A report has an optional `title` and a non-empty `blocks` list. The closed block
vocabulary is:

- `headline`: `text` and optional `tone`.
- `heading`: `text`.
- `text`: literal `text` and optional `tone`.
- `kv`: non-empty `items` of `key`, `value`, and optional `tone`.
- `rows`: optional `columns` plus non-empty `rows`; each row has `cells`, optional
  `tone`, and optional `glyph`.
- `bullets`: non-empty `items` of `text`, optional `tone`, and optional `glyph`.
- `gauge`: `label`, non-negative `value`, positive `max`, and optional `tone`. Values
  may exceed `max`.
- `divider`: no additional fields.

The tone vocabulary is `neutral` for ordinary content, `muted` for secondary context,
`info` for useful context, `ok` for healthy outcomes, `warn` for attention, `error` for
failures, and `accent` for report emphasis. A job cannot supply a color. Optional row
and bullet glyphs are restricted to `▲ ◆ • · ● ○ ✓ ✗ ↗ ↷ ⏱ ! ▸ ─`; omitting a glyph lets
the renderer choose one from the tone.

The validated report must fit within 32 KiB of UTF-8 and contain 1–48 blocks. A `kv`,
`rows`, or `bullets` block holds 1–64 entries. Rows contain 1–6 cells; when column names
are present there must be 1–6 of them and every row must have the same number of cells.
Titles are limited to 64 characters, and every other string field to 512 characters.
Required strings must be nonblank single-line text with no control characters.
`JobReport` collapses whitespace, removes controls, truncates bounded strings with a
trailing ellipsis, drops empty blocks, and rejects invalid tones, glyphs, gauges, or row
shapes before writing. Unknown fields, block kinds, and tones are rejected fail-closed
by result validation.

The runner validates the full document before launching anything. It injects the
workspace reference, a deterministic agent name and the job tribe (`tribe=chop`) in one
`%id(...)` directive, model/effort directives, and a `%wait` dependency for `wait_on`,
then launches proposals in document order. Clan-scoped proposals are preplanned as one
multi-prompt batch: the first surviving member declares one concrete clan generation and
later members join it, while waits use their full resolved names. The declarer receives
`%id:<full name>` plus `%clan(<name>, tribe=chop)`, or
`%clan(<name>, tribe=chop, summary=[[<literal Rich markup>]])` when it carries a
summary; joiners receive only `%id(<member>, clan=<name>)`. Axe neither executes the
summary as a script nor inserts it into any proposal's work prompt. Standalone
`#!workflow` references are forbidden in proposal prompts; reusable inline `#xprompt`
references remain valid. The runner records every launched agent in `agent_chops.json`
and finalizes the job only when the linked agents reach terminal state.

A launcher can still fail partway through an otherwise valid batch. The caller receives
`action_failed` immediately. When at least one proposal already started, however, the
persisted job run remains active as `launched` until every started agent finishes; it
then finalizes as `action_failed` with both the original launch error and any agent
failures. Once-per keys for accepted proposals that never started are released
immediately. A started proposal keeps its key while it runs, then releases it only if
that agent fails, so successful work remains de-duplicated. A key-release error is
appended to the job output and does not replace the original launch or agent outcome.

A proposal's `prompt` may contain typed directives such as `%if::` (a Bash or Python
condition fence) or `%proc`. When the `typed_launch_units` beta flag is enabled, a batch
containing an active directive routes through the same durable typed admission
coordinator used by sase's TUI, `sase run`, and LaunchApproval, joining AXE as a fourth
typed-admission source; see [Agent Launch Flow](architecture.md#agent-launch-flow). A
`%if` predicate evaluates after its unit's `%wait` dependency settles and before any
runner, agent identity, proc identity, or model request is allocated. For a selected
managed project, the predicate itself briefly uses a claimed, prepared operational
workspace so stale job checkouts can observe newer pushed work before admission decides.
Exit `0` admits the unit normally; exit `1` records a skip with no runner, identity,
proc, or model allocation. AXE owns the admission bundle across the run, keeping the job
in active `launched` state until every admitted unit reaches its own terminal state, and
treats predicate skips as successful no-op outcomes rather than once-per duplicates or
launcher errors. A structured proposal `wait_on` becomes both a typed admission-order
edge and, for an admitted Agent unit, a restored named-agent `%wait` in the prompt AXE
dispatches to the runner. If admission skips or condition-errors an intermediate
proposal, AXE relinks that runner wait to the nearest earlier proposal that actually
launched; if no ancestor launched, it dispatches without a named wait. A batch with no
active `%if`/`%proc` directive, or any batch while the flag is disabled, keeps using the
legacy launch path unchanged; an explicit typed directive while the flag is disabled
fails before any agent or model is dispatched.

Python job packages should use the public `sase.jobs` SDK (`load_job_invocation`,
`JobLogger`, `JobReport`, `JobResultBuilder`, and `launch_proposal`) for argument
parsing, summaries, reports, validation, and atomic result writes.

#### Publishing a Report a Notification Can Open

Per-job run history is capped, so a report that only rides along with a job result
answers "what did this tick do", not "where do things stand". A job that wants the
second answer should **publish** a standalone report document into its own state
directory (`invocation.context.state_dir`) and point a notification at it:

```python
from sase.jobs import JobReport, validate_job_report

report = JobReport(title="RELEASES")
report.headline("2 merged today · 3 pending", tone="warn")
document = validate_job_report(report.to_dict())
# atomically write `document` to <state_dir>/<name>.report.json on every tick
```

`validate_job_report` runs the same Rust job-result contract used for an embedded
`report`, so an invalid document is caught before it is written; log and skip that tick
rather than raising, leaving the previous good file in place. Rewriting the file on
every tick — including no-op ticks — is what keeps the published picture fresh without
any network call or latency inside the TUI.

The notification then carries `action: "ViewReport"` with
`action_data: {"report_path": "<state_dir>/<name>.report.json", "report_title": "..."}`.
Selecting it in sase's TUI renders the document in the notification modal's right pane
and Enter opens it full-screen; see `docs/notifications.md` for the contract, the
inline-snapshot alternative, and the fail-closed loader limits. Prefer the published
path over inlining a snapshot into `action_data` whenever the job has a durable state
directory. Timestamps inside a published document should be absolute, because the file
may be read long after it was written; relative freshness belongs to the single
provenance line the reader sees.

#### Triggers, Guards, Dedupe, and Targets

Policy is runner-owned and evaluated before the script:

- `run_every` limits cadence for each expanded job instance. A guard skip does not
  consume this cadence, so a guarded job re-evaluates its guard on the next tick rather
  than waiting out the full interval; a trigger skip (the condition was evaluated and
  not met) still advances the clock as before. Guard evaluation is not free — put a
  guard on a lane whose tick interval matches the cost of re-checking it.
- `inhibit_if` supports `patch`, `agent_hood`, `agent_clan`, and `agent_runners` guards.
  The legacy `changespec` guard key remains accepted as an alias.
  `agent_clan.name_prefix` matches canonical clan metadata on active agents only; dotted
  agent names are not treated as clans. `agent_runners.max` defaults to `0` and inhibits
  while more than that many participating lanes are occupied, a participating-lane count
  distinct from the weighted `%queue(capacity=N)` threshold. Weighted runner capacity is
  tracked separately by the host-wide capacity budget. A `STARTING` agent has not yet
  been admitted and does not count; an agent parked on a question has yielded capacity
  and does not count. A match records a visible `skipped` run naming the guard and
  matching agent.
- `trigger` defaults to `always`. `git.commits_since` observes a project repository,
  fires when its threshold is met, and owns its checkpoint under the job's state
  directory. A missing checkpoint fires once so a new job is not silently inert.
- `fs` fires when a cheap state token computed from `paths` differs from the token at
  its last fire. Each entry in `paths` is a bare path string or a `{path, glob}` object;
  a bare path is stat'd directly (existence, mtime, size, plus a non-recursive child
  count for directories), and `glob` shallow-matches entries inside a directory path
  (name, mtime, size per match — no recursion, no content reads). Relative paths resolve
  against the SASE state root (`~/.sase`, or `$SASE_HOME`); absolute paths and `~` pass
  through unchanged. `max_quiet` is a required positive compound duration: the trigger
  fires unconditionally once that long has passed since its last fire, even with no
  watched-path change, so a missed observation only delays work. Any watch path that
  cannot be read (as opposed to one that does not exist, which is itself a valid token
  state) fails open and fires without advancing the checkpoint. `fs` always uses
  `on_observation` checkpoint semantics; it has no `checkpoint_policy` setting.
- Checkpoint policy can be `on_observation`, `on_action_accepted`, or
  `on_action_success`. The last option advances only after every linked proposal agent
  succeeds.
- `once_per` renders a bounded per-proposal key; a proposal's own `dedupe_key` takes
  precedence. Duplicate proposals are skipped without relaunching work. Accepted keys
  remain reserved for successful launches, but are released when their proposal never
  starts or its launched agent reaches terminal failure, allowing a later run to retry
  that work. `dedupe_key` is durable work identity, not a retry clock: a key means "this
  is the same unit of work," and a successful no-op launch reserves it permanently. Jobs
  whose work can go stale between scans should recheck eligibility with `%if` (below)
  instead of folding a repository revision into the key.
- `for_each` accepts literal target rows or `source: projects`. Expansion creates stable
  instances such as `refresh_docs[sase-core]`, each with independent cadence, history,
  checkpoints, and dedupe state. Target overrides can patch per-instance fields such as
  `run_every` and trigger thresholds.

Manual CLI/TUI runs bypass configured triggers because the operator explicitly requested
a run, but still honor guards. With `agent_runners`, a manual run while participating
lanes are occupied skips unless `-f/--force` is passed to bypass both for that run.

Once-per filtering keeps proposal chains connected. If a surviving proposal's `wait_on`
points to a duplicate, AXE follows the skipped proposal's own dependency until it
reaches the nearest earlier proposal that also survived the filter. If no such proposal
exists, AXE removes the wait. Dry-run and recorded proposal previews put the resulting
dependency in `wait_on` and explain the change in `dedupe_reason`, so removing duplicate
work does not also discard a new downstream proposal. For a clan, the first surviving
member becomes the declarer; dry runs show the same concrete clan, declaration/join
roles, declarer-only `clan_summary`, full member names, exact scaffolded prompts, and
effective waits without reserving names or spawning agents.

A proposal that supplies an explicit `agent_name` treats a name collision at launch as
idempotency, not failure: the sequential launch path records that proposal as skipped
with a name-collision reason, releases its once-per key, and relinks dependent waits the
same way once-per dedupe does. If every proposal is skipped the run finishes `skipped`;
otherwise launched proposals proceed normally. Collisions on runner-derived names (which
embed a per-run token) and in clan batch launches remain hard failures.

#### Builtin `external_pr_mirror`

`sase_job_external_pr_mirror` fans out across enabled `git` and `gh` projects with
`for_each: {source: projects, vcs: [git, gh]}`. Each instance uses the target's
ProjectSpec directory key for local Patch files and the target workspace directory for
provider calls. A structural capability probe skips providers that cannot list PRs.

Incremental runs fetch a bounded PR inventory because the provider seam exposes a record
limit, not pagination. The job records `seen`, `fetched`, `unmirrored`, `created`,
`repaired`, `refreshed`, `skipped`, `conflicts`, `errors`, `budget_exhausted`, and
`checkpoint_advanced` in its summary. Cursor and backoff state live at a stable path
under `~/.sase/external_mirror/`, independent of whichever routine the job is configured
in, so `sase patch sync-external` reads and writes the same files. A ten-minute overlap
window covers incremental passes; the cursor advances only after a clean pass, and a
daily full scan ignores it so missed repairs are eventually found.

`unmirrored` counts fetched PRs dropped by
[`external_mirror.pull_requests.filters`](configuration.md#external_mirror), which ships
with head-ref exclusions for release-please and release-plz PRs so those never become
Patches; every other criterion is empty by default, adopting every other PR SASE did not
create. Dropped records never reach the checkpoint, so a filter change (clearing,
narrowing, or widening one) forces the next pass to go full and re-examine them. Filters
gate creation only — a PR a filter now excludes keeps whatever Patch it already has. The
last pass's `unmirrored` count per project is also written to a lane-independent
document that feeds the CLI's `Filtered` column and the Patches pane's `· M remote-only`
banner chip.

Open draft PRs become `Draft` Patches, open non-draft PRs become `Mailed`, and merged or
closed PRs are appended directly to the archive ProjectSpec as `Submitted` or
`Archived`. The `SASE_PATCH` marker identifies PRs created by SASE's tracked PR
workflow, not PRs created by any SASE agent. An agent that bypasses the tracked workflow
and calls `gh pr create` directly is indistinguishable from a human and is adopted as
`external`.

Adoption is not one-shot: a Patch that already owns a PR is refreshed whenever its
recorded `STATUS` no longer matches the state that PR now maps to, so a PR adopted while
open follows its own merge or close instead of freezing at its adoption-time status. A
refresh rewrites the status in place and, when the PR reaches a terminal state, moves
the Patch out of the active ProjectSpec into the archive. `refreshed` counts these
updates separately from `repaired`, which stays specific to a corrected `PR_ORIGIN`
marker.

Refreshes are guarded to `pr_origin: external` Patches only: a Patch SASE's own tracked
workflow created has a lifecycle AXE owns, and the mirror never writes its status.
Ownership is re-checked under the ProjectSpec lock, so a Patch that changed hands since
the pass planned its work is skipped rather than overwritten. Each refresh is a mutation
charged against the same per-pass budget and deadline as an adoption, which makes the
daily full scan load-bearing rather than merely defensive: a PR that merges long after
adoption can fall outside the ten-minute incremental overlap window.

#### Builtin `refresh_docs`

`sase_job_refresh_docs` replaces the former scheduled xprompt workflow. It expects an
expanded target with a `workspace`, then emits an `update` proposal and a `polish`
proposal whose `wait_on` points to `update`. Commit counting and checkpoints belong to
`git.commits_since`; project fan-out belongs to `for_each`:

```yaml
axe:
  routines:
    docs:
      description:
        Refresh project documentation when repositories accumulate meaningful changes
      interval: 300
      jobs:
        refresh_docs:
          script: sase_job_refresh_docs
          description: Refresh documentation after meaningful repository drift
          run_every: "30m"
          trigger:
            git.commits_since:
              project: "{target.name}"
              threshold: 25
              checkpoint: on_action_success
          for_each:
            source: projects
            vcs: [git, gh]
```

The builtin supplies plain-language update and polish prompts that are strictly scoped
to documentation files. They direct agents to document the current behavior and report
suspected code bugs instead of changing source code, tests, build configuration, or
other non-documentation files. Override the defaults with non-blank `vars.prompt` and
`vars.polish_prompt` strings; operators are responsible for including appropriate scope
restrictions in replacement prompts. The script only proposes work; it never calls
`sase run` or updates marker files.

### Manual Job Runs

Scheduled routine ticks are not the only way a job runs. Operators can launch any
configured job on demand from both the CLI and sase's TUI; manual runs share the same
execution path, run history, and live-output streaming as scheduled runs.

**From the CLI:**

```bash
sase axe job run <job>                    # name must be unique across routines
sase axe job run <job> --routine <routine> # explicit routine (short form: -L <routine>)
sase axe job run <job> --dry-run          # -n: validate and preview; launch nothing
sase axe job run <job> --job-verbose      # -V: script diagnostics + full result
sase axe job run <job> --force            # -f: bypass guards (triggers already bypassed)
```

When the same job name appears under multiple routines, `sase axe job run <job>` fails
with an unambiguous error listing the candidate routines (exit code 2). Pass
`-L/--routine` to pick one. A name that is not configured anywhere but matches a
discoverable executable still runs, attributed to the synthetic `_oneshot` routine. The
CLI run is recorded under the legacy-named
`~/.sase/axe/lumberjacks/<routine>/chops/<job>/` path exactly like a scheduled run,
except its metadata is tagged with `source = "oneshot"` (vs `"scheduled"`). The command
exits 0 for `success`, `skipped`, `no_op`, `launched`, and `action_succeeded` outcomes,
and non-zero otherwise, including when the same job already has a live run.

**From sase's TUI:**

On the Services tab, press `r` while a job row is selected to launch that exact
`(routine, job)` manually. The run uses the job's configured script, environment, and
timeout, but bypasses any `run_every` cadence because the user explicitly asked for it.
The TUI does not block while the script runs; once the subprocess starts, the new run
becomes the newest entry in the job's run history and the detail panel switches to it.

If the selected job already has a live script run in flight for the same
`(routine, job)`, `r` notifies and skips the launch rather than starting an overlapping
duplicate. On non-job rows — routine rows and running bgcmd rows — `r` is a no-op; on a
completed bgcmd row, `r` continues to re-run the bgcmd.

Manual runs participate in `Ctrl+N` / `Ctrl+P` history navigation just like scheduled
runs. TUI runs are tagged `source = "manual"`, and the job-detail header marks any
non-scheduled run with a `Source:` chip (`manual` or `oneshot`) so it is easy to tell at
a glance why a run started.

### Job Run History

Every job execution — whether kicked off by a scheduled routine tick or by
`sase axe job run …` — is recorded as a separate run under the legacy-named
`~/.sase/axe/lumberjacks/<routine>/chops/<job>/` path. Each run is assigned a sortable,
microsecond- precision `run_id`. `index.json` (kept next to `runs/`) lists the job's run
IDs newest-first:

```
~/.sase/axe/lumberjacks/<routine>/chops/<job>/
├── index.json              # Ordered run IDs (newest first)
└── runs/
    ├── <run_id>.json         # Run metadata (see below)
    ├── <run_id>.log          # Streamed stdout+stderr from the job process
    ├── <run_id>.context.json # Private context passed to this invocation
    └── <run_id>.result.json  # Structured result, when the script writes one
```

Each `<run_id>.json` is a serialized `ChopRunEntry` (see `src/sase/axe/state.py`). The
most relevant fields are `status`, `started_at`, `finished_at`, `duration_ms`,
`exit_code`, `pid`, `source` (`scheduled`, `manual`, or `oneshot`), `started_by`,
`output_bytes`, `result`, proposal previews, launches, and the recorded skip/error
`reason`.

A run starts as `running`. Exit-code-only scripts end as `success`, `failure`,
`timeout`, or `missing_script`. Policy rejections are `skipped`; structured healthy
no-work and degraded probes are `no_op` and `check_error`. A result with accepted
proposals moves to `launched`, then the housekeeping pass finalizes it as
`action_succeeded` or `action_failed` from linked agent completion artifacts. `running`
and `launched` are active states, so `finished_at` is `null` for both.

If a linked agent's process has stopped and its live `done.json` is absent, finalization
looks for the top-level dismissed-agent archive entry with the same artifact timestamp.
Workflow-child archive rows do not stand in for that top-level run. Only a `DONE`
archive status counts as success; `FAILED`, `KILLED`, any other status, or a missing
entry fails the action.

History is pruned after every run write, retaining the newest `MAX_CHOP_RUN_HISTORY`
(10) terminal runs per job. Active `running` and `launched` entries are always kept
regardless of position, so slow scripts and pending actions are never deleted out from
under their lifecycle owners.

### Services Tab Views

The Services tab sidebar renders each routine as a top-level row with its configured
jobs as indented children, followed by any background commands (`!!`). Each job row
shows a status marker derived from its newest cached run: active `running` / `launched`,
successful `success` / `action_succeeded`, healthy `no_op`, policy `skipped`, degraded
`check_error`, failed `failure` / `timeout` / `action_failed`, or `missing_script`. Jobs
with no history remain marked as never run. Selection drives three distinct dashboard
views:

- **Routine overview** — selecting a routine row shows its status, interval, cycle
  count, error count, and a per-job table with each job's last-run status, relative
  timestamp, and duration. For a job whose newest run is still active, the duration
  column shows live elapsed runtime rather than the stale `0ms` you would otherwise see
  before the run finalizes.
- **Job detail** — selecting a job row renders one width-responsive document. A
  universal **RESULT** card summarizes status, counters, reason, dry-run/source markers,
  proposals, launches, evidence, and failures from the cached run entry. A job-authored
  structured report follows when the result document provides one, then **OUTPUT**
  preserves the run's ANSI-rendered `.log` tail. Until the log has accumulated any
  bytes, the output section shows a `Waiting for output…` placeholder; the exit code is
  suppressed until the run finalizes. Active `running` and `launched` runs continue
  following the output tail, while selecting a terminal run leaves the RESULT card at
  the top of the scroll region.
- **Background command output** — the live output stream of the focused `!!` oneshot row
  (its durable proc log), with the recorded exit code in the status line once it
  finishes.

A job whose run blocked its routine's tick for at least the routine's `interval` is
marked **overrun** — amber `⚠` with a `2.4×`-style ratio of blocking time to interval.
The newest sampled run being over is level `over` (bold); an older sampled run in the
cached history being over while the newest is not is level `intermittent` (dim), so a
job that alternates does not flap its mark on and off across refreshes. The sidebar job
chip and its parent routine's roll-up chip always show the **worst** ratio in the cached
window, so a collapsed-then-expanded tree tells the same story every time; the routine
overview's `PACE` column and the job detail header instead describe the **latest** run
specifically, matching the rest of those views. A job that launches agents is measured
on its script's own wall-clock time, not on how long the launched agents ran — the tick
never waited for them, so their lifetime is excluded from the measurement.

`Ctrl+N` / `Ctrl+P` on the Services tab page through the focused job's run history
(newer / older). The viewer pins to the run you selected so that a fresh tick prepending
a new run does not bump you forward; the pin is cleared automatically if the pinned run
is pruned or itself becomes the newest run.

The same structured report renderer is used by `sase axe job run` when that command
prints a structured result (dry run or job-verbose mode), so semantic tones, rows,
gauges, and literal-text safety do not drift between the CLI and sase's TUI Services
tab.

### Job-Agent Registry

The durable `agent_chops.json` linkage associates launched proposals with job lifecycle
state. Configuration is always script-based. Each launched agent receives
`SASE_JOB_ROUTINE`, `SASE_JOB_NAME`, `SASE_JOB_RUN_ID`, and a prompt hash; the
housekeeping pass uses the registry plus normal agent completion artifacts to finalize
`launched` runs. The same values are mirrored under the legacy `SASE_CHOP_*` names,
which are still accepted from installed callers but are not the documented authoring
surface.

Linkage is explicit: a registry record is created only for proposal launches the runner
itself performs and for continuation respawns (retry or model-fallback) of an
already-linked agent. Ambient `SASE_JOB_*` and `SASE_CHOP_*` context is scrubbed from
every other spawned child's environment, so nested launches by job agents and launches
performed by job scripts themselves neither register nor inherit job identity.

Housekeeping matches registry records to the run entry's own recorded launches by
artifacts timestamp, following retry successors through `retried_as_timestamp` chains.
Unmatched records are logged into the run output and ignored for status purposes; a
launch with no matching record still fails the run closed. Records whose run entry is
missing or already terminal are garbage-collected during the housekeeping pass.

## Concurrency Management

Axe uses a cross-process runner pool to enforce global runner-capacity limits. The
`SharedRunnerPool` uses `fcntl.flock` on a shared file
(`~/.sase/axe/shared/runner_count`) to coordinate capacity claims and participating-lane
counts across all routine processes atomically.

Hook runners and agent runners have separate limits (`max_hook_runners` and
`max_agent_runners`), allowing fine-grained control over background resource usage.

## Agent Completion Artifacts

When an agent run finalizes, axe writes the normal completion metadata and sends the
workflow-complete notification. Successful runs also scan the agent workspace for
generated image files (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`), video files (`.mp4`,
`.m4v`, `.mov`, `.webm`), and Markdown files (`.md`, `.markdown`). When 10 or fewer
Markdown sources are discovered after filtering, they are rendered to PDFs under the
agent artifact directory, then the generated PDF paths are appended after the standard
chat/diff notification attachments and before image/video attachments. The PDF list is
persisted as `done.json.markdown_pdf_paths`; the image and video lists are persisted as
`done.json.image_paths` and `done.json.video_paths`. Explicit artifacts created during
the run with `sase artifact create -p <path> [-l <label>] [-k <kind>]` are appended
after generated media attachments when their stored files still exist.

The scan uses git name-status output, untracked files, saved diff metadata, and the
latest commit when the agent committed or opened a PR. Deleted, missing, unsupported,
and duplicate paths are ignored. If more than 10 Markdown sources remain, Axe skips
Markdown PDF rendering for that completion and adds a note to the notification. PDF
rendering is otherwise best-effort: missing conversion tools or render failures omit
that source without failing the agent run. Generated Markdown PDFs are optimized for
narrow viewers with a small portrait page, small margins, and larger type. As PDFs are
prepared, axe updates `workflow_state.json.pdf_status` and a compact `activity` label so
sase's TUI can show live finalization progress such as `PDF 2/4 <path>` or
`PDFs done 3/4 (1 skipped)` in the prompt/detail header's labeled `Activity:` field.
Successful runs also copy discovered media artifacts, plus prompt-referenced images and
videos, into persistent SASE artifact storage for sase's TUI. Prompt-referenced media
are not appended to completion notifications unless they were also generated/modified
files or explicit artifacts. See [`agent_images.md`](agent_images.md) for the full
contract.

The Agents tab exposes completion artifacts through the `a` action. When artifacts
exist, sase's TUI opens the artifact panel for selection. Chat transcripts, plan files,
generated PDFs/images/videos, prompt-referenced media from saved prompt artifacts, and
explicit artifacts created with
`sase artifact create -p <path> [-l <label>] [-k <kind>]` all participate in the same
list. Explicit artifacts are stored under `~/.sase/artifacts/` with a persistent
association so they remain available after dismissing and later reviving the agent.
sase's TUI shows the picker even for a single artifact. Inside that picker, `m` marks
rows, `Enter` opens the marked set or highlighted row, and `A` opens the full list. Only
one plan artifact is listed for an agent, preferring the committed SDD plan path when
one exists. Inside tmux, artifact viewing opens in a right-side tmux pane, collapses the
Agents list while live, uses `l` to focus the pane, and uses lowercase `a` to close it;
outside tmux, sase's TUI suspends and uses the current pane. The viewer supports images,
videos, Markdown, PDFs, and text fallbacks, wraps `j`/`k` page navigation at the ends,
uses `n`/`p` for artifact-sequence navigation, and warns when required
terminal/rendering tools are missing. The direct agent run-log binding is `V`.

## Maintenance Mode

Maintenance mode is a lightweight pause switch for scheduled work.
`sase axe maintenance enter --reason <text>` writes `~/.sase/axe/maintenance.json` with
the reason, caller PID, and start timestamp. Each routine checks that marker at the
start of every tick; while it is active, the routine records a cycle and skips the job
execution for that tick.

Use maintenance mode before operations that temporarily make scheduled work unsafe or
noisy, such as installing plugin updates, moving workspace directories, or running
one-off cleanup. `sase axe maintenance exit` removes the marker.
`sase axe maintenance status` exits 0 when active and 1 when inactive, so scripts can
use it as a guard. The next routine tick clears stale markers automatically when they
are older than 24 hours, malformed, or owned by a PID that is no longer running. When
Linux `/proc` identity data is readable, new markers also record the owner's process
start identity and, when available, the boot ID. Those fields let SASE reject a stale
marker after its PID has been recycled.

## Supervision and Recovery

The sase service host is the scheduler's only supervisor. It reconciles roughly every
second and restarts a crashed scheduler itself under its `Restart=on-failure` policy.
There is no second healer: no watchdog command, no timer, and no opportunistic healing
on agent waits. Use `sase axe routine status` or deep doctor mode to inspect individual
routines. `sase scheduler start` clears the boot-scoped stop marker and nudges the host,
while `sase scheduler stop` records that stop marker before shutdown. The desired state
is derived from the service host's own view of the `scheduler` proc (source
`service host`), so it records intent, not proof that the process transition succeeded.

`sase doctor -C axe.health` reports the same desired/live fields, but warns only when
the host wants the scheduler running and the orchestrator is down. Deep doctor mode
applies the same mismatch rule in its broader scheduler runtime check.

This distinction keeps the supervisor from undoing an intentional stop. To resume after
`sase scheduler stop`, start the scheduler again with `sase scheduler start`; that both
clears the stop marker and asks the host to launch the orchestrator.

SASE maintains a best-effort `~/.sase/axe/lifecycle.jsonl` journal capped at 256 KiB. It
appends every successful orchestrator start and each completed stop or restart request,
with its source. A start attempt that fails or exits before the PID is published has no
start entry. New records no longer stamp the retired desired-state marker; readers
tolerate old entries that still carry the field.

Managed restart paths, including sase's TUI and update-triggered restarts, ask the
service host to restart the `scheduler` service proc and report the host's answer
inline. `sase scheduler restart` is that same request made directly: it asks the host to
stop and start the proc and returns once the request is recorded. If the host itself
cannot keep the scheduler up, run `sase doctor` for the next step.

## State Directory

```
~/.sase/axe/
├── orchestrator.pid                # Orchestrator PID
├── orchestrator.lock               # Exclusive lifecycle lock held by the live orchestrator
├── lifecycle.jsonl                 # Bounded, source-attributed start/stop/restart journal
├── maintenance.json                # Optional maintenance marker that pauses routine ticks
├── logs/
│   ├── axe.log                     # Orchestrator startup log
│   └── lumberjack-{name}.log       # Per-routine logs (legacy filename)
├── lumberjacks/
│   └── {name}/                     # Per-routine state (legacy directory name)
│       ├── pid                     # Routine PID
│       ├── status.json             # Current status (updated every 5s)
│       ├── metrics.json            # Cumulative metrics (updated every 30s)
│       ├── chop_timestamps.json    # Last successful run_every timestamp per job
│       ├── agent_chops.json        # Durable registry of agents launched by this routine's jobs
│       ├── chops/                  # Per-job run history (legacy directory name)
│       │   └── {job}/
│       │       ├── index.json      # Ordered run IDs (newest first)
│       │       └── runs/
│       │           ├── {run_id}.json   # ChopRunEntry metadata
│       │           └── {run_id}.log    # Streamed stdout+stderr
│       ├── tick/
│       │   ├── context.json        # Context passed to script jobs
│       │   ├── all_changespecs.json
│       │   └── filtered_changespecs.json
│       └── logs/
│           └── output.log          # Routine output log
├── shared/
│   └── runner_count                # Cross-process runner counter
├── error_digests/                   # Error digest files for ViewErrorReport
│   └── digest_<timestamp>.txt      # Summarized error reports
└── recent_errors.json              # Last 100 errors encountered
```

## Process Lifecycle

The service host owns the scheduler's process lifetime; the scheduler owns only its
routine/job tree.

1. `sase scheduler start` asks the host to start the `scheduler` service proc. If the
   orchestrator is already live, start is a no-op.
2. The host execs the foreground orchestrator (`sase scheduler run`) as its child. The
   orchestrator removes stale PID files, adopts/holds the lifecycle lock, writes
   `orchestrator.pid`, and spawns all configured routines as child processes.
3. Each routine runs its jobs on its configured interval, unless maintenance mode is
   active.
4. The orchestrator monitors children and restarts any that exit unexpectedly. If the
   orchestrator itself crashes, the host restarts it under `Restart=on-failure`.
5. `sase scheduler stop` stops the service proc: SIGTERM to the orchestrator, which
   forwards it to all children. If the orchestrator does not exit within the stop
   timeout, the stopper escalates to SIGKILL and cleans up stale or owned PID files
   without deleting a PID published by a concurrent successful restart.

Under the host the scheduler's cgroup is `sase.service`, not a `.scope`.

Long-lived work that SASE detaches — agent runners, proc supervisors, monitor
supervisors, and typed launch-admission coordinators — escapes into its own transient
scope (for example `sase-agent-*`, `sase-proc-*`, or `sase-monitor-*`) whenever the
launching process already runs inside a SASE-owned systemd unit (`sase.service` or
another `sase-*` scope or service), so stopping or restarting the scheduler or a SASE
service does not tear down the agents and procs it launched. Outside a SASE-owned unit,
children keep the ordinary new-session detach; on macOS they always detach into a new
session. Set `SASE_DETACH_SCOPE_DISABLE=1` to turn off the child escape.

## sase's TUI Integration

The visible **Services** tab provides live monitoring of the service host, the
configured service procs, and the scheduler. The scheduler tree is nested below the
top-level `scheduler` service proc alongside any other configured services:

- A routine tree sidebar (routine rows + their jobs as children + background-command
  rows)
- A routine overview, per-job detail view, and run-history pager (see
  [Services Tab Views](#services-tab-views))
- Keyboard-first config management: `a` adds routines/jobs, `e` previews and edits the
  selected exact config entry, and `E` opens recorded job output. Disabled jobs remain
  visible but are not manually runnable; editing a generated row safely targets its base
  job and identifies the all-instances effect.
- Start/stop/restart the selected service proc (`x` / `r`), enable/disable it on this
  machine (`!e`), and runner counts
- The `SVC` footer pill shows the service host status: RUNNING, STOPPED, STARTING,
  STOPPING, or RESTARTING

Select the top-level scheduler row before pressing `x` or `r`; those keys intentionally
do nothing on its nested routines and jobs. `!x` starts or stops the whole service host.
The RESTARTING indicator appears when `sase tui --restart-service` (`--restart-axe`,
`-R`) is used — the host restarts in the background while the TUI starts up normally.

See [`docs/ace.md`](ace.md) for the full Services tab keybinding reference.

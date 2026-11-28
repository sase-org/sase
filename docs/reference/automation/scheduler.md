---
title: Scheduler
description: Scheduler commands, lifecycle, recovery, state, and SASE integration.
---

# Scheduler

This page covers scheduler commands, lifecycle, recovery, and integration with SASE.

## Overview

The scheduler is the background automation subsystem of sase. It watches Patches (the
per-PR records that sase uses to track work) and periodically runs lifecycle jobs such
as hook completion, mentor launch, workflow cleanup, comment polling, `%wait` dependency
checks, and error digests. `sase axe start|stop|restart|status` is the same command as
`sase scheduler start|stop|restart|status`. Older lumberjack/chop spellings remain
accepted; see
[Automation migration notes](../upgrading/automation.md#scheduler-routine-and-job-names).

The scheduler uses a multi-process architecture: an **Orchestrator** spawns multiple
**Routines**, and each routine runs a subset of jobs on its own schedule.

Two commands own two different layers:

- **`sase service`** owns the **service host**: the per-machine host process
  (`sase service run`) that starts, restarts, and stops that machine's service procs.
  `sase service init` registers it as a platform unit — a systemd user unit on Linux, a
  launchd LaunchAgent on macOS — so it starts at boot or login. The Linux unit sets
  `OOMPolicy=continue` next to `KillMode=mixed`, so one OOM-killed routine child no
  longer stops the whole host (an OOM-killed host main process still fails and restarts
  via `Restart=on-failure`). Existing installs compare stale against the rendered unit,
  so they show as stale until the normal service install or init path rewrites them.
- **`sase scheduler`** owns the **scheduler service proc**: the builtin service proc
  that runs the automation. Its start, stop, restart, and status commands route through
  the `scheduler` service proc on the service host; `sase scheduler run` execs the
  foreground orchestrator that the service host itself runs.

The `sase axe` surface remains for the routine/job tree (`sase axe job`,
`sase axe routine`, `sase axe maintenance`) alongside the four lifecycle aliases.

## Architecture

The orchestrator supervises one process per configured **routine**, a loop that runs a
set of **jobs**. The default configuration groups jobs by responsibility:

| Routine                                                                               | Main responsibilities                                                                      |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| [`hooks`](scheduler-default-routines.md#hooks-5-second-interval)                      | Hook and workflow completion, mentors, and dead-process cleanup                            |
| [`waits`](scheduler-default-routines.md#waits-10-second-interval)                     | Bead claims, epic-launch completion and recovery, and agent recovery after code updates    |
| [`agent_waits`](scheduler-default-routines.md#agentwaits-2-second-interval)           | Agent and bead dependency resolution through `wait_checks`                                 |
| [`sidecar_sync`](scheduler-default-routines.md#sidecarsync-30-second-interval)        | Fetch and fast-forward eligible primary sidecar clones; connect enabled projects' sidecars |
| [`publication`](scheduler-housekeeping.md#publication-15-second-interval)             | Queued agent and artifact-link publication                                                 |
| [`checks`](scheduler-default-routines.md#checks-5-minute-interval)                    | Periodic triage, submission checks, reconciliation, and recovery                           |
| [`usage`](scheduler-default-routines.md#usage-60-second-interval)                     | Subscription-usage refresh                                                                 |
| [`external_mirror`](scheduler-default-routines.md#external_mirror-15-minute-interval) | External issue and pull-request mirroring                                                  |
| [`comments`](scheduler-default-routines.md#comments-1-minute-interval)                | Remote review-comment polling                                                              |
| [`housekeeping`](scheduler-housekeeping.md#housekeeping-1-hour-interval)              | Error digests, disk cleanup, and artifact retention                                        |

Each linked routine entry lists its default interval and jobs. A routine tick is an
opportunity to run jobs: each job's trigger and cadence can cause it to skip that tick.
See [Scheduler jobs](scheduler-jobs.md).

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
  filters out Patches with [`PR_ORIGIN: external`](../work-units/patches.md#pr_origin)
  before any job evaluates them. Axe never acts on a Patch adopted from a PR it didn't
  create.

## CLI Commands

`sase axe job` and `sase axe routine` default to their `list` views when invoked without
a nested subcommand. See the generated [`sase scheduler`](../cli/scheduler.md) and
[`sase axe`](../cli/axe.md) pages for flags and subcommands. To put a repeated check on
a schedule, follow [Schedule recurring work](../../guides/schedule-recurring-work.md).

### Compatibility aliases {#compatibility-aliases}

Older lumberjack/chop spellings remain accepted as hidden aliases of the current
routine/job commands. See
[Automation migration notes](../upgrading/automation.md#scheduler-routine-and-job-names).

### Examples

```bash
# Start/stop the scheduler service proc (`sase axe start|stop` is the same command)
sase scheduler start
sase scheduler stop

# Ask the host to stop and start the scheduler proc; waits for the new pid
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
  start the proc and waits for the host to confirm the new pid, printing
  `pid OLD -> pid NEW`. `-n/--no-wait` returns once the request is recorded and
  `-t/--timeout SECONDS` bounds the wait. When the scheduler is down unexpectedly,
  recovery is the service host's `Restart=on-failure` plus `sase doctor`; see
  [Supervision and Recovery](#supervision-and-recovery).
- `sase doctor --deep` runs broader, slower diagnostics when the status evidence needs
  deeper investigation.
- `sase axe maintenance status` remains the compatibility/debugging view of only the
  maintenance marker.
- `sase axe routine status` remains the compatibility/debugging process view for
  individual routines.

## Routine Ticks {#routine-ticks}

Each tick, a routine writes a shared job context under `tick/` and runs its eligible
jobs concurrently. Ticks are kept cheap and bounded:

- **Bounded concurrency.** One tick runs at most the routine's `max_concurrent_jobs`
  jobs at once (default `4`; see
  [Routine Fields](scheduler-configuration.md#routine-fields)). Extra eligible jobs wait
  for a free slot, longest last-observed wall time first, so a long job does not queue
  behind short ones. Ties and jobs with no recorded run keep their configured order. A
  job's timeout starts when it starts, not when it is queued. A shutdown request stops
  queued jobs from starting. A tick that overruns its interval because of the cap says
  so in its "Tick overrun" log line.
- **Persisted cadence.** A routine whose interval is at least 60 seconds records when
  each tick that reaches job dispatch started, in `cadence.json` in its state directory.
  After a restart, whether of the service host, the scheduler, or a code swap, it waits
  until that tick plus one interval instead of re-running every job at once. A tick
  skipped for maintenance or held for a code swap does not count. Shorter routines still
  tick at start. `sase axe routine run ROUTINE -t/--tick-now` forces the first tick, and
  `sase axe job run` is unaffected.

- **Patch files only where read.** A routine serializes `all_changespecs.json` and
  `filtered_changespecs.json` only when an enabled job reads them: a job with a `patch`
  `inhibit_if` guard, a builtin Patch-lifecycle job (the hooks lane today), or any
  script outside the `sase_job_*`/`sase_chop_*` namespace. Elsewhere both context paths
  are empty strings, and the builtin job runtime parses Patches itself the first time a
  job asks for them.
- **No unchanged work.** A Patch-serializing routine re-parses only when a ProjectSpec
  file's mtime, size, or inode changed, and no routine rewrites a tick file whose
  content would not change.
- **Folded skips.** A scheduled skip whose reason matches the job's newest run record,
  itself a scheduled skip, adds no run. It folds into that record, which counts the
  skips in `skip_count` and moves `finished_at` to the latest one at most once a minute.
  Routine metrics still count every skip, and the routine log shows the first skip of a
  streak. A new reason, a manual run, or a real run starts a fresh record.
- **Honest spawn rate.** `spawns/min` in `sase axe routine status` is a rolling average:
  the spawns inside a window of `max(5 min, one interval)` divided by the window's
  observed duration. Readers recompute it from the `spawn_samples` in `metrics.json`, so
  it decays between ticks and sums across routines to the real spawn rate.

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
second and restarts a crashed scheduler itself under the entry's `restart: on-failure`
policy (a `service.procs` setting, not a systemd `Restart=` line), with a backoff that
starts at 1 second and doubles up to 60 seconds; three failures within 60 seconds mark
the proc `crash_loop` and raise one `service` notification per crash-loop episode. A
clean scheduler exit (exit code `0`, or death by `SIGTERM`, `SIGINT`, `SIGHUP`, or
`SIGPIPE` that the host did not request) is not restarted: the host parks the proc,
raises a `service` notification, and leaves it down until `sase scheduler start` (or
`restart`) revives it or the service host itself restarts. If the service configuration
stops loading, the host keeps supervising the scheduler under its last-known-good
configuration and reports the error in `sase service status`. There is no second healer:
no watchdog command, no timer, and no opportunistic healing on agent waits. Use
`sase axe routine status` or deep doctor mode to inspect individual routines.
`sase scheduler start` records a start request that clears the boot-scoped stop marker
and waits for the host to confirm the pid, while `sase scheduler stop` records that stop
marker before shutdown. The desired state is derived from the service host's own view of
the `scheduler` proc (source `service host`), so it records intent, not proof that the
process transition succeeded.

`sase doctor -C axe.health` reports the same desired/live fields, but warns only when
the host wants the scheduler running and the orchestrator is down. Deep doctor mode
applies the same mismatch rule in its broader scheduler runtime check.

This distinction keeps the supervisor from undoing an intentional stop. To resume after
`sase scheduler stop`, start the scheduler again with `sase scheduler start`; that both
clears the stop marker and asks the host to launch the orchestrator.

SASE maintains a best-effort `~/.sase/axe/lifecycle.jsonl` journal capped at 256 KiB. It
appends every successful orchestrator start and each completed stop or restart request,
with its source. A start attempt that fails or exits before the PID is published has no
start entry. New records omit the retired desired-state marker; readers tolerate old
entries that still carry the field. See
[Automation migration notes](../upgrading/automation.md#scheduler-lifecycle-journal).

Managed restart paths, including sase's TUI and update-triggered restarts, ask the
service host to restart the `scheduler` service proc and report the host's answer
inline. `sase update` waits up to 25 seconds for that confirmation and reports the
restart as unconfirmed when the host does not answer in time. `sase scheduler restart`
is that same request made directly: it asks the host to stop and start the proc and
waits for the confirmed `pid OLD -> pid NEW` (`-n/--no-wait` returns once the request is
recorded). If the host itself cannot keep the scheduler up, run `sase doctor` for the
next step.

## State Directory

```
~/.sase/axe/
├── orchestrator.pid                # Orchestrator PID
├── orchestrator.lock               # Exclusive lifecycle lock held by the live orchestrator
├── lifecycle.jsonl                 # Bounded, source-attributed start/stop/restart journal
├── maintenance.json                # Optional maintenance marker that pauses routine ticks
├── logs/
│   ├── axe.log                     # Orchestrator startup log
│   └── lumberjack-{name}.log       # Per-routine logs
├── lumberjacks/
│   └── {name}/                     # Per-routine state
│       ├── pid                     # Routine PID
│       ├── status.json             # Current status (updated every 5s)
│       ├── metrics.json            # Cumulative metrics + spawn window (every 30s)
│       ├── chop_timestamps.json    # Last successful run_every timestamp per job
│       ├── agent_chops.json        # Durable registry of agents launched by this routine's jobs
│       ├── chops/                  # Per-job run history
│       │   └── {job}/
│       │       ├── index.json      # Ordered run IDs (newest first)
│       │       └── runs/
│       │           ├── {run_id}.json   # ChopRunEntry metadata
│       │           └── {run_id}.log    # Streamed stdout+stderr
│       ├── tick/
│       │   ├── context.json        # Context passed to script jobs
│       │   ├── all_changespecs.json       # Only where a job reads Patches
│       │   └── filtered_changespecs.json  # Only where a job reads Patches
│       └── logs/
│           └── output.log          # Routine output log
├── shared/
│   └── runner_count                # Cross-process runner counter
├── error_digests/                   # Error digest files for ViewErrorReport
│   └── digest_<timestamp>.txt      # Grouped per-cause digest reports (30-day prune)
├── recent_errors.json              # Last 100 error samples, capped per signature
└── error_counts.json               # Durable exact per-cause interval totals
```

## Process Lifecycle

The service host owns the scheduler's process lifetime; the scheduler owns only its
routine/job tree.

1. `sase scheduler start` asks the host to start the `scheduler` service proc and waits
   for the confirmed pid. If the orchestrator is already live, start is a no-op that
   reports `already running: pid N`.
2. The host execs the foreground orchestrator (`sase scheduler run`) as its child. The
   orchestrator removes stale PID files, adopts/holds the lifecycle lock, writes
   `orchestrator.pid`, and spawns all configured routines as child processes.
3. Each routine runs its jobs on its configured interval, unless maintenance mode is
   active.
4. The orchestrator monitors children and restarts any that exit unexpectedly. If the
   orchestrator itself crashes, the host restarts it under `restart: on-failure`.
5. `sase scheduler stop` stops the service proc: SIGTERM to the orchestrator, which
   forwards it to all children. If the orchestrator does not exit within the stop
   timeout, the stopper escalates to SIGKILL and cleans up stale or owned PID files
   without deleting a PID published by a concurrent successful restart.

Under the host the scheduler's cgroup is `sase.service`, not a `.scope`.

Long-lived work that SASE detaches — agent runners, proc supervisors, monitor
supervisors, typed launch-admission coordinators, the scheduler's hook, checks, mentor,
and workflow (CRS, fix-hook, summarize) runners, the file-hook batch runner, the async
bead sync worker, and the chat-install worker — escapes into its own transient scope
(for example `sase-agent-*`, `sase-proc-*`, `sase-monitor-*`, `sase-hook-*`, or
`sase-mentor-*`) whenever the launching process already runs inside a SASE-owned systemd
unit (`sase.service` or another `sase-*` scope or service) **or** the user's systemd
manager is reachable (the launcher's cgroup sits under `user@<uid>.service`, or the user
bus socket exists), so stopping or restarting the scheduler, a SASE service, or the
launching terminal or tmux pane scope does not tear down the agents and procs it
launched. SASE scopes carry `OOMPolicy=continue`, so one OOM-killed process does not
stop the whole scope. Outside a reachable user manager, children keep the ordinary
new-session detach; on macOS they always detach into a new session. Set
`SASE_DETACH_SCOPE_DISABLE=1` to turn off the child escape. See
[Automation migration notes](../upgrading/automation.md#oom-in-a-sase-scope).

A SIGTERM that is neither an explicit user kill nor a handoff is recorded as an
**external** kill: the runner log prints a `Kill source: external ...` line (with the
cgroup's OOM-kill count when available), the `AGENT_KILLS` metric uses
`reason="external"`, and `done.json` gains the additive `kill_source` (`"user"` or
`"external"`) and optional `kill_evidence` (`cgroup_unit` plus `oom_kill_delta`) keys on
killed runs. `outcome` stays `"killed"`.

## sase's TUI Integration

The visible **Services** tab provides live monitoring of the service host, the
configured service procs, and the scheduler. The sidebar splits into the Service Procs
panel (every service proc, including the `scheduler` proc itself, plus oneshots) and the
User, Plugin, and Builtin Routines panels (the routine/job tree grouped by declaring
source):

- A routine tree sidebar (routine rows + their jobs as children + background-command
  rows)
- A routine overview, per-job detail view, and run-history pager (see
  [Services Tab Views](scheduler-jobs.md#services-tab-views))
- Keyboard-first config management: `a` adds routines/jobs, `e` previews and edits the
  selected exact config entry, and `E` opens recorded job output. Disabled jobs remain
  visible but are not manually runnable; editing a generated row safely targets its base
  job and identifies the all-instances effect.
- Start/stop/restart the selected service proc (`x` / `r`), enable/disable it on this
  machine (`!e`), and runner counts
- The `SVC` footer pill shows service health: a teal `N/M` count of running versus
  counted service procs, or a red `!` when the host is not running or a counted proc is
  unhealthy (see [Service Health Pill](../tui/agent-statuses.md#service-health-pill))

Select a service proc row in the Service Procs panel before pressing `x` or `r`; those
keys intentionally do nothing on routine and job rows in the routines panels. `!x`
starts or stops the whole service host. `sase tui --restart-service` (`--restart-axe`,
`-R`) restarts an already-running host in the background after the TUI's first status
load (it is a no-op when the host is not running); the pill keeps showing health
throughout.

See [TUI keymaps](../tui/keymaps.md) for the Services tab keybinding reference.

## Related

- [Default scheduler routines](scheduler-default-routines.md)
- [Scheduler housekeeping](scheduler-housekeeping.md)
- [Scheduler configuration](scheduler-configuration.md)
- [Scheduler description grammar](scheduler-description-grammar.md)
- [Scheduler jobs](scheduler-jobs.md)
- [Schedule recurring work](../../guides/schedule-recurring-work.md)
- [Automation migration notes](../upgrading/automation.md)

## `sase axe`

`sase axe start|stop|restart|status` is an alias of the matching `sase scheduler`
command. `-v/--vcs-provider` below is a `sase axe` group flag only; it applies to every
`axe` subcommand and has no `scheduler` spelling.

<a id="cli-options-4"></a> Moved to [sase axe](scheduler.md#sase-axe).

## `sase axe status`

Shows the `scheduler` service proc's status through the service host. Human output is
the default; JSON output is deterministic and never contains Rich markup or ANSI
escapes. `-j, --json` emits the proc record. See [Scheduler Status](#scheduler-status).

<a id="cli-options-5"></a> Moved to [sase axe](../cli/axe.md).

## `sase axe start`

Asks the service host to start the `scheduler` service proc and waits for the host to
confirm. This command takes no options; scheduler execution overrides belong to
`sase scheduler run` and `sase axe routine run`.

## `sase axe stop`

Asks the service host to stop the `scheduler` service proc and returns once the request
is recorded. It takes no flags.

## `sase axe restart`

Asks the service host to stop and start the `scheduler` service proc and waits for the
host to confirm the new pid. This command takes no options.

## `sase axe maintenance`

Maintenance mode pauses scheduled routine ticks without stopping the orchestrator.

<a id="cli-options-6"></a> Moved to [sase axe](../cli/axe.md).

<a id="command-behavior-2"></a> Moved to [Scheduler](scheduler.md#command-behavior-2).

## Command behavior {#command-behavior-2}

See [axe.md — Maintenance Mode](#maintenance-mode) for the runtime behavior.

## `sase axe job`

With no subcommand, `sase axe job` defaults to `sase axe job list`. Use the explicit
`list` or `doctor` subcommand when passing diagnostic flags.

<a id="cli-options-7"></a> Moved to [sase axe](../cli/axe.md).

<a id="command-behavior-3"></a> Moved to [Scheduler](scheduler.md#command-behavior-3).

## Command behavior {#command-behavior-3}

`sase axe job doctor` exits `1` when any check is `ERROR` (a configured script job
cannot be resolved) and `0` otherwise. Unconfigured available scripts and Telegram
prerequisite gaps report `WARN`. The same job diagnostics are also surfaced by
`sase doctor -C axe.jobs`. The hidden legacy `sase axe chop ...` group accepts the same
subcommands (plus the hidden `--chop-verbose` and `--lumberjack` spellings) and keeps
its schema-version-1 JSON; see [Compatibility aliases](#compatibility-aliases).

## `sase axe routine`

With no subcommand, `sase axe routine` defaults to `sase axe routine list`.

<a id="cli-options-8"></a> Moved to [sase axe](../cli/axe.md).

<a id="command-behavior-4"></a> Moved to [Scheduler](scheduler.md#command-behavior-4).

## Command behavior

Both listings print only the description summary line by default so the output stays
scannable; `-v/--verbose` renders the full
[description](scheduler-description-grammar.md#description-grammar).
`sase axe routine run` takes the routine name positionally; its runner flags are the
ones the orchestrator forwards when it spawns routines. The hidden legacy
`sase axe lumberjack ...` group accepts the same subcommands.

## Automation

Flag and option details live in the generated [CLI command groups](../cli/index.md):

- [sase scheduler](../cli/scheduler.md), [sase axe](../cli/axe.md)

Workflows: [Scheduler]().

The scheduler runs scheduled hooks, mentors, comment polling, workflow checks, `%wait`
dependency resolution, cleanup, and error digests. sase's TUI starts the service host
unless launched with `sase tui --no-service` (`--no-axe`).
`sase axe start|stop|restart|status` is an alias of the matching `sase scheduler`
command. The older `sase axe chop ...` and `sase axe lumberjack ...` spellings remain
hidden compatibility aliases for `sase axe job ...` and `sase axe routine ...`; see
[Compatibility aliases](#compatibility-aliases).

Flag and option details live in the generated [CLI command groups](../cli/index.md):

- [sase monitor](../cli/monitor.md), [sase pipe](../cli/pipe.md)

Workflows: [Monitors](monitors.md).

A long command (`just check-full`, a CI wait, a deploy) should run under a monitor
rather than blocking an agent turn — see the `/sase_monitor` skill. Handing this agent's
own turn to a successor is a different, in-process hand-off — see the `/sase_handoff`
skill.

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
checks, and error digests. AXE is its former name and remains an accepted alias:
`sase axe start|stop|restart|status` is the same command as
`sase scheduler start|stop|restart|status`.

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
  filters out Patches with [`PR_ORIGIN: external`](../../change_spec.md#pr_origin)
  before any job evaluates them. Axe never acts on a Patch adopted from a PR it didn't
  create.

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

| Legacy spelling                                                   | Current spelling                                       | Notes                                                                                |
| ----------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `sase axe lumberjack ...`                                         | `sase axe routine ...`                                 | Hidden CLI alias; completions and help advertise `routine`.                          |
| `sase axe chop ...`                                               | `sase axe job ...`                                     | Hidden CLI alias; legacy invocations keep schema-version-1 JSON.                     |
| `axe.lumberjacks.<name>.chops`                                    | `axe.routines.<name>.jobs`                             | Accepted on input; effective config and new examples use canonical keys.             |
| `chop_script_dirs`, `chop_timeout`                                | `job_script_dirs`, `job_timeout`                       | The old keys remain input aliases.                                                   |
| `lumberjack_log_*`, `lumberjack_restart_backoff_max_seconds`      | `routine_log_*`, `routine_restart_backoff_max_seconds` | The old keys remain input aliases.                                                   |
| `verbose_lumberjack_diagnostics`                                  | `verbose_routine_diagnostics`                          | The old key remains an input alias.                                                  |
| `SASE_CHOP_*`, `sase_chop_*`, `sase.chops`                        | `SASE_JOB_*`, `sase_job_*`, `sase.jobs`                | Script authors should use the job-named entrypoints and SDK facade.                  |
| `sase_chop_tg_inbound`, `sase_chop_tg_outbound` (`sase-telegram`) | `sase_job_tg_inbound`, `sase_job_tg_outbound`          | `sase axe job doctor` warns when only the legacy entrypoints are found.              |
| `chop:<routine>/<job>` artifact references                        | `job:<routine>/<job>` artifact references              | Both resolve to the same stored link identity.                                       |
| `sase doctor -C axe.chops`                                        | `sase doctor -C axe.jobs`                              | The old check ID remains a selection alias.                                          |
| Stored `chop` agent tribe                                         | `job` tribe                                            | See [Structured Results](scheduler-jobs.md#structured-results-and-launch-proposals). |

Canonical commands such as `sase axe job list --json` and `sase axe job doctor --json`
emit schema-version-2 JSON with routine/job field names (for example `routines`,
`routine_name`, `configured_jobs`, and `jobs`), and `sase config show` prints the AXE
block with canonical keys. Hidden legacy `chop` commands keep the schema-version-1
envelopes. Runtime state paths and durable registries are not migrated: directories
under `~/.sase/axe/lumberjacks/`, per-job `chops/` subdirectories, and
`agent_chops.json` remain intentionally legacy-named storage.

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
start entry. New records no longer stamp the retired desired-state marker; readers
tolerate old entries that still carry the field.

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
launched. SASE scopes carry `OOMPolicy=continue`, so one OOM-killed process no longer
stops the whole scope. Outside a reachable user manager, children keep the ordinary
new-session detach; on macOS they always detach into a new session. Set
`SASE_DETACH_SCOPE_DISABLE=1` to turn off the child escape.

This matters because an OOM kill in a terminal or tmux pane scope used to SIGTERM every
agent launched from it: systemd's default `OOMPolicy=stop` stops the whole scope after
one OOM kill, and agents launched from the TUI shared the TUI pane's cgroup. A SIGTERM
that is neither an explicit user kill nor a handoff is now recorded as an **external**
kill: the runner log prints a `Kill source: external ...` line (with the cgroup's
OOM-kill count when available), the `AGENT_KILLS` metric uses `reason="external"`, and
`done.json` gains the additive `kill_source` (`"user"` or `"external"`) and optional
`kill_evidence` (`cgroup_unit` plus `oom_kill_delta`) keys on killed runs. `outcome`
stays `"killed"`.

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

See [`docs/ace.md`](../../ace.md) for the full Services tab keybinding reference.

## Related

- [Default scheduler routines](scheduler-default-routines.md)
- [Scheduler housekeeping](scheduler-housekeeping.md)
- [Scheduler configuration](scheduler-configuration.md)
- [Scheduler description grammar](scheduler-description-grammar.md)
- [Scheduler jobs](scheduler-jobs.md)

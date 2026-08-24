# Axe — Background Automation Daemon

## Overview

Axe is the background automation subsystem of sase. It watches Patches (the per-PR
records that sase uses to track work) and periodically runs lifecycle jobs such as hook
completion, mentor launch, workflow cleanup, comment polling, `%wait` dependency checks,
and error digests.

Axe uses a multi-process architecture: an **Orchestrator** spawns multiple
**Lumberjacks**, and each lumberjack runs a subset of jobs on its own schedule. The ACE
TUI starts axe automatically unless launched with `sase ace --no-axe`; operators can
also manage it directly with `sase axe start` and `sase axe stop`.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator                          │
│  (spawns & monitors all lumberjacks)                    │
├──────────┬──────────┬──────────┬────────────┬───────────┤
│  hooks   │  waits   │  checks  │  comments  │ housekeep │
│  (5s)    │  (10s)   │  (5min)  │  (1min)    │ (1hr)     │
│          │          │          │            │           │
│ hook_    │ wait_    │ cl_sub-  │ comment_   │ error_    │
│ checks   │ checks   │ mitted_  │ checks     │ digest    │
│ mentor_  │          │ checks   │            │ managed_  │
│ checks   │          │ stale_   │            │ tmp_reap  │
│ workflow_│          │ running_ │            │           │
│ checks   │          │ cleanup  │            │           │
│ ...      │          │          │            │           │
└──────────┴──────────┴──────────┴────────────┴───────────┘
```

### Key Concepts

- **Orchestrator**: Parent process that spawns and monitors all lumberjack processes.
  Detects crashes and restarts failed lumberjacks automatically. Holds the axe lifecycle
  lock while running and forwards SIGTERM to all children on shutdown.

- **Lumberjack**: Individual scheduler loop that runs a subset of jobs on a fixed
  interval. Each lumberjack has a name (e.g., "hooks", "checks"), runs one or more chops
  per cycle, and maintains independent state and metrics.

- **Chop**: A single script-only job unit executed by a lumberjack. The executable reads
  context JSON and may return a structured result containing validated agent-launch
  proposals. The runner, never the script, launches those agents. Chops can declare
  cadence, triggers, guards, target fan-out, environment, and dedupe policy.

- **Candidate Patches**: Every cycle (checks, chops, and the lumberjack job list) first
  filters out Patches with [`PR_ORIGIN: external`](change_spec.md#pr_origin) before any
  job evaluates them. Axe never acts on a Patch adopted from a PR it didn't create.

## CLI Commands

`sase axe chop` and `sase axe lumberjack` default to their `list` views when invoked
without a nested subcommand.

| Command                                    | Description                                            |
| ------------------------------------------ | ------------------------------------------------------ |
| `sase axe start`                           | Start the orchestrator (spawns all lumberjacks)        |
| `sase axe stop`                            | Stop the orchestrator gracefully                       |
| `sase axe ensure`                          | Heal a missing daemon unless it was explicitly stopped |
| `sase axe ensure install`                  | Install and start the optional user-systemd watchdog   |
| `sase axe ensure uninstall`                | Stop and remove the optional user-systemd watchdog     |
| `sase axe status`                          | Show the read-only whole-system health snapshot        |
| `sase axe status --json`                   | Emit the schema-version-1 status object                |
| `sase axe chop list`                       | List configured chops with status (`-a` adds scripts)  |
| `sase axe chop list -v`                    | Add a panel with each chop's full description          |
| `sase axe chop doctor`                     | Diagnose configured/available chops and Telegram setup |
| `sase axe chop run <name>`                 | Run a single chop in the foreground                    |
| `sase axe chop run <name> -L <lumberjack>` | Run a single chop attributed to a specific lumberjack  |
| `sase axe lumberjack list`                 | List configured lumberjacks and their chops            |
| `sase axe lumberjack list -v`              | Add each lumberjack's full description under `details` |
| `sase axe lumberjack run <name>`           | Run a single lumberjack in the foreground              |
| `sase axe lumberjack status`               | Show status of all lumberjacks                         |
| `sase axe maintenance enter`               | Pause lumberjack ticks until maintenance exits         |
| `sase axe maintenance exit`                | Clear the maintenance marker                           |
| `sase axe maintenance status`              | Show whether maintenance mode is active                |

### Examples

```bash
# Start/stop the daemon
sase axe start
sase axe stop

# Check desired state and heal an unexpected outage
sase axe ensure

# Inspect whole-system health for an operator or automation
sase axe status
sase axe status --json

# On a host with user systemd, check automatically every five minutes
sase axe ensure install
sase axe ensure uninstall

# Run axe against only matching Patches
sase axe start --query '!!! OR @@@'

# Inspect lumberjacks
sase axe lumberjack list
sase axe lumberjack list --verbose  # also print each description body
sase axe lumberjack status

# Run a single lumberjack for debugging
sase axe lumberjack run hooks

# Inspect configured chops and discoverable scripts
sase axe chop list
sase axe chop list --available --verbose
sase axe chop doctor            # exits 1 if a configured script chop cannot be resolved

# Run a single chop once
sase axe chop run hook_checks

# Preview a proposal-emitting chop without launching agents
sase axe chop run 'refresh_docs[sase]' -L docs --dry-run --chop-verbose

# Disambiguate when the same chop name appears in multiple lumberjacks
sase axe chop run hook_checks --lumberjack hooks   # -L is the short form

# Pause/resume scheduled lumberjack work
sase axe maintenance enter --reason "install plugin update"
sase axe maintenance status
sase axe maintenance exit
```

## Whole-System Status

`sase axe status` collects one read-only snapshot of AXE intent and runtime evidence,
classifies it once, and renders an operator dashboard. It does not clean stale files,
start or stop processes, clear maintenance, or otherwise change host state.
`sase axe status -j` (equivalently `--json`) emits that same snapshot as the stable
schema-version-1 JSON object, with deterministic formatting and no Rich markup or ANSI
escapes.

The top-level lifecycle state and health are separate:

| State         | Meaning                                                                | Health      |
| ------------- | ---------------------------------------------------------------------- | ----------- |
| `running`     | The orchestrator and configured lumberjacks are coherently running.    | `healthy`   |
| `maintenance` | AXE is running with a valid maintenance marker pausing scheduled work. | `healthy`   |
| `stopped`     | The desired-state marker intentionally requests a stopped AXE.         | `healthy`   |
| `not_started` | No running process or explicit desired-state marker has been observed. | `healthy`   |
| `down`        | Desired state is `running`, but the orchestrator is not live.          | `unhealthy` |
| `degraded`    | Processes are live but orchestrator or lumberjack evidence is invalid. | `unhealthy` |
| `error`       | A required host input could not be collected or classified.            | `error`     |

The summary shows the desired state with its source and timestamp; orchestrator live
PIDs, lifecycle-lock state, and PID-file coherence; maintenance reason, owner, and age;
hook and agent runner occupancy; and the newest lifecycle journal event. The lumberjack
table is sorted by name and includes derived and reported state, process liveness, PID,
interval and staleness threshold, start and heartbeat times/ages, uptime, cycle and
historical error counts, and configured chops. At narrow terminal widths those facts
fold into a compact details column rather than being truncated.

When the classifier reports issues or collection failure, an **Attention** panel
preserves the issue order and lists deduplicated suggested commands. Exit codes are part
of the snapshot contract: `0` means healthy or intentionally inactive, `1` means
actionable degradation, and `2` means collection/classification error.

Use these related commands according to intent:

- `sase axe status` is the read-only first look at whole-system intent and health.
- `sase axe ensure` reconciles desired state and may start a missing orchestrator; it is
  a recovery command.
- `sase doctor --deep` runs broader, slower diagnostics when the status evidence needs
  deeper investigation.
- `sase axe maintenance status` remains the compatibility/debugging view of only the
  maintenance marker.
- `sase axe lumberjack status` remains the compatibility/debugging process view for
  individual lumberjacks.

## Default Lumberjacks

Axe ships with six default lumberjacks:

### hooks (5-second interval)

High-frequency hook lifecycle management:

| Chop                    | Description                                   |
| ----------------------- | --------------------------------------------- |
| `hook_checks`           | Complete finished hooks, start stale ones     |
| `mentor_checks`         | Start mentors once hook prerequisites are met |
| `workflow_checks`       | Complete/start CRS and fix-hook workflows     |
| `pending_checks_poll`   | Poll background check results                 |
| `comment_zombie_checks` | Mark old comment threads as ZOMBIE            |
| `suffix_transforms`     | Strip stale suffixes, update mail-readiness   |
| `orphan_cleanup`        | Release workspace claims for dead processes   |
| `stale_running_cleanup` | Release workspace claims from dead processes  |

### waits (10-second interval)

Fast-polling agent dependency resolution:

| Chop                | Description                                                            |
| ------------------- | ---------------------------------------------------------------------- |
| `epic_launch_flush` | Flush planner completions orphaned by unsettled epic launches          |
| `sidecar_auto_sync` | Fetch/fast-forward opted-in primary sidecar clones (plans, beads, ...) |
| `wait_checks`       | Resolve successful agent and closed-bead waits; write `ready.json`     |

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
artifact directory plus the offending outcome. The chop also emits a bounded sample of
waiters blocked by terminal dependencies so permanent stalls are diagnosable without
spamming ordinary live waiters.

Markers may also carry `wait_for_beads`, emitted by `%wait(bead=<bead-id>)`.
`wait_checks` reads the waiting agent's project bead store once per cycle and releases
the marker only when every named bead is closed as well as every agent or artifact
dependency being satisfied. Missing beads, unavailable stores, and read failures
deliberately fail closed and leave the agent parked; ACE's run-now action remains the
manual escape hatch. While live bead waits are outstanding, `sidecar_auto_sync` hints
their projects' `beads` role every 30 seconds — even when that role has not opted into
`auto_sync` — so the one conservative fetch/fast-forward sync policy converges it
promptly instead of a competing managed-integration refresh path. The waiting runner
also marks the same hint on a coarser ten-minute cadence as an outage backstop, in case
a chop failure ever leaves the tick-driven hint unconsumed. Setting
`sdd.bead_refresh.mode: off` disables both hint paths.

### checks (5-minute interval)

Lower-frequency status checks:

| Chop                    | Description                                                  |
| ----------------------- | ------------------------------------------------------------ |
| `bead_task_triage`      | Reconcile the one pending gate each task bead owns           |
| `plugins_required`      | Raise one `PluginsRequired` gate per project missing plugins |
| `pr_submitted_checks`   | Start PR submission status checks                            |
| `stale_running_cleanup` | Backstop dead-process claim cleanup                          |

**A live task bead has at most one pending gate**, and `bead_task_triage` is the single
owner of that invariant. It scans enabled non-home projects for task beads and derives
one of three gate kinds from that one issue type: a ready task gets a `TaskTriage` gate,
a snoozed one gets a `BeadSnooze` gate, and a task bead of type `flag` whose status is
`open` and whose date and release removal thresholds have both passed gets a
`FlagTriage` gate. All three kinds are reconciled in the same pass, under one lock and
one lane state, so no second chop can race this one into giving a bead two gates. The
bead-to-request mapping — including which kind each bead currently holds — lives in the
checks lumberjack's state directory. This scan does not call the dependency-aware
`sase bead ready` query, so a stored-ready task with an active blocker still receives a
gate. A flag task bead's due-ness is derived through the one shared `flag_removal_due`
predicate, never recomputed here.

A ready task bead additionally needs at least its
[effective `+1` bar](beads.md#per-type-triage-bar) of independent `+1` reports before it
earns a `TaskTriage` gate: its own task type's `triage.min_plus_ones` (`0` for most
builtins), or [`bead.task_triage.min_plus_ones`](configuration.md#bead) when the bead is
untyped or its type is not registered on this machine. A sub-threshold bead is withheld
from triage without any change to its stored status — it stays `ready` and stays visible
to `sase bead list`, `sase bead ready`, the ACE Beads panel, and its bead page — and a
`TaskTriage` gate already raised for a bead that later falls below the bar is canceled
(reason `task_bead_below_plus_one_threshold`) and its notification dismissed on the
chop's next tick. Snoozed beads and `flag` task beads are never subject to this bar.

A still-pending gate is skipped on later ticks, preventing repeated notifications. If a
bead leaves its gateable status or type through a launch, close, extension, or manual
retraction, the chop cancels its pending gate. If a gate becomes terminal or its bundle
disappears while the bead is still gateable, the next tick replaces it, except while
that bead has an active detached launch in flight. A persistent generation counter gives
each replacement a new deterministic request ID, whether the bead kept its status or
left and came back.

After project discovery succeeds and returns a non-empty inventory, the same
reconciliation also cancels pending gates when their project leaves the active
inventory, and cancels producer-owned gates no longer represented in the lumberjack's
lane state. An unavailable inventory fails closed without sweeping anything. A project
whose bead store is temporarily unreadable is likewise preserved for retry rather than
being mistaken for an inactive project and swept.

Two things also force a replacement. A gate of the wrong kind for the bead's current
status is canceled as `bead_status_changed` and replaced in the same tick — a bead that
was snoozed while its triage gate was pending is asking a different question now, so
that check outranks the presentation comparison below. Otherwise the chop compares a
presentation and gate-contract fingerprint over every stored field the gate renders:
status, the whole snooze record, title, description, notes, size, creation time, refs,
+1 evidence, close history, and (for a `flag` task bead) its key, kind, thresholds, and
due state, plus explicit renderer and option-contract versions. A mismatch cancels the
gate as `task_triage_presentation_changed` and re-raises it, so an edited description, a
re-snooze, an extended threshold, or an obsolete interaction contract never leaves a
gate advertising stale content, the old wake time, or superseded controls. While a
`BeadSnooze` gate stays pending and unchanged, the chop also re-snoozes its notification
to match the bead's wake time (whenever that wake time is still in the future), keeping
a snoozed bead's notification snoozed alongside it even after a crash or a manual
unmute.

The `TaskTriage` gate presents the task title, description, and notes, and offers three
options. **Launch** (the primary branch) accepts optional feedback and submits a
deduplicated global unattributed proc for `sase bead work <task-id> --yes-to-all`;
**Close** requires a reason and closes the bead as `canceled`; **Snooze** collects one
required `duration` line and defers the task, moving it to `snoozed` so the next tick
reconciles it into a `BeadSnooze` gate instead. The line takes the same
`"<wake-time> [+<N>]"` vocabulary the ACE snooze modal takes — for example `3d`,
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

The `plugins_required` chop is the human install offer that agent and non-interactive
contexts deliberately do not get. It scans enabled non-home projects, compares each
project's `plugins.required` list against installed distributions, and raises at most
one `PluginsRequired` gate per project per distinct missing or version-mismatched set.
**Install** runs `sase plugin install <name>` for each missing requirement from the
answering surface; when sase is not a `uv tool` install, that command fails with the
same actionable message `sase plugin install` already prints and the gate stays pending.
A successful install restarts axe. **Dismiss** records the decision so the same missing
set is not re-offered until it changes. The chop cancels the gate when the set becomes
satisfied. Lane state holds the pending request, a generation counter, and a fingerprint
over the missing set, so a re-run does not duplicate a notification. Run
`sase axe chop run plugins_required` to raise or refresh those gates without waiting for
the next five-minute checks tick.

### external_mirror (15-minute interval)

Isolated remote-tracker polling:

| Chop                    | Description                                    |
| ----------------------- | ---------------------------------------------- |
| `external_issue_mirror` | Mirror external tracker issues into task beads |
| `external_pr_mirror`    | Adopt remote pull requests as local Patches    |

Both chops are the same class of work — one bounded remote poll per project — so they
share a single generously paced lane instead of two. A healthy full pass is 1–3.5
seconds, so the 900-second interval leaves wide headroom, and a 5-minute per-chop
timeout means the worst-case cycle (`interval + chop_timeout`) stays a bounded 20
minutes without ever delaying the faster `checks` lane's PR-submission and
workspace-claim work.

`external_issue_mirror` expands to one instance per enabled project via
`for_each: {source: projects, vcs: [git, gh]}` (`external_issue_mirror[<project>]`), the
first production use of `for_each`. Each pass diffs that project's tracker against local
beads on `external_ref` and creates explicitly `small`, `open` (never `ready`) task
beads for uncovered issues, so no `TaskTriage` gate fires on a first-pass backlog. The
issue-listing seam has no page cursor or ordering guarantee, so every pass lists the
tracker's full inventory (`state="all"`, `limit=0`); the per-pass bound instead caps
local writes — at most 25 bead creations and 50 notes per pass, within a wall-clock work
budget derived from the lane's configured `chop_timeout`. A pass that hits the creation
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
would look exactly like "no issues." The check reports the chop's own persisted evidence
rather than attempting an interactive provider call.

See [Builtin `external_pr_mirror`](#builtin-external_pr_mirror) below for that chop's
own behavior, including where its cursor and backoff state live.

### comments (1-minute interval)

Comment polling:

| Chop             | Description                   |
| ---------------- | ----------------------------- |
| `comment_checks` | Start critique comment checks |

### housekeeping (1-hour interval)

Periodic maintenance:

| Chop                 | Description                                                                     |
| -------------------- | ------------------------------------------------------------------------------- |
| `error_digest`       | Send error notification digests (creates `ViewErrorReport` notification action) |
| `managed_tmp_reap`   | Prune stale scratch under the managed SASE temp root                            |
| `bead_stale_cleanup` | Sweep stale sub-threshold ready task beads into one `BeadStaleCleanup` gate     |

The `error_digest` chop summarizes recent errors into a digest file stored at
`~/.sase/axe/error_digests/digest_<timestamp>.txt`. The notification includes a
`ViewErrorReport` action that opens the digest in `$EDITOR` when selected in the ACE
notification modal.

The `managed_tmp_reap` chop bounds the managed SASE temp root (`$SASE_TMPDIR`, else
`~/.sase/tmp`) that `get_sase_managed_tmpdir()` hands out. Horizons are per
subdirectory: command scratch (`editors/`, `wrappers/`, `viewers/`, `commit-messages/`,
…) goes after 12 hours, handoff files (`handoff/`, `gh-diffs/`) after 3 days, and
artifacts the ACE Agents tab reads back (`launch-prompts/`, `workflow-artifacts/`) after
14 days. Each run removes at most 2,000 entries so a long-neglected root converges over
several passes instead of stalling one; the chop summary reports `scanned`, `removed`,
`deindexed`, and `capped=1` when it hit that budget. Reaped directories are dropped from
the agent artifact index too, since a workflow launched without an explicit
`artifacts_dir` gets one under `workflow-artifacts/`. It lives on `housekeeping` rather
than an interactive path because the first pass over a neglected root walks tens of
thousands of entries.

The `bead_stale_cleanup` chop is the other half of the task-bead `+1` bar. Ready task
beads that never clear their [effective `+1` bar](beads.md#per-type-triage-bar) stay
`ready` (the five-minute `bead_task_triage` chop withholds their `TaskTriage` gate) and
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
`sase axe chop run bead_stale_cleanup` to raise or refresh that gate without waiting for
the hour.

## Configuration

Axe is configured in `sase.yml` under the `axe:` section. See
[`docs/configuration.md`](configuration.md) for the full configuration reference.

### Global Settings

| Setting                                  | Default  | Description                                               |
| ---------------------------------------- | -------- | --------------------------------------------------------- |
| `max_hook_runners`                       | 3        | Concurrent hook runners allowed globally                  |
| `max_agent_runners`                      | 3        | Concurrent agent runners allowed globally                 |
| `zombie_timeout_seconds`                 | 7200     | Timeout for marking jobs as zombie                        |
| `query`                                  | `""`     | Optional query filter for all Patches                     |
| `chop_script_dirs`                       | `[]`     | Directories to search for chop scripts                    |
| `lumberjack_log_max_bytes`               | 52428800 | Maximum bytes retained for each bounded lumberjack log    |
| `lumberjack_log_temp_max_age_seconds`    | 300      | Age before orphaned log-rotation temp files may be reaped |
| `lumberjack_restart_backoff_max_seconds` | 60       | Maximum delay between retries for a crashing lumberjack   |
| `verbose_lumberjack_diagnostics`         | false    | Include verbose diagnostics in chop script context JSON   |

The `query` setting uses the same Patch query language as ACE. CLI flags on
`sase axe start` and `sase axe lumberjack run` override the configured query, runner
limits, and zombie timeout for that process.

### Lumberjack Configuration

```yaml
axe:
  lumberjacks:
    my_lumberjack:
      description: |-
        Run project-scoped custom checks once a minute

        Use this lane for inexpensive checks that should react within a minute. Individual chops may use run_every to
        reduce their own cadence; long-running maintenance and high-frequency lifecycle checks belong in separate
        lumberjacks.
      interval: 60 # Seconds between cycles
      chop_timeout: "60s" # Default timeout for all chops in this lumberjack
      wait_runners: 0 # Start lane agents only when no other agent holds a runner slot
      env: # Inherited by every chop; individual chop env wins
        API_TOKEN: { env: MY_API_TOKEN }
      chops:
        my_chop:
          script: my_chop_executable # Optional; defaults to name
          description: |-
            Run a custom validation after meaningful repository changes

            Creates one instance per enabled Git or GitHub project and runs at most once every 1h30m after ten new
            commits. A successful action advances the trigger checkpoint; an active toobig agent clan inhibits the
            check, and the per-chop timeout limits each run to 30 seconds.
          run_every: "1h30m" # Run at most once per compound duration
          timeout: "30s" # Per-chop timeout (overrides chop_timeout)
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
            source: projects # One stable my_chop[project] instance per enabled project
            vcs: [git, gh]
```

Every lumberjack requires a `description` explaining the lane's cadence and the class of
work it owns, and every chop requires one explaining what that chop does. Both follow
the summary/body grammar in [Description Grammar](#description-grammar).

#### Lumberjack Fields

| Field          | Type                   | Required | Description                                                                                                                    |
| -------------- | ---------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `description`  | `str`                  | yes      | Summary line, then a blank line, then an optional body (see [Description Grammar](#description-grammar))                       |
| `interval`     | `int`                  | no       | Seconds between chop polling cycles; defaults to `1`                                                                           |
| `chop_timeout` | `str \| null`          | no       | Default positive compound duration for chops in this lumberjack                                                                |
| `wait_runners` | `int \| null`          | no       | Start a lane agent once at most this many other agents hold runner slots; omitting it uses the global `max_running_agents` cap |
| `env`          | `dict[str, env-value]` | no       | Values inherited by every chop; individual chop env wins                                                                       |
| `chops`        | list or map            | no       | Composable chop definitions                                                                                                    |

`wait_runners` applies only to agents emitted through a script chop's
`proposed_launches`; it does not gate mentor, hook, or CRS workflow launchers. When a
chop proposes a clan, every member carries the threshold and waits independently, so a
low threshold can serialize the clan.

#### Chop Fields

| Field         | Type                   | Required  | Description                                                                                                                |
| ------------- | ---------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------- |
| `name`        | `str`                  | list only | Chop identity in object-list form; map form uses the mapping key                                                           |
| `description` | `str`                  | yes       | Summary line, then a blank line, then an optional body (see [Description Grammar](#description-grammar))                   |
| `script`      | `str \| null`          | no        | Exact executable name; defaults to the chop identity                                                                       |
| `enabled`     | `bool`                 | no        | Soft-disable a keyed entry without deleting the packaged/base configuration                                                |
| `run_every`   | `str \| null`          | no        | Positive compound duration (e.g., `"5m"`, `"1h30m"`, `"1d"`)                                                               |
| `timeout`     | `str \| null`          | no        | Per-chop timeout duration (overrides the lumberjack's `chop_timeout`)                                                      |
| `env`         | `dict[str, env-value]` | no        | Values merged over lumberjack env; literals or `{env:}`, `{file:}`, `{pass:}` refs                                         |
| `inhibit_if`  | list or map            | no        | `patch` / `agent_hood` / `agent_clan` / `agent_runners` guards evaluated before the script; `changespec` is a legacy alias |
| `trigger`     | string or map          | no        | `always` or `git.commits_since`; scheduled runs fire only when it accepts                                                  |
| `once_per`    | string or object       | no        | Bounded per-proposal dedupe-key template                                                                                   |
| `for_each`    | list or source         | no        | Literal target objects or `source: projects`, expanded to stable per-target instances                                      |
| `vars`        | `dict`                 | no        | Non-secret configuration copied into the script context                                                                    |

Map-form chops compose by identity across config layers. A higher-priority layer can
patch a single field or set `enabled: false` while retaining the rest of a packaged
entry. Object-list form remains accepted, but bare-string list entries are invalid
because they cannot provide the required description. Target instances use names such as
`my_chop[sase-core]`, with independent cadence, run history, checkpoints, and dedupe
state. Literal targets may include an `overrides:` object for per-target fields such as
`run_every`; the `projects` source accepts `name`/`names` and `vcs` filters.

Configuration is validated fail-closed. Unknown fields, duplicate chop identities, and
invalid or non-positive durations produce actionable errors with their config paths.
Secret references resolve at dispatch and fail closed with provider-specific
diagnostics. Legacy `agent:` and `xprompt:` chop fields are rejected: scheduled agent
work must originate from a script's structured launch proposals.

### Description Grammar

Both `axe.lumberjacks.<name>.description` and every chop `description` use one grammar,
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
ACE Axe tab, both CLI listings, and the entry editor always agree on where the summary
ends. It is computed once per entity when the config is parsed, never on a render or
keystroke path.

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
- Must stand alone: the collapsed Axe-tab panel, both CLI listings, and the entry
  editor's preview show only this line.

**Body**

- One to three short paragraphs and/or one bullet list. Aim for six to ten rendered
  lines.
- Answer, in this order, only what is true and non-obvious: what it actually does, when
  it fires, what state it reads or mutates, and the one thing an operator most needs to
  know (a failure mode, a safety property, a cost, a limit).
- Name the config knobs that matter when they are set (`interval`, `chop_timeout`,
  `run_every`, `trigger`, `inhibit_if`, `for_each`, `env`).
- Do not restate the summary, do not narrate the implementation line by line, and do not
  document SASE concepts that belong elsewhere in `docs/`.

**Lumberjack bodies additionally** state the cadence in words and why that cadence is
right for the lane, and say what belongs in the lane and what deliberately does not, so
a reader knows where to add a new chop.

**Mechanics**: bullets start with `- ` at the block's base indentation and continuation
lines indent two further spaces; no trailing whitespace, no tabs, and no blank line at
the end of the block.

### Script Chops

Every chop is an external executable. Axe resolves the exact configured `script` value
(or `name` when `script` is omitted) in this order:

1. An exact-name executable in one of `axe.chop_script_dirs`.
2. An exact-name executable beside the running Python interpreter.
3. An exact-name executable on `$PATH`.

No prefix is added automatically. Builtin chops therefore declare names such as
`script: sase_chop_hook_checks` explicitly. The available-script inventory still scans
`$PATH` for `sase_chop_*` executables as a discovery convenience, but resolution always
uses the configured full name.

Axe runs script chops as:

```bash
<script> --context <context.json>
```

The context file contains the effective runner limits, zombie timeout, query, lumberjack
name, lumberjack state directory, paths to legacy-named serialized
`all_changespecs.json` and `filtered_changespecs.json` files, the current `target`,
configured `vars`, the run source (`scheduled`, `manual`, or `oneshot`), the `dry_run`
flag, and the run-local result path. The result path is also exported as
`SASE_CHOP_RESULT_FILE`; the source and dry-run flag are mirrored as `SASE_CHOP_SOURCE`
and `SASE_CHOP_DRY_RUN` (`1` for true, `0` for false). `SASE_CHOP_VERBOSE` enables
opt-in debug output. Target fields are exported as `SASE_CHOP_TARGET_<FIELD>` along with
`SASE_CHOP_TARGET_KEY`. Scripts with direct side effects must honor `dry_run` before
mutating external state; runner-level dry-run only previews launch proposals. Scheduled
script chops within one lumberjack tick run concurrently; use `timeout` or
`chop_timeout` to keep a slow script from blocking later ticks indefinitely.

Script chop stdout and stderr are streamed to the chop's per-run log file while the
subprocess is still alive (see [Chop Run History](#chop-run-history) below). The Axe-tab
dashboard tails that file so a long-running chop's output becomes visible immediately
rather than only after process exit.

Chop output is part of the operator contract. Every actual chop run should write a
compact, human-readable summary for both no-op and action paths. At minimum, include the
chop identity or run scope, counts of inspected/skipped/updated or launched items, an
explicit no-op reason, and bounded identifiers for any affected items. Avoid tokens,
full notification bodies, full prompts, and unbounded command output in ordinary AXE
logs. A chop with a meaningful structured story should also publish a report while
keeping this compact stdout summary unchanged; logs and notifications continue to use
the summary line.

#### Structured Results and Launch Proposals

Exit-code-only scripts remain supported: exit zero means `success`, a non-zero exit
means `failure`, and no result file is required. A proposal-emitting script atomically
writes a schema-versioned JSON document to `SASE_CHOP_RESULT_FILE`:

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
`tribe`; the first accepted member declares the clan with the default `chop` tribe.

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

`report` is an optional structured document rendered with the result on the ACE AXE tab.
Chop authors supply semantic tones rather than colors, and the frontend owns the palette
and width-responsive layout. The public SDK keeps report construction typed and
validates the finished result through the Rust contract:

```python
from sase.chops import ChopReport, ChopResultBuilder

report = ChopReport(title="CI WATCH")
report.headline("4 green · 1 red · 1 fix proposed", tone="warn")
report.heading("REPOSITORIES")
rows = report.rows(columns=("REPOSITORY", "STATE", "EVIDENCE"))
rows.row(("sase-org/sase", "red", "ci / test · streak 2/2"), tone="error")
rows.row(("sase-org/sase-core", "green", "a1b2c3d"), tone="ok")
report.divider().kv({"mode": "dry run"}, tone="muted")

ChopResultBuilder(
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
failures, and `accent` for report emphasis. A chop cannot supply a color. Optional row
and bullet glyphs are restricted to `▲ ◆ • · ● ○ ✓ ✗ ↗ ↷ ⏱ ! ▸ ─`; omitting a glyph lets
the renderer choose one from the tone.

The validated report must fit within 32 KiB of UTF-8 and contain 1–48 blocks. A `kv`,
`rows`, or `bullets` block holds 1–64 entries. Rows contain 1–6 cells; when column names
are present there must be 1–6 of them and every row must have the same number of cells.
Titles are limited to 64 characters, and every other string field to 512 characters.
Required strings must be nonblank single-line text with no control characters.
`ChopReport` collapses whitespace, removes controls, truncates bounded strings with a
trailing ellipsis, drops empty blocks, and rejects invalid tones, glyphs, gauges, or row
shapes before writing. Unknown fields, block kinds, and tones are rejected fail-closed
by result validation.

The runner validates the full document before launching anything. It injects the
workspace reference, a deterministic agent name and `tribe=chop` in one `%id(...)`
directive, model/effort directives, and a `%wait` dependency for `wait_on`, then
launches proposals in document order. Clan-scoped proposals are preplanned as one
multi-prompt batch: the first surviving member declares one concrete clan generation and
later members join it, while waits use their full resolved names. A summarized declarer
receives `%clan(<name>, tribe=chop, summary=[[<literal Rich markup>]])`; joiners receive
only `%id(<member>, clan=<name>)`. Axe neither executes the value as a summary script
nor inserts it into any proposal's work prompt. Standalone `#!workflow` references are
forbidden in proposal prompts; reusable inline `#xprompt` references remain valid. The
runner records every launched agent in `agent_chops.json` and finalizes the chop only
when the linked agents reach terminal state.

A launcher can still fail partway through an otherwise valid batch. The caller receives
`action_failed` immediately. When at least one proposal already started, however, the
persisted chop run remains active as `launched` until every started agent finishes; it
then finalizes as `action_failed` with both the original launch error and any agent
failures. Once-per keys for accepted proposals that never started are released
immediately. A started proposal keeps its key while it runs, then releases it only if
that agent fails, so successful work remains de-duplicated. A key-release error is
appended to the chop output and does not replace the original launch or agent outcome.

A proposal's `prompt` may contain typed directives such as `%if::` (a Bash or Python
condition fence) or `%proc`. When the `typed_launch_units` beta flag is enabled, a batch
containing an active directive routes through the same durable typed admission
coordinator used by ACE, `sase run`, and LaunchApproval, joining AXE as a fourth typed-
admission source; see [Agent Launch Flow](architecture.md#agent-launch-flow). A `%if`
predicate evaluates after its unit's `%wait` dependency settles and before any runner,
workspace, agent identity, or model request is allocated. Exit `0` admits the unit
normally; exit `1` records a resource-free skip and allocates nothing. AXE owns the
admission bundle across the run, keeping the chop in active `launched` state until every
admitted unit reaches its own terminal state, and treats predicate skips as successful
no-op outcomes rather than once-per duplicates or launcher errors. A batch with no
active `%if`/`%proc` directive, or any batch while the flag is disabled, keeps using the
legacy launch path unchanged; an explicit typed directive while the flag is disabled
fails before any agent or model is dispatched.

Python chop packages should use the public `sase.chops` SDK (`load_chop_invocation`,
`ChopLogger`, `ChopReport`, `ChopResultBuilder`, and `launch_proposal`) for argument
parsing, summaries, reports, validation, and atomic result writes.

#### Publishing a Report a Notification Can Open

Per-chop run history is capped, so a report that only rides along with a chop result
answers "what did this tick do", not "where do things stand". A chop that wants the
second answer should **publish** a standalone report document into its own state
directory (`invocation.context.state_dir`) and point a notification at it:

```python
from sase.chops import ChopReport, validate_chop_report

report = ChopReport(title="RELEASES")
report.headline("2 merged today · 3 pending", tone="warn")
document = validate_chop_report(report.to_dict())
# atomically write `document` to <state_dir>/<name>.report.json on every tick
```

`validate_chop_report` runs the same Rust chop-result contract used for an embedded
`report`, so an invalid document is caught before it is written; log and skip that tick
rather than raising, leaving the previous good file in place. Rewriting the file on
every tick — including no-op ticks — is what keeps the published picture fresh without
any network call or latency inside the TUI.

The notification then carries `action: "ViewReport"` with
`action_data: {"report_path": "<state_dir>/<name>.report.json", "report_title": "..."}`.
Selecting it in ACE renders the document in the notification modal's right pane and
Enter opens it full-screen; see `docs/notifications.md` for the contract, the
inline-snapshot alternative, and the fail-closed loader limits. Prefer the published
path over inlining a snapshot into `action_data` whenever the chop has a durable state
directory. Timestamps inside a published document should be absolute, because the file
may be read long after it was written; relative freshness belongs to the single
provenance line the reader sees.

#### Triggers, Guards, Dedupe, and Targets

Policy is runner-owned and evaluated before the script:

- `run_every` limits cadence for each expanded chop instance. A guard skip does not
  consume this cadence, so a guarded chop re-evaluates its guard on the next tick rather
  than waiting out the full interval; a trigger skip (the condition was evaluated and
  not met) still advances the clock as before. Guard evaluation is not free — put a
  guard on a lane whose tick interval matches the cost of re-checking it.
- `inhibit_if` supports `patch`, `agent_hood`, `agent_clan`, and `agent_runners` guards.
  The legacy `changespec` guard key remains accepted as an alias.
  `agent_clan.name_prefix` matches canonical clan metadata on active agents only; dotted
  agent names are not treated as clans. `agent_runners.max` defaults to `0` and inhibits
  while more than that many agents hold runner slots, matching the population counted by
  `%wait(runners=N)` and the ACE runner-capacity chip. A `STARTING` agent has not yet
  been admitted and does not count; an agent parked on a question has yielded its slot
  and does not count. A match records a visible `skipped` run naming the guard and
  matching agent.
- `trigger` defaults to `always`. `git.commits_since` observes a project repository,
  fires when its threshold is met, and owns its checkpoint under the chop's state
  directory. A missing checkpoint fires once so a new chop is not silently inert.
- Checkpoint policy can be `on_observation`, `on_action_accepted`, or
  `on_action_success`. The last option advances only after every linked proposal agent
  succeeds.
- `once_per` renders a bounded per-proposal key; a proposal's own `dedupe_key` takes
  precedence. Duplicate proposals are skipped without relaunching work. Accepted keys
  remain reserved for successful launches, but are released when their proposal never
  starts or its launched agent reaches terminal failure, allowing a later run to retry
  that work. `dedupe_key` is durable work identity, not a retry clock: a key means "this
  is the same unit of work," and a successful no-op launch reserves it permanently.
  Chops whose work can go stale between scans should recheck eligibility with `%if`
  (below) instead of folding a repository revision into the key.
- `for_each` accepts literal target rows or `source: projects`. Expansion creates stable
  instances such as `refresh_docs[sase-core]`, each with independent cadence, history,
  checkpoints, and dedupe state. Target overrides can patch per-instance fields such as
  `run_every` and trigger thresholds.

Manual CLI/TUI runs bypass configured triggers because the operator explicitly requested
a run, but still honor guards. With `agent_runners`, a manual run while agents hold
runner slots skips unless `-f/--force` is passed to bypass both for that run.

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

`sase_chop_external_pr_mirror` fans out across enabled `git` and `gh` projects with
`for_each: {source: projects, vcs: [git, gh]}`. Each instance uses the target's
ProjectSpec directory key for local Patch files and the target workspace directory for
provider calls. A structural capability probe skips providers that cannot list PRs.

Incremental runs fetch a bounded PR inventory because the provider seam exposes a record
limit, not pagination. The chop records `seen`, `fetched`, `unmirrored`, `created`,
`repaired`, `refreshed`, `skipped`, `conflicts`, `errors`, `budget_exhausted`, and
`checkpoint_advanced` in its summary. Cursor and backoff state live at a stable path
under `~/.sase/external_mirror/`, independent of whichever lumberjack the chop is
configured in, so `sase patch sync-external` reads and writes the same files. A
ten-minute overlap window covers incremental passes; the cursor advances only after a
clean pass, and a daily full scan ignores it so missed repairs are eventually found.

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

`sase_chop_refresh_docs` replaces the former scheduled xprompt workflow. It expects an
expanded target with a `workspace`, then emits an `update` proposal and a `polish`
proposal whose `wait_on` points to `update`. Commit counting and checkpoints belong to
`git.commits_since`; project fan-out belongs to `for_each`:

```yaml
axe:
  lumberjacks:
    docs:
      description:
        Refresh project documentation when repositories accumulate meaningful changes
      interval: 300
      chops:
        refresh_docs:
          script: sase_chop_refresh_docs
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

### Manual Chop Runs

Scheduled lumberjack ticks are not the only way a chop runs. Operators can launch any
configured chop on demand from both the CLI and the ACE TUI; manual runs share the same
execution path, run history, and live-output streaming as scheduled runs.

**From the CLI:**

```bash
sase axe chop run <chop>                       # name must be unique across lumberjacks
sase axe chop run <chop> --lumberjack <lj>     # explicit lumberjack (short form: -L <lj>)
sase axe chop run <chop> --dry-run             # -n: validate and preview; launch nothing
sase axe chop run <chop> --chop-verbose        # -V: script diagnostics + full result
sase axe chop run <chop> --force               # -f: bypass guards (triggers already bypassed)
```

When the same chop name appears under multiple lumberjacks, `sase axe chop run <chop>`
fails with an unambiguous error listing the candidate lumberjacks. Pass
`-L/--lumberjack` to pick one. The manual run is recorded under
`~/.sase/axe/lumberjacks/<lumberjack>/chops/<chop>/` exactly like a scheduled run,
except its metadata is tagged with `source = "manual"` (vs `"scheduled"`).

**From the ACE TUI:**

On the Axe tab, press `r` while a chop row is selected to launch that exact
`(lumberjack, chop)` manually. The run uses the chop's configured script, environment,
and timeout, but bypasses any `run_every` cadence because the user explicitly asked for
it. The TUI does not block while the script runs; once the subprocess starts, the new
run becomes the newest entry in the chop's run history and the detail panel switches to
it.

If the selected chop already has a live script run in flight for the same
`(lumberjack, chop)`, `r` notifies and skips the launch rather than starting an
overlapping duplicate. On non-chop rows — lumberjack rows and running bgcmd rows — `r`
is a no-op; on a completed bgcmd row, `r` continues to re-run the bgcmd.

Manual runs participate in `Ctrl+N` / `Ctrl+P` history navigation just like scheduled
runs. The chop-detail header marks them with a `Source: manual` chip so it is easy to
tell at a glance why a run started.

### Chop Run History

Every chop execution — whether kicked off by a scheduled lumberjack tick or by
`sase axe chop run …` — is recorded as a separate run under
`~/.sase/axe/lumberjacks/<lumberjack>/chops/<chop>/`. Each run is assigned a sortable,
microsecond- precision `run_id`. `index.json` (kept next to `runs/`) lists the chop's
run IDs newest-first:

```
~/.sase/axe/lumberjacks/<lumberjack>/chops/<chop>/
├── index.json              # Ordered run IDs (newest first)
└── runs/
    ├── <run_id>.json         # Run metadata (see below)
    ├── <run_id>.log          # Streamed stdout+stderr from the chop process
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
(10) terminal runs per chop. Active `running` and `launched` entries are always kept
regardless of position, so slow scripts and pending actions are never deleted out from
under their lifecycle owners.

### AXE Tab Views

The Axe tab sidebar renders each lumberjack as a top-level row with its configured chops
as indented children, followed by any background commands (`!!`). Each chop row shows a
status marker derived from its newest cached run: active `running` / `launched`,
successful `success` / `action_succeeded`, healthy `no_op`, policy `skipped`, degraded
`check_error`, failed `failure` / `timeout` / `action_failed`, or `missing_script`.
Chops with no history remain marked as never run. Selection drives three distinct
dashboard views:

- **Lumberjack overview** — selecting a lumberjack row shows its status, interval, cycle
  count, error count, and a per-chop table with each chop's last-run status, relative
  timestamp, and duration. For a chop whose newest run is still active, the duration
  column shows live elapsed runtime rather than the stale `0ms` you would otherwise see
  before the run finalizes.
- **Chop detail** — selecting a chop row renders one width-responsive document. A
  universal **RESULT** card summarizes status, counters, reason, dry-run/source markers,
  proposals, launches, evidence, and failures from the cached run entry. A chop-authored
  structured report follows when the result document provides one, then **OUTPUT**
  preserves the run's ANSI-rendered `.log` tail. Until the log has accumulated any
  bytes, the output section shows a `Waiting for output…` placeholder; the exit code is
  suppressed until the run finalizes. Active `running` and `launched` runs continue
  following the output tail, while selecting a terminal run leaves the RESULT card at
  the top of the scroll region.
- **Background command output** — the existing live output stream for the focused `!!`
  row.

A chop whose run blocked its lumberjack's tick for at least the lumberjack's `interval`
is marked **overrun** — amber `⚠` with a `2.4×`-style ratio of blocking time to
interval. The newest sampled run being over is level `over` (bold); an older sampled run
in the cached history being over while the newest is not is level `intermittent` (dim),
so a chop that alternates does not flap its mark on and off across refreshes. The
sidebar chop chip and its parent lumberjack's roll-up chip always show the **worst**
ratio in the cached window, so a collapsed-then-expanded tree tells the same story every
time; the lumberjack overview's `PACE` column and the chop detail header instead
describe the **latest** run specifically, matching the rest of those views. A chop that
launches agents is measured on its script's own wall-clock time, not on how long the
launched agents ran — the tick never waited for them, so their lifetime is excluded from
the measurement.

`Ctrl+N` / `Ctrl+P` on the Axe tab page through the focused chop's run history (newer /
older). The viewer pins to the run you selected so that a fresh tick prepending a new
run does not bump you forward; the pin is cleared automatically if the pinned run is
pruned or itself becomes the newest run.

The same structured report renderer is used by `sase axe chop run` when that command
prints a structured result (dry run or chop-verbose mode), so semantic tones, rows,
gauges, and literal-text safety do not drift between the CLI and the ACE AXE tab.

### Chop-Agent Registry

The durable `agent_chops.json` linkage and `SASE_CHOP_*` metadata associate launched
proposals with chop lifecycle state. Configuration is always script-based. Each launched
agent receives `SASE_CHOP_LUMBERJACK`, `SASE_CHOP_NAME`, `SASE_CHOP_RUN_ID`, and a
prompt hash; the housekeeping pass uses the registry plus normal agent completion
artifacts to finalize `launched` runs.

Linkage is explicit: a registry record is created only for proposal launches the runner
itself performs and for continuation respawns (retry or model-fallback) of an
already-linked agent. Ambient `SASE_CHOP_*` context is scrubbed from every other spawned
child's environment, so nested launches by chop agents and launches performed by chop
scripts themselves neither register nor inherit chop identity.

Housekeeping matches registry records to the run entry's own recorded launches by
artifacts timestamp, following retry successors through `retried_as_timestamp` chains.
Unmatched records are logged into the run output and ignored for status purposes; a
launch with no matching record still fails the run closed. Records whose run entry is
missing or already terminal are garbage-collected during the housekeeping pass.

## Concurrency Management

Axe uses a cross-process runner pool to enforce global concurrency limits. The
`SharedRunnerPool` uses `fcntl.flock` on a shared file
(`~/.sase/axe/shared/runner_count`) to coordinate runner slots across all lumberjack
processes atomically.

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
ACE can show live finalization progress such as `PDF 2/4 <path>` or
`PDFs done 3/4 (1 skipped)` in the prompt/detail header's labeled `Activity:` field.
Successful runs also copy discovered media artifacts, plus prompt-referenced images and
videos, into persistent SASE artifact storage for ACE. Prompt-referenced media are not
appended to completion notifications unless they were also generated/modified files or
explicit artifacts. See [`agent_images.md`](agent_images.md) for the full contract.

The Agents tab exposes completion artifacts through the `a` action. When artifacts
exist, ACE opens the artifact panel for selection. Chat transcripts, plan files,
generated PDFs/images/videos, prompt-referenced media from saved prompt artifacts, and
explicit artifacts created with
`sase artifact create -p <path> [-l <label>] [-k <kind>]` all participate in the same
list. Explicit artifacts are stored under `~/.sase/artifacts/` with a persistent
association so they remain available after dismissing and later reviving the agent. ACE
shows the picker even for a single artifact. Inside that picker, `m` marks rows, `Enter`
opens the marked set or highlighted row, and `A` opens the full list. Only one plan
artifact is listed for an agent, preferring the committed SDD plan path when one exists.
Inside tmux, artifact viewing opens in a right-side tmux pane, collapses the Agents list
while live, uses `l` to focus the pane, and uses lowercase `a` to close it; outside
tmux, ACE suspends and uses the current pane. The viewer supports images, videos,
Markdown, PDFs, and text fallbacks, wraps `j`/`k` page navigation at the ends, uses
`n`/`p` for artifact-sequence navigation, and warns when required terminal/rendering
tools are missing. The direct agent run-log binding is `V`.

## Maintenance Mode

Maintenance mode is a lightweight pause switch for scheduled axe work.
`sase axe maintenance enter --reason <text>` writes `~/.sase/axe/maintenance.json` with
the reason, caller PID, and start timestamp. Each lumberjack checks that marker at the
start of every tick; while it is active, the lumberjack records a cycle and skips the
chop execution for that tick.

Use maintenance mode before operations that temporarily make scheduled work unsafe or
noisy, such as installing plugin updates, moving workspace directories, or running
one-off cleanup. `sase axe maintenance exit` removes the marker.
`sase axe maintenance status` exits 0 when active and 1 when inactive, so scripts can
use it as a guard. The next lumberjack tick clears stale markers automatically when they
are older than 24 hours, malformed, or owned by a PID that is no longer running. When
Linux `/proc` identity data is readable, new markers also record the owner's process
start identity and, when available, the boot ID. Those fields let SASE reject a stale
marker after its PID has been recycled.

## Watchdog and Recovery

`sase axe ensure` is a single-shot, idempotent reconciliation of the requested axe state
and the orchestrator process. It checks only orchestrator liveness; use
`sase axe lumberjack status` or deep doctor mode to inspect individual lumberjacks.
Start and restart requests write `running` before attempting startup, while
`sase axe stop` writes `stopped` before shutdown. The marker therefore records intent,
not proof that the process transition succeeded.

| Desired-state marker | Live orchestrator | `sase axe ensure` result                                      |
| -------------------- | ----------------- | ------------------------------------------------------------- |
| `running`            | Yes               | Reports healthy; no process change                            |
| `running`            | No                | Starts axe and reports healed, or exits 1 if startup fails    |
| `stopped`            | Either            | Reports explicitly stopped; no process change                 |
| Missing or invalid   | Yes               | Uses the historical running default and reports healthy       |
| Missing or invalid   | No                | Uses the historical running default and attempts to start axe |

After a successful heal, SASE makes a best-effort attempt to write an **Axe
self-healed** entry to the notification inbox. Notification failure does not turn the
heal into a failure. `sase doctor -C axe.health` reports the same desired/live fields,
but warns only when a valid marker explicitly says `running` and the orchestrator is
down. With no marker and no process, that doctor check reports OK even though a
subsequent `sase axe ensure` would attempt startup. Deep doctor mode applies the same
explicit-`running` mismatch rule in its broader AXE runtime check.

This distinction prevents a watchdog from undoing an intentional stop. To resume healing
after `sase axe stop`, start axe again with `sase axe start`; that both launches the
daemon and restores the desired state to running. Installing or uninstalling the
watchdog does not directly rewrite an explicit desired state, and uninstalling it does
not stop a running daemon. Once enabled, however, each due timer invocation behaves like
bare `ensure`, including treating a missing marker as `running`.

Agent runners blocked on dependency waits also make best-effort ensure calls. Those
calls share a host-wide marker and are limited to at most one actual check every five
minutes. The optional timer is useful when no waiting agent is alive to make those
checks.

SASE maintains a best-effort `~/.sase/axe/lifecycle.jsonl` journal capped at 256 KiB. It
appends every successful orchestrator start—including automatic healing—and each
completed stop or restart request, with its source. A start attempt that fails or exits
before the PID is published has no start entry. Before healing a down daemon, `ensure`
checks this journal for restart churn. By default, five successful starts within the
preceding 30 minutes damp further automatic healing: the command returns a rate-limited
result without starting axe and emits a durable **Axe restart storm damped**
notification. Repeated alerts are suppressed while the set of contributing starts is
unchanged. The notification identifies their sources and attaches the journal; healing
becomes eligible again after enough starts age out of the window. Explicit lifecycle
commands remain available to the operator.

On Linux hosts with user systemd, `sase axe ensure install` writes and enables
`sase-axe-ensure.service` and `sase-axe-ensure.timer` under the user systemd directory.
Its first activation is scheduled for two minutes after boot (or promptly when enabled
after that point), followed by an activation five minutes after the prior service
activation. The monotonic timer does not replay missed intervals after downtime. It
invokes the stable SASE executable selected at installation time and preserves
`SASE_HOME` when that variable is set. `sase axe ensure uninstall` disables the timer
and removes both units. On systems without `systemctl --user`, run bare
`sase axe ensure` manually or from the host's scheduler instead.

Managed restart paths, including ACE and update-triggered restarts, record `running`,
make up to three startup attempts, and report success only after the orchestrator is
live and every configured lumberjack reports `running` with PID and heartbeat values
changed from the pre-restart snapshot. If all attempts fail, SASE records the attempt
summaries in `recent_errors.json` and sends a durable **Axe restart failed**
notification; an installed watchdog can try a clean start on a later tick.

## State Directory

```
~/.sase/axe/
├── orchestrator.pid                # Orchestrator PID
├── orchestrator.lock               # Exclusive lifecycle lock held by the live orchestrator
├── desired_state.json              # Last requested running/stopped state
├── ensure.lock                     # Serializes ensure checks with one another and explicit stops
├── ensure.json                     # Timestamp/source of the latest non-rate-limited ensure check
├── lifecycle.jsonl                 # Bounded, source-attributed start/stop/restart journal
├── maintenance.json                # Optional maintenance marker that pauses lumberjack ticks
├── logs/
│   ├── axe.log                     # Orchestrator startup log
│   └── lumberjack-{name}.log       # Per-lumberjack logs
├── lumberjacks/
│   └── {name}/                     # Per-lumberjack state
│       ├── pid                     # Lumberjack PID
│       ├── status.json             # Current status (updated every 5s)
│       ├── metrics.json            # Cumulative metrics (updated every 30s)
│       ├── chop_timestamps.json    # Last successful run_every timestamp per chop
│       ├── agent_chops.json        # Durable registry of agents launched by this lumberjack's chops
│       ├── chops/                  # Per-chop run history (newest 10 terminal runs per chop)
│       │   └── {chop}/
│       │       ├── index.json      # Ordered run IDs (newest first)
│       │       └── runs/
│       │           ├── {run_id}.json   # ChopRunEntry metadata
│       │           └── {run_id}.log    # Streamed stdout+stderr
│       ├── tick/
│       │   ├── context.json        # Context passed to script chops
│       │   ├── all_changespecs.json
│       │   └── filtered_changespecs.json
│       └── logs/
│           └── output.log          # Lumberjack output log
├── shared/
│   └── runner_count                # Cross-process runner counter
├── error_digests/                   # Error digest files for ViewErrorReport
│   └── digest_<timestamp>.txt      # Summarized error reports
└── recent_errors.json              # Last 100 errors encountered
```

## Process Lifecycle

1. `sase axe start` first checks for a live orchestrator PID. If one exists, start is a
   no-op and returns the existing PID.
2. If no live PID exists, startup acquires `~/.sase/axe/orchestrator.lock` and hands
   that lock to the detached orchestrator process. Concurrent starts wait briefly and
   then return the live PID or decline to start.
3. The orchestrator removes stale PID files, adopts/holds the lifecycle lock, writes
   `orchestrator.pid`, and spawns all configured lumberjacks as child processes.
4. Each lumberjack runs its chops on its configured interval, unless maintenance mode is
   active.
5. The orchestrator monitors children and restarts any that exit unexpectedly.
6. `sase axe stop` sends SIGTERM to the orchestrator, which forwards it to all children.
   If the orchestrator does not exit within the stop timeout, the stopper escalates to
   SIGKILL and cleans up stale or owned PID files without deleting a PID published by a
   concurrent successful restart.
7. `sase axe ensure` compares this live state with `desired_state.json`; it heals
   unexpected downtime but honors an explicit stop. See
   [Watchdog and Recovery](#watchdog-and-recovery).

## ACE Integration

The Axe tab in the ACE TUI provides live monitoring of the daemon:

- A lumberjack tree sidebar (lumberjack rows + their chops as children +
  background-command rows)
- A lumberjack overview, per-chop detail view, and run-history pager (see
  [AXE Tab Views](#axe-tab-views))
- Keyboard-first config management: `a` adds lumberjacks/chops, `e` previews and edits
  the selected exact config entry, and `E` opens recorded chop output. Disabled chops
  remain visible but are not manually runnable; editing a generated row safely targets
  its base chop and identifies the all-instances effect.
- Start/stop the orchestrator (`x` key or `!x`) and runner counts
- Footer shows a segmented `AXE` badge followed by daemon status: RUNNING, STOPPED,
  STARTING, STOPPING, or RESTARTING

The RESTARTING indicator appears when `sase ace --restart-axe` (`-R`) is used — the
daemon restarts in the background while the TUI starts up normally.

See [`docs/ace.md`](ace.md) for the full Axe tab keybinding reference.

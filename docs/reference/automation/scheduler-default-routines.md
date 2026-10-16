---
title: Default scheduler routines
description: The built-in routines that run background SASE maintenance and automation.
---

# Default scheduler routines

This page lists the default routines and the work each routine performs.

## Default Routines

The scheduler ships with nine default routines.

<a id="housekeeping-1-hour-interval"></a> Moved to
[Scheduler housekeeping](scheduler-housekeeping.md#housekeeping-1-hour-interval).

## hooks (5-second interval) {#hooks-5-second-interval}

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

## waits (10-second interval) {#waits-10-second-interval}

Bead-claim reconciliation and epic-launch flushing:

| Job                  | Description                                                   |
| -------------------- | ------------------------------------------------------------- |
| `bead_claim_checks`  | Acquire/release bead claims for pre-launch agents             |
| `epic_launch_flush`  | Flush planner completions orphaned by unsettled epic launches |
| `agent_auto_restart` | Sweep update-skew recoveries; submit the healer as a proc     |

## agent_waits (2-second interval) {#agentwaits-2-second-interval}

Fast-polling agent dependency resolution:

| Job           | Description                                                        |
| ------------- | ------------------------------------------------------------------ |
| `wait_checks` | Resolve successful agent and closed-bead waits; write `ready.json` |

`wait_checks` runs in its own 2-second routine so a slow `sidecar_auto_sync` pass does
not convoy it behind a shared 10-second tick.

## sidecar_sync (30-second interval) {#sidecarsync-30-second-interval}

Primary sidecar convergence, isolated from wait resolution:

| Job                 | Description                                                            |
| ------------------- | ---------------------------------------------------------------------- |
| `sidecar_auto_sync` | Fetch/fast-forward opted-in primary sidecar clones (plans, beads, ...) |

The routine interval provides the 30-second cadence. The per-job `2m` timeout stays.
After a `beads`-role refresh, the job touches that project's completion pulse so
`agent_waits` re-evaluates bead waits on its next 2-second tick.

`bead_claim_checks` and `wait_checks` both ship with an `fs` trigger watching the
per-project completion pulse
(`paths: [{path: projects, glob: "*/artifacts/.ace_refresh_pulse"}]`,
`max_quiet: "120s"`), so an idle tick only re-scans when something touches that
project's `artifacts/.ace_refresh_pulse` file. Agent completions (via
`write_done_marker_and_update_index` and the hook-runner done writer), gate/monitor turn
settlement, handoff and repeat-stop finalization, a dependency-carrying `waiting.json`
write, and TUI wait-target edits all touch the pulse; pure runner-slot queue republishes
deliberately do not, and per-agent pulses written inside run directories never match the
project-level glob. Anything the pulse cannot observe — such as the dead-owner claim
release, where no live process writes anything — still resolves on the `max_quiet`
backstop. `epic_launch_flush` is untouched by that guard; it already throttles via
`run_every: "30s"`. `sidecar_auto_sync` lives in its own 30-second routine now.

`agent_auto_restart` sweeps update-skew recoveries (see
[Agent auto-restart](../agent-auto-restart.md) for the full feature guide): it
enumerates recovery doorbells, recent failed rows, and stale, deferred, and launched
ledger records, then submits `sase agent auto-restart run -p -j` as a durable proc
(concurrency key `agent-auto-restart`, one at a time) when work exists. It settles
`launched` records from their replacement's outcome, re-surfaces stale `pending` rows,
and — when the feature is off or paused — re-surfaces pending failures loudly instead of
healing them. Its `fs` trigger watches `agent_auto_restart/doorbell` and the code-swap
lock file with `max_quiet: "60s"`; idle ticks cost a handful of `stat()` calls and the
full artifact scan runs at most once a minute.

`wait_checks` unblocks a named dependency when the newest matching agent, or the newest
matching workflow root and all of its children, has a successful terminal `done.json`
outcome: `"completed"`, `"noop"`, `"epic_approved"`, or `"plan_committed"`. An ordinary
wait on an epic-approved planner releases when that planner finishes. An ordinary wait
on an epic-approved planner follows it into the epic it launched: `%wait(planner)` also
waits until that epic is closed (opt out with `%wait(planner, for_epic=false)`). The
runner initial check, the parked-runner fallback, `wait_checks`, and kill/dismiss share
that decision. The default is true for user-authored agent targets; `--plan` rows never
follow. `"noop"` agents can also satisfy waits even though they are hidden from normal
done-agent lists. Failed, killed, stopped, crashed, still-running, malformed, or missing
`done.json` artifacts do not satisfy `%wait`; the dependent agent remains parked until a
later successful run of the same dependency name appears. `"plan_rejected"` is
deliberately identity-terminal for exact artifact waits but does not satisfy a named
`%wait`.

Each tick walks every project's `ace-run` directories for `waiting.json` markers and
classifies each pending waiter (marker present, `ready.json` absent) by runner liveness:
`alive` for a running recorded pid, `dead` for a `stopped_at` stamp or a provably gone
pid (PID reuse guarded by `process_identity` and boot time), and `unknown` when no pid
was recorded. Unknown waiters resolve as if live; dead waiters are skipped entirely — no
resolution, no notifications — and counted in the `dead_waiting` backlog counter
alongside `live_waiting` and `unknown_liveness`. With no live or unknown waiter pending,
the tick emits its summary without building any dependency view, and `unresolved` counts
only live/unknown waiters. The resolving view itself is built from filesystem
`agent_meta.json` rows rather than the artifact index. Named-agent and bead-only waiters
resolve from a scoped view: only rows whose identity keys intersect the live waiters'
dependency names, plus each scopable waiter's own directory. Confirmation re-lists those
projects fresh and keeps the same per-waiter key set, so a member that appears between
the two views still defers release. Unscopable shapes — `@tribe` names, hoods, fork
sources, identity (`wait_for_artifacts`) deps, and armed epic follows — keep today's
full view, built at most once per tick and only when a live waiter needs it.

The `wait_checks` summary includes `walk_ms` for marker scanning and liveness
classification, `view_ms` for dependency view construction, `resolve_ms` for the
per-waiter loop, `view_rows` for the rows loaded into views during the tick,
`scoped_waiters` for live waiters resolved from the scoped view, and `full_view_waiters`
for live waiters that used the full view. Progress lines report the waiter counts after
classification and the resolving view's row count; chop log lines flush immediately so
they remain available if the job is killed.

If an unresolved dependency already has a terminal `done.json` outcome that wait
resolution does not recognize, `wait_checks` increments `unknown_outcome` and logs the
artifact directory plus the offending outcome. The job also emits a bounded sample of
waiters blocked by terminal dependencies so permanent stalls are diagnosable without
spamming ordinary live waiters.

An armed epic follow moves through `launching`, `following`, and `blocked` stages
(`none` is never persisted). `launching` means the planner finished but no epic has
appeared yet: the launch is still in flight, or it ended inside a short settle window (2
minutes) that absorbs monitor/proc handoff lag. `following` means the launched epics
were pinned into `wait_for_beads` and the wait now tracks them like ordinary bead waits.
`blocked` means no epic will appear without operator action: the launch was skipped, it
ended without an epic, the target was dismissed mid-launch, or the follow would cycle
back onto the waiter. A `launching` follow stays quiet until its `since` is older than
the 10-minute grace period; only then does `wait_checks` raise one deduplicated inbox
entry per waiter and target, and likewise one entry per `blocked` follow (naming the
reason with its resume command, jumping to the waiter) and one per followed epic whose
land agent failed terminally (naming the waiter, the epic, and the land agent). Repeat
ticks corroborate the single entry with +1 instead of duplicating it, and the entry is
dismissed once its state resolves or the waiter's runner is classified `dead` (a dead
runner never releases, so its follow entries are stale). Nothing about a follow ever
releases on a timeout: an overdue or blocked waiter stays parked until an epic appears,
the follow is cleared, or the wait is relaunched.

Two guards keep a follow from deadlocking the epic machinery. The deadlock guard drops
any launched epic that already contains the waiter: the waiter's own bead equals the
epic or is a phase bead nested under it. The cycle guard blocks when a live agent in the
launched epic's clan already waits on the waiter — through `waiting_for`, `wait_for`, or
the approval "Wait for" field — because each side would otherwise wait out the other
forever.

Before writing `ready.json`, `wait_checks` confirms an agent-shaped release against a
fresh on-disk membership view taken after the resolving marker read. If a session gained
a member in between — for example, a coder just launched its monitor or gate — the
waiter remains parked for a later tick. The waiting runner applies the same confirmation
for its startup and periodic fallback path. Such ordinary deferrals are counted in the
`deferred_unconfirmed` summary field rather than treated as errors.

The runner's startup check and 60-second fallback build that view from the waiter's
project only. Named waits and bead-only waits use a scoped index: rows whose identity
keys intersect the marker's dependency names, plus the waiter's own artifact directory.
Unscopable shapes — `@tribe` names, hoods, fork sources, identity deps, and armed epic
follows — still load the full project index. Release decisions stay the same as the full
view; scoping only drops rows that those queries never consult.

Row selection itself goes through a persistent scope-key cache
(`~/.sase/cache/wait_scope_keys.json`), so a live tick stats each artifact's
`agent_meta.json` instead of reading it. Each entry maps an ace-run artifact directory
to its meta `(st_mtime_ns, st_size, st_ino)` fingerprint plus its sorted scope keys.
Only `wait_checks` writes the file — atomically, and only when an entry changed — while
runners read it read-only and read the meta themselves on a miss. An unreadable,
corrupt, or wrong-schema cache counts as empty, so everything is read; it is never read
as "no rows". Selected rows always read their meta fresh, so the cache can only affect
which rows are selected, never their content, and new artifact directories are cache
misses that still read meta (which keeps the confirmation pass's new-member signal).
Deleting the cache file is always safe: the next tick rebuilds it.

`ready.json` is published atomically — via a temp file plus a no-clobber link, so the
first writer wins — and is skipped entirely once the waiter is gone. The waiting runner
treats an unreadable or malformed marker as not ready and keeps polling (bounded by its
periodic fallback, which never reads `ready.json`).

### Wait release telemetry {#wait-release-telemetry}

Each crossed wait barrier records how it was released and how long each segment took, in
`agent_meta.json`:

| Key                              | Meaning                                                                                                                                                                                      |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `wait_release_source`            | `startup` (resolved before parking), `ready_json` (`wait_checks` marker), `manual` (marker with `unwait: true`, i.e. TUI run-now), `runner_fallback`, or `timer` (duration/until-only waits) |
| `wait_dependencies_satisfied_at` | Epoch seconds when the last relevant dependency member finished, when known                                                                                                                  |
| `wait_release_latency_s`         | Dependency-release instant minus `wait_dependencies_satisfied_at`, clamped ≥ 0; only for `ready_json` / `runner_fallback` releases with a known satisfied time and no bead dependencies      |
| `admission_latency_s`            | `run_started_at` − `wait_completed_at`, for runs that crossed a wait barrier                                                                                                                 |
| `runner_slot_wait_s`             | `run_started_at` minus the instant the runner entered `wait_for_runner_slot`                                                                                                                 |

`wait_checks` publishes `released_by: "wait_checks"` plus `dependencies_satisfied_at`
(when known and the waiter has no bead dependencies) in `ready.json`; the runner carries
those into its own stamp. To tally release sources over recent runs:

```bash
find ~/.sase/projects/*/artifacts/ace-run -name agent_meta.json -newermt '7 days ago' \
  -exec python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("wait_release_source", "unknown"))' {} \; \
  | sort | uniq -c | sort -rn
```

A waiter whose resolution raises stays parked, is counted in `waiter_errors`, and marks
the tick `check_error` without blocking other waiters.

Markers may also carry `wait_for_beads`, emitted by `%wait(bead=<bead-id>)`.
`wait_checks` reads the waiting agent's project bead store once per cycle and releases
the marker only when every named bead is closed as well as every agent or artifact
dependency being satisfied. Missing beads, unavailable stores, and read failures
deliberately fail closed and leave the agent parked; sase's TUI run-now action remains
the manual escape hatch. While live bead waits are outstanding, `sidecar_auto_sync`
hints their projects' `beads` role every tick — even when that role has not opted into
`auto_sync` — so the one conservative fetch/fast-forward sync policy converges it
promptly instead of a competing managed-integration refresh path. The waiting runner
also marks the same hint on a coarser ten-minute cadence as an outage backstop, in case
a job failure ever leaves the tick-driven hint unconsumed. Setting
`sdd.bead_refresh.mode: off` disables both hint paths.

A parked runner with agent dependencies stats `ready.json` every 0.5 seconds; the
60-second direct-resolution fallback cadence is unchanged.

The `agent_waits` and `sidecar_sync` routines activate on the scheduler restart
`sase update` performs. The moved jobs start with fresh per-routine state: the
`wait_checks` trigger checkpoint fires once, and `sidecar_sync` re-checks every role
once because its backoff schedule file lives in the routine state dir.

## checks (5-minute interval) {#checks-5-minute-interval}

Lower-frequency status checks:

| Job                       | Description                                                  |
| ------------------------- | ------------------------------------------------------------ |
| `bead_task_triage`        | Reconcile the one pending gate each task bead owns           |
| `plugins_required`        | Raise one `PluginsRequired` gate per project missing plugins |
| `pr_submitted_checks`     | Start PR submission status checks                            |
| `stale_running_cleanup`   | Backstop dead-process claim and proc-row cleanup             |
| `orphan_agent_scope_reap` | Reap orphaned agent scopes whose runner died                 |

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
[effective `+1` bar](../work-units/beads.md#per-type-triage-bar) of independent `+1`
reports before it earns a `TaskTriage` gate: its own task type's `triage.min_plus_ones`
(`0` for `ci`, `feature`, and `memory`; `1` for `bug`; `3` for `flake`), or
[`bead.task_triage.min_plus_ones`](../config/automation-behavior.md#bead) when the bead
is untyped or its type is not registered on this machine. A sub-threshold bead is
withheld from triage without any change to its stored status — it stays `ready` and
stays visible to `sase bead list`, `sase bead ready`, sase's TUI Beads panel, and its
bead page — and a `TaskTriage` gate already raised for a bead that later falls below the
bar is canceled (reason `task_bead_below_plus_one_threshold`) and its notification
dismissed on the job's next tick. Snoozed beads and `flag` task beads are never subject
to this bar.

A still-pending gate is skipped on later ticks, preventing repeated notifications. If a
bead leaves its gateable status or type through a launch, close, extension, or manual
retraction, the job cancels its pending gate. If a gate becomes terminal or its bundle
disappears while the bead is still gateable, the next tick replaces it, except while
that bead has an active detached launch in flight. A persistent generation counter gives
each replacement a new deterministic request ID, whether the bead kept its status or
left and came back.

After project discovery succeeds and returns a non-empty inventory, the same
reconciliation also cancels pending gates when their project leaves the active
inventory, and cancels producer-owned gates that are absent from the routine's lane
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
[TaskTriage notifications](notification-gates.md#command-backed-interaction-gates-1),
the [snooze workflow](../work-units/bead-triage.md#snoozing-a-task-bead) for what a
`BeadSnooze` gate then asks, and the
[standalone task workflow](../work-units/bead-triage.md#standalone-task-workflow) for
the human-facing lifecycle.

The `FlagTriage` gate presents the flag's key, kind, both-branch prose, `remove_when`,
both removal thresholds, its countdown, and the registry definition's description (or a
callout when no definition names the key), and offers four options. **Remove** (the
primary branch) deletes the Off branch and makes the On branch unconditional; it
collects a required `winner` choice (`enabled` or `disabled`) for the worker brief and
submits the same deduplicated `sase bead work <flag-id> --yes-to-all` proc; **Extend**
requires a reason plus a new date and release line, pushes both thresholds out, and
leaves the bead `open` so the next tick finds it is not due and cancels the gate as
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

The `orphan_agent_scope_reap` job is the five-minute backstop for agent scopes whose
runner died without sweeping (SIGKILL, OOM, or crash). It scans `sase-agent-*` scopes
under the user manager and terminates leaked processes in scopes with no live runner,
using the same spare-process selection rule as the runner-exit sweep: scopes holding a
live runner or a `systemd-run` pre-exec window, scopes younger than
[`agent_scope_teardown.reaper_min_scope_age_seconds`](../config/agents-and-runners.md#agentscopeteardown),
and scopes whose every member is a spared shared daemon (`ssh-agent`, `gpg-agent`, tmux
server, ssh ControlMaster) are left untouched. It keeps the default `always` trigger
because process death leaves no filesystem event to watch. To spot leaks by hand, run
`systemctl --user list-units 'sase-agent-*'`; to reap one pass immediately, run
`sase axe job run orphan_agent_scope_reap`.

## usage (60-second interval) {#usage-60-second-interval}

Subscription-usage collection, owned by the scheduler:

| Job             | Description                            |
| --------------- | -------------------------------------- |
| `usage_refresh` | Refresh due subscription-usage windows |

The `usage_refresh` job checks machine-local due and backoff state and probes the
admitted providers inline in the job process, under a non-proc operation ID, so periodic
collection creates no proc rows. It does not poll per agent or per project. Collection
stays gated by `llm_provider.usage_metrics.enabled`; see
[Subscription usage extension](../providers/plugins.md#subscription-usage-extension).

A scheduled tick performs a due-only refresh. A manual run — the Services-tab `r` key or
`sase axe job run usage_refresh` — performs an explicit refresh instead, still subject
to the 60-second cooldown and any `Retry-After`. A host that shares an account with
another machine can opt out per provider with
`llm_provider.usage_metrics.providers.<name>.enabled: false` in a machine overlay.

<a id="externalmirror-15-minute-interval"></a>

## external_mirror (15-minute interval) {#external_mirror-15-minute-interval}

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

The [`external_mirror.issues.filters`](../config/automation-behavior.md#externalmirror)
surface (empty by default) excludes tracker issues from mirroring by author, label,
title, or state; a non-empty filter means the bead list is not a strict superset of the
issue list. Filters gate creation only — clearing a filter re-examines issues the filter
excluded, but a filter never deletes a bead that already exists. Records a filter drops
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

See [Builtin `external_pr_mirror`](scheduler-jobs.md#builtin-external_pr_mirror) below
for that job's own behavior, including where its cursor and backoff state live.

## comments (1-minute interval) {#comments-1-minute-interval}

Comment polling:

| Job              | Description                   |
| ---------------- | ----------------------------- |
| `comment_checks` | Start critique comment checks |

## Related

- [Scheduler](scheduler.md)
- [Scheduler configuration](scheduler-configuration.md)
- [Scheduler housekeeping](scheduler-housekeeping.md)
- [Schedule recurring work](../../guides/schedule-recurring-work.md)

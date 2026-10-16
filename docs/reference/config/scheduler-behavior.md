---
title: "Scheduler configuration behavior"
description: "AXE scheduler settings and their runtime behavior."
---

# Scheduler configuration behavior

AXE scheduler settings and their runtime behavior.

## axe

Configures the scheduler's routine-based automation. The scheduler architecture uses an
orchestrator that spawns multiple routines, each running a set of jobs on a fixed
interval. Defaults are provided by `src/sase/default_config.yml`. The config section
keeps its historical `axe` name.

The YAML below is an abridged illustration of the shipped defaults, not the whole file:
it shows the shape of a lane and a job and omits some lanes and jobs entirely. See
[AXE Automation](../../axe.md#default-routines) for the complete lane-by-lane inventory,
and `src/sase/default_config.yml` for the literal defaults.

```yaml
axe:
  max_hook_runners: 3 # concurrent hook runners (default: 3)
  max_agent_runners: 3 # concurrent agent runners (default: 3)
  zombie_timeout_seconds: 7200 # seconds (default: 7200 = 2 hours)
  query: "" # query filter for Patches (default: all)
  job_script_dirs: [] # additional directories to search for job scripts
  routines:
    hooks:
      description: |-
        Fast lane that advances hook, mentor, and workflow lifecycle state every few seconds

        Runs every five seconds with a 90-second per-job timeout so completed work is noticed and new work starts
        promptly. Put latency-sensitive Patch lifecycle reconciliation here; slower remote polling, wait
        coordination, and maintenance belong in the other lanes.
      interval: 5
      job_timeout: "90s"
      jobs:
        - name: hook_checks
          script: sase_job_hook_checks
          trigger:
            provider: fs
            max_quiet: "120s"
            paths:
              - path: projects
                glob: "*/*.sase"
              - path: projects
                glob: "*/*.gp"
          description: |-
            Complete finished hooks and start stale ones, with zombie detection

            Scans hook entries on every matching Patch, records completed process results, and starts stale hooks
            when a runner slot is free. Honors max_hook_runners across the tick; stale fix-hook suffixes older than
            zombie_timeout_seconds become ZOMBIE, while terminal Patches may finish hooks but cannot start new ones.
        - name: mentor_checks
          script: sase_job_mentor_checks
          trigger:
            provider: fs
            max_quiet: "120s"
            paths:
              - path: projects
                glob: "*/*.sase"
              - path: projects
                glob: "*/*.gp"
          description: |-
            Start mentor workflows once all hook prerequisites are met

            Reconciles running mentors, stops mentors left behind by older commits, adds matching mentor profiles, and
            launches ready profiles after their hooks finish. Mentor launches share max_agent_runners with other agent
            workflows, and review-ineligible or terminal Patches are skipped.
        - name: workflow_checks
          script: sase_job_workflow_checks
          trigger:
            provider: fs
            max_quiet: "120s"
            paths:
              - path: projects
                glob: "*/*.sase"
              - path: projects
                glob: "*/*.gp"
          description: |-
            Complete finished CRS/fix-hook workflows and start stale ones

            Reads workflow state from every matching Patch, records results for finished CRS and fix-hook agents,
            and launches stale workflows. New workflows share max_agent_runners and the current tick's agent-launch
            budget with mentors, so a full runner pool defers work instead of queueing it.
        - name: pending_checks_poll
          script: sase_job_pending_checks_poll
          trigger:
            provider: fs
            max_quiet: "120s"
            paths:
              - path: checks
                glob: "*/*.txt"
          description: |-
            Poll background is_cl_submitted and critique_comments checks for results

            Scans the pending-check directory once per tick, applies completed results to matching Patches, and
            reaps output files orphaned by killed or crashed checks. This job only consumes background results;
            pr_submitted_checks and comment_checks launch the remote checks.
        - name: comment_zombie_checks
          script: sase_job_comment_zombie_checks
          trigger:
            provider: fs
            max_quiet: "120s"
            paths:
              - path: projects
                glob: "*/*.sase"
              - path: projects
                glob: "*/*.gp"
          description: |-
            Mark comment threads older than zombie_timeout as ZOMBIE

            Examines comment-entry suffix timestamps on matching Patches and writes a ZOMBIE suffix when an entry
            exceeds zombie_timeout_seconds. It performs no remote comment fetch; comment_checks starts those checks and
            pending_checks_poll applies their results.
        - name: suffix_transforms
          script: sase_job_suffix_transforms
          trigger:
            provider: fs
            max_quiet: "120s"
            paths:
              - path: projects
                glob: "*/*.sase"
              - path: projects
                glob: "*/*.gp"
          description: |-
            Strip stale suffixes from older proposals and update mail-readiness markers

            Normalizes matching Patches in place by converting old proposal markers from !: to ~:, removing error
            markers from superseded stitches, and acknowledging attention markers on terminal statuses. It only
            repairs stored suffix state and never launches hooks or agents.
        - name: orphan_cleanup
          script: sase_job_orphan_cleanup
          trigger:
            provider: fs
            max_quiet: "120s"
            paths:
              - path: projects
                glob: "*/*.sase"
              - path: projects
                glob: "*/*.gp"
          description: |-
            Release workspace claims orphaned by reverted PRs with dead PIDs

            Reads all Patches and workspace claims, regardless of the axe query, then releases unpinned claims tied
            to Reverted Patches when their owning PID is absent or dead. Live claims and pinned workspaces are left
            untouched.
        # stale_running_cleanup keeps the default `always` trigger: dead-PID detection
        # has no filesystem proxy to watch.
        - name: stale_running_cleanup
          script: sase_job_stale_running_cleanup
          description: |-
            Release workspace claims and terminalize proc rows held by dead processes

            Walks every project, including disabled projects, and releases unpinned workspace claims whose owning
            process has exited. A pinned held claim is preserved while its agent artifacts still exist; this fast-lane
            placement frees ordinary dead claims within seconds. It also terminalizes active proc rows whose supervisor
            exited without reporting.
    waits:
      description: |-
        Reconcile bead claims and flush orphaned epic launches

        Runs every ten seconds so short-lived bead claims are reconciled quickly. Agent dependency resolution
        lives in the agent_waits lane and sidecar syncing in the sidecar_sync lane; Patch lifecycle checks and
        general cleanup belong in their dedicated lanes.
      interval: 10
      jobs:
        - name: bead_claim_checks
          script: sase_job_bead_claim_checks
          trigger:
            provider: fs
            max_quiet: "120s"
            paths:
              - path: projects
                glob: "*/artifacts/.ace_refresh_pulse"
          description: |-
            Acquire missing bead claims for live pre-launch agents and release claims held by dead ones

            Scans pre-launch agent artifacts, backfills a missing claim for a live waiting agent, and releases a
            claimed bead when its unpromoted owner has died. Reconciled dead records are tombstoned so later ticks avoid
            reopening their stores, while a failed project read is retried safely.
        - name: epic_launch_flush
          script: sase_job_epic_launch_flush
          run_every: "30s"
          description: |-
            Flush planner completion notifications orphaned by an unsettled epic launch

            Preserves deferrals while a matching detached epic-launch task is active, flushes unowned deferrals after
            a 90-second grace period with a resume command, and reaps unclaimed settle markers after one hour.
    agent_waits:
      description: |-
        Resolve agent wait dependencies within seconds of completion

        Runs every two seconds so waiting agents resume promptly once a dependency finishes. Only agent
        dependency resolution belongs here; bead-claim work lives in waits and sidecar syncing in sidecar_sync.
      interval: 2
      job_timeout: "2m"
      jobs:
        - name: wait_checks
          script: sase_job_wait_checks
          trigger:
            provider: fs
            max_quiet: "120s"
            paths:
              - path: projects
                glob: "*/artifacts/.ace_refresh_pulse"
          description: |-
            Resolve agent wait dependencies and write ready.json when satisfied

            Walks waiting markers across projects, resolves only live waiters (provably dead runners are skipped and
            counted in the dead-waiter backlog counter), and resolves named-agent, artifact, and closed-bead
            dependencies from filesystem agent metadata and canonical bead state. It writes ready.json only after
            every dependency is satisfied; invalid or already-ready markers are skipped without blocking other agents.
    sidecar_sync:
      description: |-
        Fetch and fast-forward opted-in primary sidecar clones

        Runs every thirty seconds so sidecar clones converge without delaying agent wait resolution. Only the
        sidecar_auto_sync job belongs here; agent dependency resolution lives in agent_waits.
      interval: 30
      jobs:
        - name: sidecar_auto_sync
          script: sase_job_sidecar_auto_sync
          timeout: "2m"
          description: |-
            Fetch and fast-forward opted-in primary sidecar clones (plans, beads, research, custom)

            Scans every enabled project's auto_sync sidecar roles, syncing a role immediately when a publisher left a
            pending hint and otherwise backstopping it at most every five minutes. Projects with a live agent waiting
            on bead completion also hint the beads role every tick, even when that role has not opted into auto_sync,
            so waiters unblock promptly instead of relying on the runner's coarser fallback. Only a clean, attached,
            non-diverged clone with a matching remote is fetched and fast-forwarded; dirty, detached, diverged,
            mismatched, missing, or busy clones are left untouched and reported. Bounded work budget and persistent
            per-role backoff keep one unhealthy clone from stalling the rest. After a beads-role refresh, touches
            the project's completion pulse so agent_waits re-evaluates bead waits on its next 2 s tick.
    checks:
      description: |-
        Poll slower PR-submission and workspace-claim checks on a five-minute cadence

        Runs every five minutes for checks that can tolerate delay or may touch remote PR state, reducing needless
        polling while retaining a cleanup backstop. Fast hook progression, minute-level comments, and hourly
        maintenance deliberately live elsewhere.
      interval: 300
      jobs:
        - name: bead_task_triage
          script: sase_job_bead_task_triage
          timeout: "2m"
          description: |-
            Raise one human gate for each ready or snoozed task bead, and for each due flag-typed task bead

            Scans enabled projects every five minutes and gives every live task bead exactly one pending
            gate: a TaskTriage gate while a task bead is ready and has at least its effective +1 bar in reports
            (its own task type's triage.min_plus_ones, else the global bead.task_triage.min_plus_ones), a BeadSnooze
            wake gate while it is snoozed, and a FlagTriage gate once a flag-typed task bead's date and release removal
            thresholds have both passed. A ready task bead below the +1 bar is withheld from
            triage without changing its stored status, and a gate already raised for a bead that falls below the
            bar is canceled and its notification dismissed. Deterministic gate generations in lane state prevent
            duplicate notifications, a gate of the wrong kind is replaced when its bead's status or due-ness
            changes, and a snoozed bead's notification is re-snoozed to its wake time if it ever drifts. Gates are
            canceled when their beads leave those states, while answered or missing gates can be regenerated
            safely if work remains. Gates stranded by removed projects or forgotten lane state are swept without
            touching projects that are only temporarily unreadable. A gateable bead is deferred while a detached
            launch is still in flight or a live agent is working the bead, and a pending gate is canceled when a
            live agent owns the bead.
        - name: plugins_required
          script: sase_job_plugins_required
          timeout: "2m"
          description: |-
            Raise one human gate per project whose required plugins are missing

            Scans enabled projects every five minutes and compares each project's plugins.required list against
            installed distributions. A project with a missing or version-mismatched required set gets exactly one
            pending PluginsRequired gate offering Install and Dismiss. Install performs one combined install for
            all missing names from the answering surface, sharing a bounded public-index probe and resolving each
            plugin from the index unless public PyPI returns a definitive 404, in which case that plugin uses git.
            The gate stays pending when planning or the uv mutation fails, including when sase is not a uv tool
            install. Dismiss records the decision so the same missing set is not re-offered until it changes. The
            job cancels the gate when the set becomes satisfied. Deterministic generations in lane state prevent
            duplicate notifications. Agent and non-interactive contexts still fail closed and never auto-install.
        - name: pr_submitted_checks
          script: sase_job_pr_submitted_checks
          description: |-
            Start background is_cl_submitted checks for leaf PRs with a submitted parent

            Applies the axe query, finds eligible leaf Patches with PR URLs, and launches non-blocking submission
            checks whose results are collected by pending_checks_poll. A five-minute sync cache suppresses duplicate
            remote work, except that the first cycle checks eligible leaves immediately.
        - name: stale_running_cleanup
          script: sase_job_stale_running_cleanup
          description: |-
            Backstop release of workspace claims and proc rows held by dead processes

            Runs the same all-project dead-process reconciliation as the hooks-lane cleanup, including conservative
            handling of pinned claims with agent artifacts and terminalization of orphaned active proc rows. This
            five-minute placement still frees stale workspace claims and proc rows if the fast hooks lane is disabled,
            restarting, or repeatedly failing.
        # orphan_agent_scope_reap keeps the default `always` trigger: process death
        # leaves no filesystem event to watch, so no fs proxy exists - the same
        # rationale as stale_running_cleanup.
        - name: orphan_agent_scope_reap
          script: sase_job_orphan_agent_scope_reap
          timeout: "2m"
          description: |-
            Reap orphaned agent scopes whose runner died without cleaning up

            Scans sase-agent scopes under the user manager every five minutes and terminates leaked processes in
            scopes with no live runner (SIGKILL, OOM, or crash), using the same spare-process selection rule as the
            runner-exit sweep. Scopes holding a live runner or systemd-run window, scopes younger than
            agent_scope_teardown.reaper_min_scope_age_seconds, and scopes whose every member is a spared shared
            daemon (ssh-agent, gpg-agent, tmux server, ssh ControlMaster) are left untouched. Disabled entirely when
            agent_scope_teardown.enabled is false.
    comments:
      description: |-
        Start background critique-comment checks for mailed PRs every minute

        Runs every minute so reviewer feedback reaches active Patches promptly without polling on every hooks tick.
        Only remote comment-check launches belong here; pending result collection and zombie marking remain in the
        faster hooks lane.
      interval: 60
      jobs:
        - name: comment_checks
          script: sase_job_comment_checks
          description: |-
            Start background critique_comments checks for all mailed PRs

            Applies the axe query and starts non-blocking critique_comments checks for mailed Patches that have an
            available workspace, then records a comment-cycle summary. The routine's one-minute interval is the
            polling throttle; pending_checks_poll later consumes each background result.
    housekeeping:
      description: |-
        Run hourly error digests, notification compaction, artifact previews, and cleanup

        Runs once an hour because notification batching, live-inbox bounding, bounded scratch reclamation,
        artifact/run-retention previews, and stale-backlog cleanup are useful but not latency-sensitive. Put
        durable maintenance that may scan substantial local state here, not lifecycle, dependency, or remote polling
        work.
      interval: 3600
      jobs:
        - name: error_digest
          script: sase_job_error_digest
          description: |-
            Send a notification digest of errors from the last hour

            Reads the AXE error log and the last successful digest timestamp, then notifies only about newer errors
            within the rolling one-hour window. The checkpoint advances to the newest notified timestamp, preventing
            duplicate digests while leaving unsent errors eligible after a notification failure.
        - name: managed_tmp_reap
          script: sase_job_managed_tmp_reap
          description: |-
            Prune stale scratch under the managed SASE temp root

            Removes old children from managed-temp buckets using workload-specific age limits, without following
            symlinks or deleting the stable bucket directories. Launched agents default TMPDIR/TMP/TEMP,
            CARGO_TARGET_DIR, and CARGO_BUILD_BUILD_DIR into managed buckets, and runners remove their own
            launch-assigned scratch at exit when no live process still uses it. The reaper can also prune aged large
            build output early when the managed root exceeds its size target or the filesystem falls below the
            free-space floor; pressure pruning waits for the configured minimum age (12h by default), or 1h once the
            free-space floor is breached, while preserving generic agent scratch, handoff data, unknown buckets, and
            build trees with fresh descendants. Each pass removes at most 2,000 entries and de-indexes deleted
            agent-artifact directories, so a neglected root converges without blocking interactive commands.
        - name: proc_runtime_sweep
          script: sase_job_proc_runtime_sweep
          description: |-
            Prune stale rowless proc runtime directories

            Removes only canonical proc runtime directories that no longer have a durable proc row, are older than
            the configured proc runtime orphan horizon, and are direct non-symlink children of ~/.sase/procs/runtime.
            The Rust owner rechecks the proc store under its lock before deletion so concurrent reservations are
            preserved. Runtime directories for proc rows actually pruned by retention are deleted immediately by the
            proc store path; this job handles historical orphans over a bounded per-pass budget.
        - name: disk_pressure
          script: sase_job_disk_pressure
          timeout: "5m"
          description: |-
            React when SASE's filesystem crosses disk-pressure thresholds

            Checks proportional free-space thresholds, logs and notifies the largest SASE disk owners, then runs
            unattended owner-safe cleanup passes early. Managed temp and proc runtime sweeps may apply because their
            owners encode deletion policy. Artifact run directories, backups, and unowned Cargo-shaped strays are
            reported for human action and are never deleted by this job.
        - name: bead_stale_cleanup
          script: sase_job_bead_stale_cleanup
          timeout: "2m"
          description: |-
            Sweep stale sub-threshold ready task beads into one BeadStaleCleanup gate

            Reads every enabled project's ready task beads and offers those that have sat below
            their effective +1 bar (their own task type's triage.min_plus_ones, else the global
            bead.task_triage.min_plus_ones) for bead.task_triage.stale_after_days once at least
            bead.task_triage.stale_cleanup_min_beads such beads exist. One pending gate at a time
            carries at most 50 beads, oldest first; a larger backlog is reported in omitted_count and
            offered on later ticks. An unchanged roster leaves the pending gate alone. The gate is
            canceled when the backlog drops below the bar.
        - name: artifact_run_prune
          script: sase_job_artifact_run_prune
          timeout: "5m"
          description: |-
            Preview old ace-run directories and empty shard cleanup

            Plans whole-run ace-run retention without deleting anything. The preview keeps the newest
            artifacts.retention.keep_recent_run_months calendar months whole, protects runs referenced by
            artifact files, text refs, agent names, and non-closed beads, and reports empty month/day shards
            outside sase's TUI startup watch window. When unchanged candidates or protection problems remain, it
            upserts one deduplicated Axe report notification that names the preview command. Artifact-run
            deletion is currently preview-only.
```

**Top-level fields:**

[Generated reference for `axe`](scheduler.md#axe)

**Routine fields** (per entry under `routines`):

[Generated reference for `axe`](scheduler.md#axe)

**Job fields** (per entry under `jobs`):

[Generated reference for `axe`](scheduler.md#axe)

Both `description` fields use one grammar: a non-blank summary line of at most 100
characters, then — if anything follows — a blank line, then a free-form body, with the
whole string capped at 2000 characters. Violations produce the
`description_summary_blank`, `description_summary_too_long`,
`description_body_separator_required`, and `description_too_long` diagnostics. See
[AXE — Description Grammar](../../axe.md#description-grammar) for the full contract, the
authoring style guide, and the YAML literal-block form.

Routines were formerly called lumberjacks and jobs were called chops. The old spellings
remain accepted, schema-valid input aliases but are marked deprecated: `lumberjacks` for
`routines`, `chops` for `jobs`, `chop_timeout` for `job_timeout`, `chop_script_dirs` for
`job_script_dirs`, and `lumberjack_log_max_bytes`,
`lumberjack_log_temp_max_age_seconds`, `lumberjack_restart_backoff_max_seconds`, and
`verbose_lumberjack_diagnostics` for their `routine_*` counterparts. New configuration
should use the canonical keys. `sase config show` prints the effective AXE block with
the canonical names. Legacy `sase_chop_*` executables still exist beside the
`sase_job_*` entrypoints. See
[AXE compatibility aliases](../../axe.md#compatibility-aliases) for the matching CLI,
environment, and artifact-reference aliases.

All jobs are scripts. Exact-name resolution checks `job_script_dirs`, then the running
interpreter's bin directory, then `$PATH`. Invalid fields, duplicate identities,
non-positive intervals, and invalid durations fail config loading with a dotted config
path and source-layer diagnostic. `agent:` and `macro:` are rejected with a migration
message.

Environment values resolve at dispatch time. Use a literal for non-secret data or
`{env: NAME}`, `{file: path}`, and `{pass: entry}` references for secrets. Routine-level
`env` is inherited by every job, then a job's own `env` overrides matching names.

The built-in `wait_checks` job writes `ready.json` only after named `%wait` dependencies
complete successfully. Failed, killed, crashed, still-running, malformed, or missing
`done.json` artifacts do not satisfy the dependency.

Map form is the composable form. Higher-priority config layers patch matching fields by
key, and per-field source provenance is shown by the verbose job inventory:

```yaml
axe:
  routines:
    docs:
      description:
        Refresh project documentation when repositories accumulate meaningful changes
      interval: 60
      env:
        API_TOKEN: { env: DOCS_API_TOKEN }
      jobs:
        refresh_docs:
          description: Refresh documentation after meaningful repository drift
          script: sase_job_refresh_docs
          run_every: "30m"
          trigger:
            git.commits_since:
              project: "{target.name}"
              threshold: 10
              checkpoint: on_action_success
          for_each:
            source: projects
            vcs: [git, gh]
        packaged_but_disabled:
          description: Retain a packaged documentation check without running it
          enabled: false
```

`for_each` produces stable identities such as `refresh_docs[sase-core]`. Each instance
has independent scheduling, history, checkpoints, and once-per state. Target data is
available in the context JSON under `target` and through `SASE_JOB_TARGET_KEY` /
`SASE_JOB_TARGET_<FIELD>`. Literal target rows may include `overrides:` for per-target
job fields such as `run_every` and trigger thresholds.

`inhibit_if` accepts keyed `patch`, `agent_hood`, `agent_clan`, and `agent_runners`
providers. The legacy `changespec` key remains accepted as an alias. The clan provider
requires a case-sensitive `name_prefix` and checks canonical clan metadata for active
agents, including waiting members; it never infers clans from dotted names.
`agent_runners.max` defaults to `0` and inhibits while more than that many participating
agent lanes are occupied, a participating-lane count distinct from the weighted
`%queue(capacity=N)` admission budget. Weighted capacity is tracked separately by the
runner-capacity snapshot and sase's TUI header. A `STARTING` agent has not yet been
admitted and does not count; an agent parked on a question has yielded its capacity and
does not count. `trigger` accepts `always`, `git.commits_since`, or `fs`; the git
provider requires `project` and `threshold`, and its checkpoint policy is
`on_observation`, `on_action_accepted`, or `on_action_success`. The `fs` provider
requires `paths` (bare path strings or `{path, glob}` objects, stat'd shallowly — no
recursion, no content reads) and a positive `max_quiet` duration, fires when its
computed state token changes or `max_quiet` elapses since the last fire, always uses
`on_observation` checkpoint semantics, and fails open (fires without advancing its
checkpoint) on an unreadable path. See
[AXE — Triggers, Guards, Dedupe, and Targets](../../axe.md#triggers-guards-dedupe-and-targets)
for the full contract. Skips are recorded with reasons. Manual runs bypass the trigger
but honor guards; with `agent_runners`, a manual run while participating lanes are
occupied skips unless `sase axe job run -f/--force` is used. `once_per` can be a key
template string or an object with `key` and bounded `capacity`; proposal-supplied
`dedupe_key` values take precedence. `dedupe_key` is durable work identity, not a retry
clock: it stays reserved after a successful no-op launch, so jobs whose work can go
stale between scans should recheck eligibility with a proposal `%if::` predicate (see
[Structured Results and Launch Proposals](../../axe.md#structured-results-and-launch-proposals))
instead of folding a repository revision into the key. When dedupe removes a proposal
from a `wait_on` chain, AXE walks through the skipped dependencies to the nearest
earlier proposal that survives filtering. If none survives, AXE removes the wait.
Proposal previews expose the resulting `wait_on` value and explain a relink in
`dedupe_reason`.

The builtin `sase_job_refresh_docs` emits an update proposal plus a polish proposal that
waits for the update. It uses the target source's `workspace`, while cadence and commit
thresholds stay declarative in configuration. Its default prompts are strictly
documentation-scoped and tell agents to report suspected code bugs instead of fixing
them. The defaults can be replaced with non-blank `vars.prompt` and `vars.polish_prompt`
strings; operators are responsible for the scoping language in replacement prompts. See
[Axe structured results and launch proposals](../../axe.md#structured-results-and-launch-proposals)
for the result document, proposal fields, lifecycle statuses, and debugging commands.

Every job entry must carry a `description` following the
[description grammar](../../axe.md#description-grammar). Bare-string list entries are no
longer valid because they cannot carry one; use map form or object-form list entries:

```yaml
jobs:
  # Object-form list entry
  - name: hook_checks
    script: sase_job_hook_checks
    description: Check for completed or failed hooks
  - name: custom_job
    script: my_full_executable_name
    description: Run custom analysis
    run_every: "1h30m"
    env:
      MY_API_KEY: { env: MY_API_KEY }
```

CLI flags on `sase scheduler run` override `max_hook_runners`, `max_agent_runners`,
`zombie_timeout_seconds`, and `query` for a single run (see
[CLI Flags](../../reference/cli/scheduler.md#sase-scheduler-run)).

Source: `src/sase/axe/config.py`, `src/sase/default_config.yml`

## Related

- [Scheduler configuration](scheduler.md) — generated scheduler keys and defaults.
- [Scheduler and service host](../../axe.md) — scheduler operation.

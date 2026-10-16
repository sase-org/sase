---
title: Scheduler configuration
description: Global scheduler settings and the fields that configure routines.
---

# Scheduler configuration

This page describes global scheduler settings and routine configuration.

## Configuration

Axe is configured in `sase.yml` under the `axe:` section. Keys, types, and defaults are
on the generated [scheduler configuration](../config/scheduler.md) page; behavior notes
are on [AXE configuration behavior](../config/scheduler-behavior.md).

<a id="description-grammar"></a> <a id="diagnostics"></a>
<a id="authoring-style-guide"></a> Moved to
[Scheduler description grammar](scheduler-description-grammar.md#description-grammar).
<a id="script-jobs"></a> <a id="structured-results-and-launch-proposals"></a>
<a id="publishing-a-report-a-notification-can-open"></a>
<a id="triggers-guards-dedupe-and-targets"></a> <a id="builtin-externalprmirror"></a>
<a id="builtin-refreshdocs"></a> Moved to
[Scheduler jobs](scheduler-jobs.md#script-jobs). <a id="manual-job-runs"></a> Moved to
[Scheduler jobs](scheduler-jobs.md#manual-job-runs). <a id="job-run-history"></a> Moved
to [Scheduler jobs](scheduler-jobs.md#job-run-history). <a id="services-tab-views"></a>
Moved to [Scheduler jobs](scheduler-jobs.md#services-tab-views).
<a id="job-agent-registry"></a> Moved to
[Scheduler jobs](scheduler-jobs.md#job-agent-registry).

## Global Settings {#global-settings}

The `query` setting uses the same Patch query language as sase's TUI. CLI flags on
`sase scheduler run` and `sase axe routine run` override the configured query, runner
limits, and zombie timeout for that process.

## Routine Configuration {#routine-configuration}

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
summary/body grammar in
[Description Grammar](scheduler-description-grammar.md#description-grammar).

### Routine Fields {#routine-fields}

Routine field names, types, and defaults are on the generated
[scheduler configuration](../config/scheduler.md) page.

`wait_runners` applies only to agents emitted through a script job's
`proposed_launches`; it does not gate mentor, hook, or CRS workflow launchers. The
runner prepends it to each proposed prompt as `%queue(capacity=N)` unless the prompt
already authors its own `%queue` capacity, so it follows the
[per-launch capacity budget](../macros/directive-launch.md#agent-names-waits-and-queue-admission)
rules: the agent starts when the occupied weighted load plus its own weight fits within
`N`, and `1` makes a default-weight lane agent run alone. `N` must be at least `1`;
`wait_runners: 0` produces a `%queue(capacity=0)` that is rejected at launch. When a job
proposes a clan, every member carries the budget and waits independently, so a low
budget can serialize the clan.

### Job Fields {#job-fields}

Job field names, types, and defaults are on the generated
[scheduler configuration](../config/scheduler.md) page. `inhibit_if.changespec` remains
accepted as an alias of `inhibit_if.patch`.

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
diagnostics. Scheduled agent work must originate from a script's structured launch
proposals; `agent:` and `macro:` job fields are rejected. See
[Automation migration notes](../upgrading/automation.md#rejected-agent-and-macro-job-fields).

## Related

- [Scheduler description grammar](scheduler-description-grammar.md)
- [Scheduler jobs](scheduler-jobs.md)
- [Scheduler](scheduler.md)
- [Scheduler configuration keys](../config/scheduler.md)
- [Automation migration notes](../upgrading/automation.md)

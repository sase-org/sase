---
title: Scheduler configuration
description: Global scheduler settings and the fields used to configure routines.
---

# Scheduler configuration

This page describes global scheduler settings and routine configuration.

## Configuration

Axe is configured in `sase.yml` under the `axe:` section. See the
[AXE configuration behavior](../config/scheduler-behavior.md) and generated
[scheduler configuration keys](../config/scheduler.md).

<a id="global-settings"></a> Moved to [Scheduler configuration](#global-settings).
<a id="routine-configuration"></a> <a id="routine-fields"></a> <a id="job-fields"></a>
Moved to [Scheduler configuration](#routine-configuration).
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

## Global Settings

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

## Routine Configuration

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

### Routine Fields

| Field          | Type                   | Required | Description                                                                                                                              |
| -------------- | ---------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `description`  | `str`                  | yes      | Summary line, then a blank line, then an optional body (see [Description Grammar](scheduler-description-grammar.md#description-grammar)) |
| `interval`     | `int`                  | no       | Seconds between job polling cycles; defaults to `1`                                                                                      |
| `job_timeout`  | `str \| null`          | no       | Default positive compound duration for jobs in this routine                                                                              |
| `wait_runners` | `int \| null`          | no       | Per-launch capacity budget for lane agents, emitted as `%queue(capacity=N)`; omitting it uses only the global capacity budget            |
| `env`          | `dict[str, env-value]` | no       | Values inherited by every job; individual job env wins                                                                                   |
| `jobs`         | list or map            | no       | Composable job definitions                                                                                                               |

`wait_runners` applies only to agents emitted through a script job's
`proposed_launches`; it does not gate mentor, hook, or CRS workflow launchers. The
runner prepends it to each proposed prompt as `%queue(capacity=N)` unless the prompt
already authors its own `%queue` capacity, so it follows the
[per-launch capacity budget](../../macros.md#agent-names-waits-and-queue-admission)
rules: the agent starts when the occupied weighted load plus its own weight fits within
`N`, and `1` makes a default-weight lane agent run alone. `N` must be at least `1`;
`wait_runners: 0` produces a `%queue(capacity=0)` that is rejected at launch. When a job
proposes a clan, every member carries the budget and waits independently, so a low
budget can serialize the clan.

### Job Fields

| Field         | Type                   | Required  | Description                                                                                                                              |
| ------------- | ---------------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `name`        | `str`                  | list only | Job identity in object-list form; map form uses the mapping key                                                                          |
| `description` | `str`                  | yes       | Summary line, then a blank line, then an optional body (see [Description Grammar](scheduler-description-grammar.md#description-grammar)) |
| `script`      | `str \| null`          | no        | Exact executable name; defaults to the job identity                                                                                      |
| `enabled`     | `bool`                 | no        | Soft-disable a keyed entry without deleting the packaged/base configuration                                                              |
| `run_every`   | `str \| null`          | no        | Positive compound duration (e.g., `"5m"`, `"1h30m"`, `"1d"`)                                                                             |
| `timeout`     | `str \| null`          | no        | Per-job timeout duration (overrides the routine's `job_timeout`)                                                                         |
| `env`         | `dict[str, env-value]` | no        | Values merged over routine env; literals or `{env:}`, `{file:}`, `{pass:}` refs                                                          |
| `inhibit_if`  | list or map            | no        | `patch` / `agent_hood` / `agent_clan` / `agent_runners` guards evaluated before the script; `changespec` is a legacy alias               |
| `trigger`     | string or map          | no        | `always`, `git.commits_since`, or `fs`; scheduled runs fire only when it accepts                                                         |
| `once_per`    | string or object       | no        | Bounded per-proposal dedupe-key template                                                                                                 |
| `for_each`    | list or source         | no        | Literal target objects or `source: projects`, expanded to stable per-target instances                                                    |
| `vars`        | `dict`                 | no        | Non-secret configuration copied into the script context                                                                                  |

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
diagnostics. Legacy `agent:` and `macro:` job fields are rejected: scheduled agent work
must originate from a script's structured launch proposals.

## Related

- [Scheduler description grammar](scheduler-description-grammar.md)
- [Scheduler jobs](scheduler-jobs.md)
- [Scheduler](scheduler.md)

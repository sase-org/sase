---
title: Schedule recurring work
description: Run a check on a schedule with the scheduler and confirm each run.
---

# Schedule recurring work

This guide puts a repeated check on a schedule: a routine that ticks on an interval and
a job script that does the work. It assumes the check already exists as an executable
script; if the work needs a person to decide each time, keep it as a gate instead.

## Before you start

You need a checkout where `sase` runs and a script the scheduler can find through the
configured job script directories. Confirm the scheduler is running first:

```bash
sase scheduler status
```

Start it when the status says otherwise; nothing scheduled runs while it is stopped.

## 1. Add a routine and a job

Declare the lane and its cadence in the configuration file under the scheduler section.
Every routine and every job needs a one-line description of what it owns:

```yaml
axe:
  routines:
    nightly_checks:
      description: |-
        Run inexpensive project checks once an hour
      interval: 3600
      jobs:
        lint_scan:
          description: |-
            Scan the tree for new lint findings

            Runs the fast linter and proposes a fix agent when findings appear.
          run_every: "1h"
```

A job originates scheduled agent work only through its script's structured launch
proposals; prompts embedded in configuration are rejected. See the scheduler reference
for timeouts, triggers, and per-target expansion.

## 2. Run the job once by hand

Execute the job in the foreground and preview what it would launch before it runs on its
own:

```bash
sase axe job run lint_scan -n
sase axe job run lint_scan
```

The preview run prints the validated proposals without launching agents. The real run
records history under the routine so the next scheduled tick continues from it.

## 3. Confirm the schedule holds

List the configured jobs and re-check the scheduler after one interval has passed:

```bash
sase axe job list
sase scheduler status
```

The job appears with its routine and cadence, and its run history shows the manual run
followed by scheduled ones.

## If it goes wrong

A job missing from the list usually means its script is not discoverable or its
configuration failed validation: run `sase axe job doctor` and fix the reported path.
For a run that never starts, see [Unstick a queued agent](unstick-queued-agent.md).

## Related

- [Scheduler](../axe.md) — routines, jobs, triggers, and every configuration field.
- [Automation and human checkpoints](../concepts/automation.md) — why recurring work
  stays automatic and decisions stay reviewable.

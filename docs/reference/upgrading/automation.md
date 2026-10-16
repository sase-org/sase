---
title: Automation migration notes
description: Upgrade notes for scheduler naming, monitor hand-off, and gate contracts.
---

# Automation migration notes

This page records automation changes an upgrading reader needs. Newest notes first.
Current behavior lives on the [automation](../automation/index.md) pages.

## Neutral gate bundles and per-option input

New producers write schema-v3 neutral gate bundles. Readers still resolve in-flight
plan, question, launch, and HITL request directories from earlier layouts, then fall
back to those trees. New producers do not dual-write the old trees.

Upgrade `sase-core` first so every surface has indexed turn lookup and acceptance
policy. Then upgrade the SASE Python package, sase's TUI, and mobile clients against
that binding, and finally Telegram so its receiver submits answers through the same
supervised proc path. In-flight gates from the earlier layout still finish through
`response.json`.

`--input @file.json` and the shared `input` / `input_data` fields remain accepted for
bundles that predate per-option submission. New answers submit `option_inputs`.
`/sase_plan` still creates a `PLAN` turn for those earlier plans alongside `TALE` and
`EPIC`.

See [Command-backed interaction gates](../automation/notification-gates.md).

## Monitor hand-off is `sase pipe`

A successor used to be obtained by monitoring a no-op command:

```bash
sase monitor start -s SLEEPING -S SLEPT -r '...' -n '<the real prompt>' -- sleep 1
```

Use `sase pipe` for a hand-off instead. See
[Monitor operations](../automation/monitor-operations.md).

`sase monitor start --lane` remains accepted as an alias of `--agent`.

## OOM in a SASE scope

SASE scopes set `OOMPolicy=continue`, so one OOM-killed process does not stop the whole
scope. systemd's default `OOMPolicy=stop` used to SIGTERM every agent launched from the
same terminal or tmux pane cgroup. See [Scheduler](../automation/scheduler.md).

## Scheduler lifecycle journal

New `~/.sase/axe/lifecycle.jsonl` records omit the retired desired-state marker. Readers
tolerate old entries that still carry the field.

## Rejected `agent:` and `macro:` job fields

Scheduled agent work must originate from a script's structured launch proposals.
`agent:` and `macro:` job fields in configuration are rejected. See
[Scheduler configuration](../automation/scheduler-configuration.md).

## Scheduler routine and job names

Current commands, configuration, examples, and public JSON use routine/job terms. Older
spellings remain accepted as compatibility aliases:

| Older spelling                                                    | Current spelling                                       | Notes                                                                    |
| ----------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------ |
| `sase axe lumberjack ...`                                         | `sase axe routine ...`                                 | Hidden CLI alias; completions and help advertise `routine`.              |
| `sase axe chop ...`                                               | `sase axe job ...`                                     | Hidden CLI alias; older invocations keep schema-version-1 JSON.          |
| `axe.lumberjacks.<name>.chops`                                    | `axe.routines.<name>.jobs`                             | Accepted on input; effective config and new examples use canonical keys. |
| `chop_script_dirs`, `chop_timeout`                                | `job_script_dirs`, `job_timeout`                       | The old keys remain input aliases.                                       |
| `lumberjack_log_*`, `lumberjack_restart_backoff_max_seconds`      | `routine_log_*`, `routine_restart_backoff_max_seconds` | The old keys remain input aliases.                                       |
| `verbose_lumberjack_diagnostics`                                  | `verbose_routine_diagnostics`                          | The old key remains an input alias.                                      |
| `SASE_CHOP_*`, `sase_chop_*`, `sase.chops`                        | `SASE_JOB_*`, `sase_job_*`, `sase.jobs`                | Script authors should use the job-named entrypoints and SDK facade.      |
| `sase_chop_tg_inbound`, `sase_chop_tg_outbound` (`sase-telegram`) | `sase_job_tg_inbound`, `sase_job_tg_outbound`          | `sase axe job doctor` warns when only the older entrypoints are found.   |
| `chop:<routine>/<job>` artifact references                        | `job:<routine>/<job>` artifact references              | Both resolve to the same stored link identity.                           |
| `sase doctor -C axe.chops`                                        | `sase doctor -C axe.jobs`                              | The old check ID remains a selection alias.                              |
| Stored `chop` agent tribe                                         | `job` tribe                                            | See [Scheduler jobs](../automation/scheduler-jobs.md).                   |

Canonical `sase axe job list --json` and `sase axe job doctor --json` emit
schema-version-2 JSON with routine/job field names. Hidden `chop` commands keep
schema-version-1 envelopes. On-disk paths under `~/.sase/axe/lumberjacks/` and
`agent_chops.json` are not migrated.

`inhibit_if.changespec` remains accepted as an alias of `inhibit_if.patch`.

## ToolRun project identity

Named-tool runs are recorded under the repository that owns the catalog, not the host
project. Rows written before that rule keep the identity they were recorded with and are
not rewritten. Linked-repo `check` runs from that period carry the host project's
identity and are told apart only by `definition_digest`. See
[Named tools and ToolRuns](../automation/tools.md).

## Unparseable snooze deadlines

A stored row whose `snooze_until` is unparseable or timezone-naive resurfaces
immediately. New mutations reject that value. Rows written before `resurfaced_at`
existed default to `resurfaced_at: null`. See
[Notifications](../automation/notifications.md).

## Related

- [Automation](../automation/index.md) — current notification, scheduler, monitor, and
  tool behavior.
- [Upgrading](index.md) — other upgrade notes.

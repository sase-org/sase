---
title: "Runtime and storage configuration"
description: "Configuration for processes, services, local storage, and telemetry."
---

# Runtime and storage configuration

Configuration for processes, services, local storage, and telemetry.

## procs

Durable proc records live in `~/.sase/procs/procs.jsonl`, with combined output logs
under `~/.sase/procs/logs/`. Retention keeps every pending or running proc plus the
newest configured number of finished procs. Lowering the limit trims the oldest finished
rows and their logs; active work is never pruned. Finished procs tagged `command-line`
(TUI Command Line submissions) keep a separate bucket of 50 beside this limit, so heavy
Command Line use never evicts operational proc history.

Each proc also has a runtime directory under `~/.sase/procs/runtime/`. Retention deletes
a pruned row's runtime directory immediately, while the hourly `proc_runtime_sweep`
housekeeping job removes older rowless (orphaned) runtime directories within the horizon
and per-pass budget below. Fresh orphans are left alone so a launch that is still
reserving its row is never raced.

```yaml
procs:
  history_limit: 100
  runtime_orphan_horizon_seconds: 259200
  runtime_orphan_max_removals: 2000
```

[Generated reference for `procs`](runtime.md#procs)

The top-level `tasks` block is still schema-valid, and `sase config layers` and
`sase doctor` flag it for migration. In practice the legacy key has no effect in a
normal merged configuration: the bundled defaults always supply `procs.history_limit`,
which takes precedence over `tasks.history_limit`. Move the value to
`procs.history_limit` to change retention.

## service

The per-machine service host supervises configured daemon procs and transient oneshots.
Its catalog is deliberately machine-owned: builtin defaults, plugin defaults, user
config, and machine overlays compose field by field, while project-local `sase/sase.yml`
`service:` entries are ignored — the host resolves machine-level layers only, never a
project-local `sase.yml`. Lists replace earlier lists whole; `env` is the one map that
merges key by key. A section-level error fails closed, while an invalid individual entry
stays visible as unavailable and does not block valid peers.

```yaml
service:
  procs:
    scheduler:
      builtin: scheduler
      description: "SASE's background automation: routines and their jobs."
    gateway:
      builtin: gateway
      description: "Mobile gateway HTTP API for remote agent dispatch."
      enabled: false
    indexer:
      command: [my-indexer, --watch]
      cwd: ~/work
      env:
        LOG_LEVEL: info
      restart: on-failure
      after: [scheduler]
```

The shipped `scheduler` entry is enabled and owns routine/job automation. The shipped
`gateway` entry is disabled so a default host does not expose a mobile API on machines
that never paired a phone; it is enabled per machine in the overlay where the gateway is
wanted. Builtin launchers must use the entry's own reserved name. A custom entry instead
supplies exactly one `command`: a string runs through `sh -c`, while a string array runs
directly as argv.

[Generated reference for `service`](runtime.md#service)

A bare `command` array's first element (for example `sase_job_tg_inbound`) is looked up
on `PATH` first and then in the bin directory of the interpreter running the host. The
second lookup is what makes a plugin's console scripts work under
`uv tool install --with`, which links only the primary package's entry points onto
`PATH`. A `PATH` hit always wins, an element that contains a path separator is used as
written, and the remaining arguments are never changed. The string (shell) form gets no
such fallback, because the shell resolves the name; prefer the array form for plugin
scripts. `sase service init` warns when an enabled entry's executable resolves nowhere.

`sase service proc enable/disable` writes machine-local effective enablement without
editing YAML. `stop` changes only the current boot: it records a marker that is cleared
on the next host boot. `start` and `restart` record a durable, numbered request that
also clears that marker; the host consumes it and the CLI waits for the confirmed pid.
Use `sase service proc show NAME` to see where an effective entry and enablement came
from, plus the current restart decision and any pending request.

Restart policy: `always` restarts after every exit and `on-failure` after a non-clean
one, each with a backoff that starts at 1 second and doubles up to 60 seconds. A clean
exit is exit code `0`, a `success_exit_codes` code, or death by `SIGTERM`, `SIGINT`,
`SIGHUP`, or `SIGPIPE`; a stop the host itself requested is never restarted. Three
restart-triggering exits or spawn failures within 60 seconds mark the proc `crash_loop`
and raise one `service` notification per crash-loop episode; a run of at least 5 minutes
resets the backoff and ends the episode. When the policy decides not to restart — a
clean exit under `on-failure`, or any exit or spawn failure under `never` — the host
parks the proc instead of relaunching it on the next reconcile, and raises a `service`
notification when the proc is still desired running. A parked proc stays down until an
explicit `start`/`restart` request, a changed entry, a disable-then-enable cycle, or a
restart of the service host itself. If the `service.procs` configuration stops loading,
the host keeps supervising its last-known-good configuration and surfaces the load error
as the host error in `sase service status`; a host that has never loaded a valid
configuration launches nothing until it does.

`sase service init --yes` installs an idempotent user unit (`sase.service` under
`systemd --user` on Linux, `sh.sase.service` as a macOS LaunchAgent), captures only the
allow-listed provider credentials, `PATH`, `SASE_TMPDIR`, `SASE_HOME`, and configured
mobile credential environment variable into a mode-`0600` file, retires legacy
gateway/AXE units, enables the unit, and starts it. `SASE_FEATURE_FLAGS` is never
captured: the host resolves flags from saved state. Planning and diffs redact every
captured value. Linux warns when user linger is off because the service may then stop at
logout. See [`sase service`](../agents/service-host.md#sase-service-1) for lifecycle
commands.

Source: `src/sase/default_config.yml`, `src/sase/config/sase.schema.json`,
`src/sase/service/config.py`, `src/sase/service/platform.py`

## disk

Disk-pressure thresholds combine absolute byte floors with proportional free-space
floors, so large volumes warn before they are almost out of bytes. The doctor resource
check uses these values, and the hourly `disk_pressure` housekeeping job uses the warn
threshold to decide when to notify and run owner-safe cleanup early.

```yaml
disk:
  pressure:
    warn_free_percent: 5.0
    error_free_percent: 1.0
    top_owner_min_bytes: 1073741824
```

[Generated reference for `disk`](runtime.md#disk)

`sase doctor` still honors its absolute floors of 3 GiB for WARN and 1 GiB for ERROR;
the effective threshold is the larger of the absolute and proportional values. Use
`sase disk list` to see SASE disk usage by owner and `sase disk reap` to preview or run
the owners' cleanup passes.

Source: `src/sase/default_config.yml`, `src/sase/core/disk_pressure.py`

<a id="managedtmp"></a>

## managed_tmp

Age horizons and pressure thresholds for the managed SASE temp root: `$SASE_TMPDIR` when
set, otherwise `$SASE_HOME/tmp` (`~/.sase/tmp` by default). SASE writes scratch there in
per-purpose bucket directories, and launched agents get `TMPDIR`/`TMP`/`TEMP`,
`CARGO_TARGET_DIR`, and `CARGO_BUILD_BUILD_DIR` pointed into managed buckets. Runners
remove their own launch-assigned scratch at exit when no live process still uses it;
`sase disk reap` and the hourly `managed_tmp_reap` housekeeping job clean up the rest
with these values.

Each bucket belongs to one horizon category. Editor, wrapper, per-agent `agent-tmp`, and
similar command scratch uses the command-scratch horizon; `handoff`, `gh-diffs`, and
`muse-prompts` use the handoff horizon; `build-targets` and `cargo-targets` use the
build-scratch horizon; and `launch-prompts`, `screenshots`, and `workflow-artifacts`,
which sase's TUI and screenshot tooling read back after a run ends, use the run-artifact
horizon. Unknown buckets and stray top-level entries are aged at the handoff horizon.
The bucket mapping is fixed; only the durations and pressure thresholds are
configurable.

Between the age horizons runs a dead-launch backstop over the launch-keyed buckets
(`agent-tmp`, `cargo-targets`, legacy `build-targets`) for launches that never ran
runner-exit cleanup — crashed, SIGKILLed, OOM-killed, or handed off to a monitor/gate
follow-up, which mints a fresh scratch key and leaves the old one quiet. Entries whose
newest descendant write predates `dead_launch.grace_seconds` and that no live process
holds (by environment or working directory, observed through procfs in one batch scan)
are removed largest-first within the removal budget. Held and incomplete-observation
entries are preserved and counted; hosts without readable procfs skip the pass and keep
the age horizons as the fallback.

Pressure pruning is a later pass that removes aged, large build scratch early when the
managed root grows past `pressure.max_bytes` or the filesystem's free space drops below
`pressure.min_available_bytes`. It never prunes generic agent scratch, handoff data,
unknown buckets, or build trees with fresh descendants. While the procfs observer is
available it is liveness-aware: a held entry is never removed, an incomplete observation
is preserved, and an unheld entry needs only the dead-launch grace rather than
`pressure.min_age_seconds`.

Every root `get_sase_managed_tmpdir()` writes into is recorded in a Rust-owned registry
at `$SASE_HOME/managed_tmp/roots.json` (schema version plus
`{path, first_seen_epoch, last_seen_epoch}` entries, written atomically under a lock
file). The hourly `managed_tmp_reap` job, the `disk_pressure` cleanup, and
`sase disk reap` each reap the effective root plus every registered root that still
exists, so scratch is bounded no matter which environment its writer resolved. A root
nested inside another covered root is folded into it, so it is not reaped or counted
twice. Registration is fail-open and never breaks a launch; only absolute, non-symlink
directories enroll, and broad roots such as `/tmp` or `$HOME` are refused.

In practice, the housekeeping `managed_tmp_reap` job, the `disk_pressure` job, and
`sase disk reap` all pass the shared [`disk.pressure`](#disk) warn threshold (the larger
of 3 GiB and `disk.pressure.warn_free_percent`) as both the free-space floor and the
recovery target, so `pressure.min_available_bytes` and
`pressure.recovery_available_bytes` currently take effect only for direct reaper calls
that leave those values unset.

Launched agents export `CARGO_INCREMENTAL=0` by default, or `CARGO_INCREMENTAL=1` when
`agent_cargo_incremental` is enabled. Only hosts with the splitting rustc wrapper
(athena) should opt in; elsewhere incremental test builds cost ~9 GB per run.

```yaml
managed_tmp:
  horizons:
    command_scratch_seconds: 43200
    handoff_seconds: 259200
    build_scratch_seconds: 86400
    run_artifact_seconds: 1209600
  max_removals: 2000
  dead_launch:
    enabled: true
    grace_seconds: 7200
  pressure:
    max_bytes: 17179869184
    target_bytes: 8589934592
    min_available_bytes: 34359738368
    recovery_available_bytes: 51539607552
    min_age_seconds: 43200
    low_free_space_min_age_seconds: 3600
    min_entry_bytes: 67108864
  agent_cargo_incremental: false
```

[Generated reference for `managed_tmp`](runtime.md#managed_tmp)

Source: `src/sase/default_config.yml`, `src/sase/config/_settings_system.py`,
`src/sase/core/managed_tmp_reaper.py`

## telemetry

Configures local telemetry recording and retention. See
[Telemetry details](../../contribute/telemetry.md) for the full telemetry reference,
including the CLI, metric catalog, local store, and Admin Center tab.

```yaml
telemetry:
  enabled: true
  flush_interval_seconds: 15
  retention:
    raw_seconds: 172800
    rollup_5m_seconds: 2592000
    rollup_1h_seconds: 31536000
  health_thresholds:
    error_rate_warn: 10.0
    error_rate_critical: 25.0
    retry_rate_warn: 10.0
    retry_rate_critical: 25.0
    p95_latency_warn: 300.0
    p95_latency_critical: 600.0
```

[Generated reference for `telemetry`](integrations.md#telemetry)

The legacy `telemetry.prometheus` block (`url`, `pushgateway_url`, `exposition_port`) is
still schema-valid for compatibility but is ignored.

Source: `src/sase/default_config.yml`, `src/sase/telemetry/_config.py`

<a id="toolruns"></a>

## tool_runs

Operational retention for the machine-local ToolRun ledger. This block uses ordinary
config-layer precedence (builtin, plugin, user, overlay, then project). It is
independent of the project-owned [`tools`](prompts-and-tools.md#tools) catalog: changing
retention cannot change argv.

```yaml
tool_runs:
  summary_days: 180
  detail_days: 60
  log_days: 14
  log_max_bytes: 2147483648
  run_log_max_bytes: 268435456
  event_max_bytes: 16777216
  soft_ceiling:
    default: ""
    providers: {}
```

[Generated reference for `tool_runs`](runtime.md#tool_runs)

`tool_runs.soft_ceiling` is the most time an agent should block on one `sase tool run`
before escalating to a monitor; it kills nothing; the effective budget is the smaller of
this and the hard ceiling's budget. The provider entry wins, then `default`, then none.
A malformed or non-positive value is ignored with one warning and never fails a launch.

Unknown fields and non-positive or inconsistent horizons are rejected. JSON Schema
cannot express `detail_days <= summary_days`; runtime validation covers that.

Source: `src/sase/default_config.yml`, `src/sase/config/sase.schema.json`,
`src/sase/config/tools.py`

## update

Configures install-mode switching (see
[Install mode switching](../integrations/plugins-update.md#install-mode-switching)).

```yaml
update:
  dev_root: "~/projects/github"
```

[Generated reference for `update`](runtime.md#update)

Source: `src/sase/default_config.yml`, `src/sase/mode_switch/repos.py`

## Related

- [Runtime and stored data configuration](runtime.md) — generated keys and defaults.
- [Configuration reference](index.md) — all configuration subjects.

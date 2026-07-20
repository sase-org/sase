# Telemetry

SASE records debugging and health metric history locally. No network service is required: instrumented processes
accumulate metric deltas in memory, periodically flush them to a SQLite store through the Rust core, and query the same
store through the telemetry diagnostics CLI. Historical product-usage questions are answered by the Admin Center's
Statistics tab from durable run and activity records instead of this short-lived metric store.

Telemetry is enabled by default. Set `telemetry.enabled: false` to opt out; instrumentation then remains connected to
lightweight no-op stubs and no samples are written.

## Architecture

```text
Instrumentation (.labels().inc() / .observe() / .set())
        |
        v
In-process accumulators
        |  periodic flush for daemons; exit flush for runners
        v
sase_core_rs telemetry bindings
        |
        v
~/.sase/telemetry/metrics.sqlite
        |
        +---- sase telemetry cleanup-test-data/health/list/snapshot/status
```

Counters and histograms flush only the delta accumulated since the previous write. Gauges flush their latest value with
a process source identifier; queries discard stale sources so crashed processes do not remain active forever. Writes use
short transactions, WAL mode, and a bounded busy timeout. A failed flush is retried a bounded number of times and then
dropped at debug log level rather than interrupting normal SASE work.

The Rust core owns storage, rollups, retention, range aggregation, and histogram quantiles. Python owns instrumentation,
configuration, local path selection, and presentation.

## Configuration

The default configuration is:

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

| Field                                              | Default    | Meaning                                         |
| -------------------------------------------------- | ---------- | ----------------------------------------------- |
| `telemetry.enabled`                                | `true`     | Record telemetry locally.                       |
| `telemetry.flush_interval_seconds`                 | `15`       | Flush cadence for long-lived processes.         |
| `telemetry.retention.raw_seconds`                  | `172800`   | Raw sample retention: 48 hours.                 |
| `telemetry.retention.rollup_5m_seconds`            | `2592000`  | Five-minute rollup retention: 30 days.          |
| `telemetry.retention.rollup_1h_seconds`            | `31536000` | Hourly rollup retention: one year.              |
| `telemetry.health_thresholds.error_rate_warn`      | `10.0`     | Error-rate percentage that produces WARN.       |
| `telemetry.health_thresholds.error_rate_critical`  | `25.0`     | Error-rate percentage that produces CRITICAL.   |
| `telemetry.health_thresholds.retry_rate_warn`      | `10.0`     | Retry-rate percentage that produces WARN.       |
| `telemetry.health_thresholds.retry_rate_critical`  | `25.0`     | Retry-rate percentage that produces CRITICAL.   |
| `telemetry.health_thresholds.p95_latency_warn`     | `300.0`    | P95 duration in seconds that produces WARN.     |
| `telemetry.health_thresholds.p95_latency_critical` | `600.0`    | P95 duration in seconds that produces CRITICAL. |

The default database path is `~/.sase/telemetry/metrics.sqlite` (under the effective SASE home). The parent directory
and database are created when the first batch is recorded.

### Retention and rollups

Raw samples support recent health queries. As raw data ages, the store folds it into five-minute and hourly rollups;
range queries choose the appropriate resolution transparently. Retention pruning is opportunistic on writes, so a
read-only command never performs cleanup.

## CLI commands

With no subcommand, `sase telemetry` prints a delegation notice and runs `sase telemetry list`.

### `sase telemetry cleanup-test-data`

Preview or remove rows whose exact labels identify known test data. The match set is deliberately narrow:
`llm_provider=test-provider`, `llm_provider=fakey`, or `workflow=test-workflow`. The command reports matching raw,
five-minute-rollup, and hourly-rollup rows plus the store size before and after the operation.

```bash
sase telemetry cleanup-test-data --dry-run
sase telemetry cleanup-test-data --yes
```

Every invocation prints the criteria and a preview first. `-n|--dry-run` stops after that preview without changing the
store. Running without either flag also leaves the store unchanged but exits `2` with a refusal; deletion requires the
explicit `-y|--yes` flag. Exact matching preserves near misses such as `test-provider-local`.

### `sase telemetry health`

Assess the last hour of data using the configured error-rate, retry-rate, and p95 thresholds. Rich output is the
default; JSON is available for automation.

```bash
sase telemetry health
sase telemetry health -j
```

Exit codes are `0` for healthy, `1` for degraded/WARN, and `2` for CRITICAL.

### `sase telemetry list`

Display the metric catalog derived from the same definitions used by instrumentation.

```bash
sase telemetry list
sase telemetry list -s "Agent Lifecycle"
sase telemetry list -t histogram
```

| Flag              | Values                          | Meaning                     |
| ----------------- | ------------------------------- | --------------------------- |
| `-s, --subsystem` | subsystem name                  | Restrict the catalog group. |
| `-t, --type`      | `counter`, `gauge`, `histogram` | Restrict the metric kind.   |

### `sase telemetry snapshot`

Query current values from the local store. Counters are summed, current gauges use only fresh source values, and
histograms include count, average, minimum, and maximum.

```bash
sase telemetry snapshot
sase telemetry snapshot -f json
sase telemetry snapshot -s "LLM Provider"
```

| Flag              | Values         | Default | Meaning                    |
| ----------------- | -------------- | ------- | -------------------------- |
| `-f, --format`    | `rich`, `json` | `rich`  | Output format.             |
| `-s, --subsystem` | subsystem name | all     | Restrict returned metrics. |

### `sase telemetry status`

Show whether recording is enabled, the resolved database path and size, raw and rollup sample counts, inferred flusher
state, and last-write freshness by subsystem.

```bash
sase telemetry status
```

## Admin Center Statistics tab

Open the SASE Admin Center with `#` or the command palette, then press `4` or select **Statistics**. The pane aggregates
durable agent records rather than the short-lived telemetry metric store described above. It loads only while visible,
performs aggregation off the UI thread, refreshes every 30 seconds, and shows loading, empty-range, and query-error
states in place.

The scope header makes the current controls explicit: **Range** shows a friendly summary and, when space permits, its
absolute span; **Group** names the active Projects or Runtime dimension; and **Project** shows **All projects** or the
configured display name and color of the selected project. A custom range is labeled **Custom**, and narrow terminals
compact the chips without changing the selection. Project keys remain canonical internally even when every visible label
is humanized.

The seven views answer different questions:

| View                  | Contents                                                                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Overview**          | Run volume over time plus top providers, skills, and projects.                                                                                          |
| **Runs**              | Outcomes, active and waiting work, retry chains, commit attribution, and top target repositories.                                                       |
| **Projects**          | Project and ChangeSpec run counts, success, commits, wall time, and last activity; `g` cycles project, ChangeSpec, and project-to-ChangeSpec groupings. |
| **Providers**         | Provider, model, and effort usage with success rates and average runtime.                                                                               |
| **Runtime**           | Total, mean, p50, p95, and maximum runtime; `g` cycles tribe, clan, family, agent, provider, model, workflow, project, and ChangeSpec dimensions.       |
| **Activity**          | Skill, memory, and workspace use.                                                                                                                       |
| **Plans & Questions** | Plan lifecycle and tier/phase distributions plus question-session counts and sizes.                                                                     |

Each view ends with a compact legend defining its calculated metrics. Press `?` for the complete per-view glossary,
control list, active range/group/project scope, and freshness notes. On Overview, the Agents Run, Success Rate, and
Commits tiles open Runs when clicked; Plans Proposed and Questions open Plans & Questions without another data load.

| Key     | Action                                                              |
| ------- | ------------------------------------------------------------------- |
| `[`/`]` | Cycle statistic views.                                              |
| `t`     | Cycle Today, 24h, 7d, 30d, 90d, and All.                            |
| `c`     | Enter a custom absolute or relative time range.                     |
| `g`     | Cycle grouping in the Projects or Runtime view.                     |
| `p`     | Cycle All → each project from the latest unfiltered ranking → All.  |
| `r`     | Refresh immediately.                                                |
| `?`     | Open contextual help; press the configured help key again to close. |

Custom ranges accept elapsed windows such as `12h`, `14d`, or `8w`; a calendar month such as `2026-07`; a closed date
range such as `2026-07-01..2026-07-18`; or an open-ended range such as `2026-07-01..`. Calendar inputs use the
configured SASE timezone, closed ranges include the final date, and future time is excluded.

The project choices come from the most recent unfiltered result. If you change the range while a project remains
selected, `p` continues to use that cached list; cycle back to **All** and let the pane reload to rank projects for the
new range. When the selected project has no rows in the range, one `p` clears the filter directly to **All projects**.

The project filter applies to run-backed totals, project-attributed activity, plan lifecycle counts, and question
session counts. Some distributions are derived from global plan and question documents rather than project-attributed
runs: while a project filter is active, the pane labels plan tiers, phases per epic, total questions, and questions per
session as **all projects** so their scope is explicit. The Projects view also retains an `(no ChangeSpec)` row for runs
that have a project but no ChangeSpec attribution.

Override these focused-pane bindings under `ace.keymaps.statistics`; the effective keys are reflected in the pane's hint
bar:

```yaml
ace:
  keymaps:
    statistics:
      prev_view: "["
      next_view: "]"
      cycle_range: "t"
      custom_range: "c"
      cycle_group: "g"
      cycle_project_filter: "p"
      refresh: "r"
      help: "question_mark"
```

The bindings are inactive on every other Admin Center tab and may safely overlap global app keys. Empty ranges name the
active range and show the effective keys for widening it and, when applicable, clearing the project filter. A first-load
query failure shows the error and the effective refresh key for retrying; a failure after successful data has loaded
keeps the prior result visible while marking the refresh as failed.

## Metric catalog and integration

The catalog contains 27 counters, gauges, and histograms across five groups: Agent Lifecycle, LLM Provider, Axe
Orchestrator, Hooks/Mentors/Workflows, and VCS/Workspace. Run `sase telemetry list` for the authoritative metric names,
kinds, and labels.

Instrumentation remains at debugging and health boundaries: agent runner setup/finalization, LLM invocation, axe and
lumberjack loops, hook and mentor runners, VCS operations, active-workspace tracking, and zombie detection. Call sites
keep the stable `.labels().inc()`, `.observe()`, and `.set()` API regardless of whether recording is enabled.

## Migration from the external stack

The bundled Docker Compose, Grafana, Prometheus, and Pushgateway stack has been removed. Existing exported stacks are no
longer used by SASE and may be stopped and deleted independently. Legacy `telemetry.prometheus` configuration is
accepted but ignored; remove it when convenient. Historical data from the old stack is not imported, so local telemetry
begins with samples recorded after upgrading.

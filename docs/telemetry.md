# Telemetry

SASE records debugging and health metric history locally. No network service is
required: instrumented processes accumulate metric deltas in memory, periodically flush
them to a SQLite store through the Rust core, and query the same store through the
telemetry diagnostics CLI. Historical product-usage questions are answered by the Admin
Center's Statistics tab from durable run and activity records instead of this
short-lived metric store.

Telemetry is enabled by default. Set `telemetry.enabled: false` to opt out;
instrumentation then remains connected to lightweight no-op stubs and no samples are
written.

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

Counters and histograms flush only the delta accumulated since the previous write.
Gauges flush their latest value with a process source identifier; queries discard stale
sources so crashed processes do not remain active forever. Writes use short
transactions, WAL mode, and a bounded busy timeout. A failed flush is retried a bounded
number of times and then dropped at debug log level rather than interrupting normal SASE
work.

The Rust core owns storage, rollups, retention, range aggregation, and histogram
quantiles. Python owns instrumentation, configuration, local path selection, and
presentation.

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

The default database path is `~/.sase/telemetry/metrics.sqlite` (under the effective
SASE home). The parent directory and database are created when the first batch is
recorded.

### Retention and rollups

Raw samples support recent health queries. As raw data ages, the store folds it into
five-minute and hourly rollups; range queries choose the appropriate resolution
transparently. Retention pruning is opportunistic on writes, so a read-only command
never performs cleanup.

## CLI commands

With no subcommand, `sase telemetry` prints a delegation notice and runs
`sase telemetry list`.

### `sase telemetry cleanup-test-data`

Preview or remove rows whose exact labels identify known test data. The match set is
deliberately narrow: `llm_provider=test-provider`, `llm_provider=fakey`, or
`workflow=test-workflow`. The command reports matching raw, five-minute-rollup, and
hourly-rollup rows plus the store size before and after the operation.

```bash
sase telemetry cleanup-test-data --dry-run
sase telemetry cleanup-test-data --yes
```

Every invocation prints the criteria and a preview first. `-n|--dry-run` stops after
that preview without changing the store. Running without either flag also leaves the
store unchanged but exits `2` with a refusal; deletion requires the explicit `-y|--yes`
flag. Exact matching preserves near misses such as `test-provider-local`.

### `sase telemetry health`

Assess the last hour of data using the configured error-rate, retry-rate, and p95
thresholds. Rich output is the default; JSON is available for automation.

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

Query current values from the local store. Counters are summed, current gauges use only
fresh source values, and histograms include count, average, minimum, and maximum.

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

Show whether recording is enabled, the resolved database path and size, raw and rollup
sample counts, inferred flusher state, and last-write freshness by subsystem.

```bash
sase telemetry status
```

## Admin Center Statistics tab

Open the SASE Admin Center with `#` or the command palette, then press `5` or select
**Statistics**. The first seven views aggregate durable agent records. The eighth,
**Perf**, combines bounded TUI diagnostic logs with the telemetry metric store described
above. The pane loads only while visible, performs aggregation off the UI thread,
refreshes every 30 seconds, and shows loading, empty-range, and query-error states in
place.

The scope header makes the current controls explicit: **Range** shows a friendly summary
and, when space permits, its absolute span; **Group** appears only in the Projects,
XPrompts, and Perf views and names the active dimension; and **Project** shows **All
projects** or the selected project's display name (falling back to its canonical key),
preceded by a categorical color swatch. A custom range is labeled **Custom**, and narrow
terminals compact the chips without changing the selection. Project keys remain
canonical internally even when a configured display name is shown. Perf is global, so
its project chip stays visible but adds **not applied**.

**All time** has no real start instant, so its absolute span reads
`through <end> · start bounded by retained data` instead of naming a date. What it
covers is whatever the agent-artifact index and the telemetry store still retain — see
[Retention and rollups](perf_runbook.md#retention-and-rollups) for the Perf view's two
retention rules.

The eight numbered views answer different questions:

| #   | View                  | Contents                                                                                                                                                                                                       |
| --- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Overview**          | Run volume over time plus top providers, skills, and projects.                                                                                                                                                 |
| 2   | **Runners**           | Historical runner occupancy and concurrency trends, with today's effective global limit (including a temporary override) as present-day context.                                                               |
| 3   | **Projects**          | Project and Patch run counts, success, commits, wall time, and last activity; `g` cycles project, Patch, and project-to-Patch groupings. A bounded Patch list closes with `N additional Patch rows not shown.` |
| 4   | **Providers**         | Provider, model, and effort usage with success rates and average runtime.                                                                                                                                      |
| 5   | **Activity**          | Skill, memory, and workspace use; the three panels are titled **Top …** because each is truncated to the highest-volume rows.                                                                                  |
| 6   | **XPrompts**          | XPrompt use by frequency, model, project, and co-usage, with an optional focused XPrompt drill-down.                                                                                                           |
| 7   | **Plans & Questions** | Plan lifecycle and tier/phase distributions plus question-session counts and sizes.                                                                                                                            |
| 8   | **Perf**              | TUI startup and responsiveness, launch and agent/LLM latency, reliability, and the health of each data source.                                                                                                 |

Each populated view ends with a compact legend defining its calculated metrics. Press
`?` for the complete per-view glossary, control list, active range/group/project scope,
and freshness notes. On Overview, the Agents Run, Success Rate, and Commits tiles open
Projects when clicked; Plans Proposed and Questions open Plans & Questions without
another data load.

Two Overview definitions differ from each other on purpose: the **Success Rate** tile is
completed ÷ _finished_ runs, while the **Top projects** success column is completed ÷
_all_ runs in the range. "Finished" means the run reached a terminal outcome, so the
tile ignores runs still in progress while the column counts them in its denominator. A
range holding many live runs therefore shows a tile percentage above the column's. The
legend states both.

Overview's **Runs over time** panel is clamped to observed activity. Leading and
trailing zero-run buckets are dropped, so a wide window does not render years of empty
rows, while interior zero buckets are kept so gaps in activity stay visible. If more
than 96 buckets remain, adjacent buckets are merged into equal-width chunks and the
panel title names the new width (for example `Runs over time · 7-day buckets`); an
unaggregated panel keeps the plain title.

The empty state is per view rather than global. Overview, Projects, and Providers are
entirely run-derived, so they report "No agent runs recorded in …". Activity and Plans &
Questions are timestamped by when their skill/memory/plan/question events happened
rather than by when the producing agent launched, so they report their own emptiness
("No skill or memory activity recorded", "No plans or questions recorded") and still
render data in a window that contains no launches. Runners, XPrompts, and Perf render
their own empty states inside the view.

The default focused-pane keys are:

| Key                 | Action                                                                                   |
| ------------------- | ---------------------------------------------------------------------------------------- |
| `[`/`]`             | Cycle statistic views.                                                                   |
| `0`, then `1`–`8`   | Select the corresponding numbered Statistics view.                                       |
| `'`                 | Arm the same numbered-view selection as `0`.                                             |
| `t`/`T`             | Cycle Today, 24h, 7d, 30d, 90d, and All forward / backward.                              |
| `c`                 | Enter a custom absolute or relative time range.                                          |
| `g`                 | Cycle grouping in Projects, XPrompts, or Perf.                                           |
| `p`                 | Cycle All → each project from the latest unfiltered ranking → All.                       |
| `P`                 | Cycle the same project order backward, wrapping in either direction.                     |
| `x` / `X`           | Focus one XPrompt / return to all XPrompts in the XPrompts view.                         |
| `Ctrl+D` / `Ctrl+U` | Scroll the statistics body down / up by half a page when the range input is not focused. |
| `r`                 | Refresh immediately.                                                                     |
| `?`                 | Open contextual help; press the configured help key again to close.                      |

From a custom range, `t` returns to **Today** and `T` returns to **All time** before
subsequent presses continue through the preset cycle.

Custom ranges accept elapsed windows such as `12h`, `14d`, or `8w`; a calendar month
such as `2026-07`; a closed date range such as `2026-07-01..2026-07-18`; or an
open-ended range such as `2026-07-01..`. Calendar inputs use the configured SASE
timezone, closed ranges include the final date, and future time is excluded.

The project choices are ranked by run count in the most recently loaded unfiltered
result. First open seeds the current project when `ace.current_project.seed_filters` is
on; `p` / `P` can always cycle away from that seed. The cycle is **All projects**
followed by those ranked projects: `p` moves forward and wraps, while `P` moves backward
and wraps. From **All**, `p` selects the first ranked project and `P` selects the last.
If you change the range while a project remains selected, both keys continue to use that
cached list; cycle back to **All** and let the pane reload to rank projects for the new
range. When the selected project has no rows in the range, either key clears the filter
directly to **All projects**.

The project filter applies to run-backed metrics, project-attributed activity (including
the Activity view's skill and memory panels), and—in Plans & Questions—the run-backed
plan lifecycle, Sessions, and Asking agents summaries. Plan tiers and phases, plus
total-question counts and questions-per-session distributions, come from global
documents rather than project-attributed runs. The detailed Plans & Questions view
labels those fields **all projects** while a project is selected. The Overview Plans
Proposed and Questions tiles also use all-project document aggregates, but their tile
faces do not append that scope label. The Projects view retains an `(no Patch)` row for
runs that have a project but no Patch attribution. Perf does not apply the project
filter because its telemetry labels and TUI diagnostic logs do not carry project
attribution. See
[Reading the Admin Center Perf view](perf_runbook.md#reading-the-admin-center-perf-view)
for its panels, sources, retention, and probe flags.

Override these focused-pane bindings under `ace.keymaps.statistics`; the effective keys
are reflected in the pane's hint bar:

```yaml
ace:
  keymaps:
    statistics:
      prev_view: "["
      next_view: "]"
      select_view: "0"
      jump_to_entry: "apostrophe"
      cycle_range: "t"
      cycle_range_reverse: "T"
      custom_range: "c"
      cycle_group: "g"
      cycle_project_filter: "p"
      cycle_project_filter_reverse: "P"
      focus_xprompt: "x"
      clear_xprompt_focus: "X"
      scroll_down: "ctrl+d"
      scroll_up: "ctrl+u"
      refresh: "r"
      help: "question_mark"
```

The bindings are inactive on every other Admin Center tab and may safely overlap global
app keys. Empty ranges name the active range and show the effective keys for widening it
and, when applicable, clearing the project filter. A first-load query failure shows the
error and the effective refresh key for retrying; a failure after successful data has
loaded keeps the prior result visible while marking the refresh as failed.

## Metric catalog and integration

The catalog contains 27 counters, gauges, and histograms across five groups: Agent
Lifecycle, LLM Provider, Axe Orchestrator, Hooks/Mentors/Workflows, and VCS/Workspace.
Run `sase telemetry list` for the authoritative metric names, kinds, and labels.

Instrumentation remains at debugging and health boundaries: agent runner
setup/finalization, LLM invocation, axe and lumberjack loops, hook and mentor runners,
VCS operations, active-workspace tracking, and zombie detection. Call sites keep the
stable `.labels().inc()`, `.observe()`, and `.set()` API regardless of whether recording
is enabled.

## Migration from the external stack

The bundled Docker Compose, Grafana, Prometheus, and Pushgateway stack has been removed.
Existing exported stacks are no longer used by SASE and may be stopped and deleted
independently. Legacy `telemetry.prometheus` configuration is accepted but ignored;
remove it when convenient. Historical data from the old stack is not imported, so local
telemetry begins with samples recorded after upgrading.

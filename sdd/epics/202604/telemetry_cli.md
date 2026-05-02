---
create_time: 2026-04-07 23:40:55
status: done
bead_id: sase-e
prompt: sdd/prompts/202604/telemetry_cli.md
---

# Plan: `sase telemetry` CLI Subcommand

## Overview

Build a `sase telemetry` CLI command that makes Prometheus metrics accessible, beautiful, and actionable directly from
the terminal. Five subcommands across three phases, each phase independently useful.

**Design principles:**

- **Intuitive** — subcommands map to natural questions: "Is telemetry working?" (`status`), "What metrics exist?"
  (`list`), "What are the current values?" (`snapshot`), "Show me a live view" (`dashboard`), "Is everything healthy?"
  (`health`)
- **Reliable** — graceful degradation when data sources are unreachable; never crashes on network errors
- **Beautiful** — Rich panels, colored type badges, traffic-light indicators, grouped layout

## Data Sources

| Source               | URL                                          | Contains                                             | Availability                              |
| -------------------- | -------------------------------------------- | ---------------------------------------------------- | ----------------------------------------- |
| Push Gateway         | `http://{pushgateway_url}/metrics`           | Latest pushed values from all jobs                   | When pushgateway is running               |
| Exposition endpoint  | `http://localhost:{exposition_port}/metrics` | Current values from a running process (e.g., axe)    | When a long-lived sase process is running |
| Internal definitions | `sase.telemetry.metrics.METRIC_DEFS`         | Metric metadata (names, types, labels, descriptions) | Always available                          |

Both external sources return standard Prometheus text exposition format.

## Subcommands

### `sase telemetry status`

Quick health check and config display.

```
$ sase telemetry status
╭─── Telemetry Status ──────────────────────────────╮
│                                                    │
│  Enabled      ● yes                                │
│  Metrics      28 registered (19 counters,          │
│               5 histograms, 4 gauges)              │
│                                                    │
│  Push Gateway localhost:9091     ● reachable       │
│  Exposition   localhost:9464     ○ not running      │
│                                                    │
╰────────────────────────────────────────────────────╯
```

- Green `●` / red `○` connectivity indicators (HTTP GET with 2s timeout)
- Shows metric count breakdown by type
- When telemetry is disabled, shows a clear message with how to enable it

### `sase telemetry list`

Metric catalog from internal definitions.

```
$ sase telemetry list
╭─── Agent Lifecycle (5 metrics) ────────────────────────────────────────────╮
│  Name                  Prometheus Name                 Type      Labels    │
│  AGENT_RUNS            sase_agent_runs_total           counter   provider… │
│  AGENT_RUN_DURATION    sase_agent_run_duration_seconds histogram provider… │
│  AGENT_ACTIVE          sase_agent_active               gauge     provider… │
│  ...                                                                      │
╰────────────────────────────────────────────────────────────────────────────╯
╭─── LLM Provider (4 metrics) ──────────────────────────────────────────────╮
│  ...                                                                      │
╰────────────────────────────────────────────────────────────────────────────╯
```

- Grouped by subsystem in separate panels
- Colored type badges: `counter` (cyan), `histogram` (magenta), `gauge` (yellow)
- `--subsystem/-s SUBSYSTEM` — filter to specific subsystem(s)
- `--type/-t TYPE` — filter by metric type

### `sase telemetry snapshot`

Fetch and display current metric values.

```
$ sase telemetry snapshot
╭─── Agent Lifecycle ───────────────────────────────────────────────────────╮
│  sase_agent_runs_total{provider="claude",status="ok"}           42       │
│  sase_agent_runs_total{provider="claude",status="error"}         3       │
│  sase_agent_active{provider="claude",project="sase"}             2       │
│  sase_agent_run_duration_seconds (p50=45.2s p95=180.3s p99=312.1s)      │
╰───────────────────────────────────────────────────────────────────────────╯
```

- `--source/-S` (auto|pushgateway|exposition) — where to fetch from; "auto" tries pushgateway first
- `--format/-f` (rich|json|prometheus) — output format
- `--subsystem/-s` — filter by subsystem
- Histograms show computed percentiles (p50, p95, p99) from bucket data
- Gauges show current value; counters show total

### `sase telemetry dashboard`

Live auto-refreshing TUI.

```
$ sase telemetry dashboard
┌ Telemetry Dashboard ─── refreshing every 5s ─── Ctrl+C to exit ─────────┐
│                                                                          │
│ ╭─ Agents ────────╮ ╭─ LLM ──────────╮ ╭─ Axe ──────────╮              │
│ │ Active    2      │ │ Invocations 156│ │ Lumberjacks  3  │              │
│ │ Runs     42      │ │ Errors       3 │ │ Cycles     847  │              │
│ │ Errors    3      │ │ Retries     12 │ │ Errors       0  │              │
│ │ p95   180.3s     │ │ p95    2.1s    │ │ Restarts     1  │              │
│ ╰──────────────────╯ ╰────────────────╯ ╰─────────────────╯              │
│                                                                          │
│ ╭─ Hooks ─────────╮ ╭─ Beads ────────╮ ╭─ VCS ───────────╮              │
│ │ Executions  89   │ │ Active    5    │ │ Commits     23  │              │
│ │ Retries      2   │ │ Operations 34 │ │ Operations 156  │              │
│ │ p95     0.8s     │ │ Transitions 12│ │ Workspaces   3  │              │
│ ╰──────────────────╯ ╰────────────────╯ ╰─────────────────╯              │
└──────────────────────────────────────────────────────────────────────────┘
```

- `--interval/-i SECONDS` (default 5) — refresh interval
- `--source/-S` (auto|pushgateway|exposition) — data source
- Uses Rich Live for flicker-free updates
- Compact panels per subsystem showing key metrics
- Color-coded values: green (normal), yellow (elevated), red (critical)
- Ctrl+C for clean exit

### `sase telemetry health`

Traffic-light health assessment for scripting.

```
$ sase telemetry health
╭─── Health Check ──────────────────────────────────╮
│                                                   │
│  ● Agents         OK     (error rate 6.7%)        │
│  ● LLM            OK     (error rate 1.9%)        │
│  ● Axe            OK     (0 errors)               │
│  ● Hooks          OK     (retry rate 2.2%)        │
│  ● Beads          OK     (0 stuck)                │
│  ● VCS            OK     (0 failures)             │
│  ● Notifications  OK     (0 failures)             │
│                                                   │
│  Overall: ● HEALTHY                               │
╰───────────────────────────────────────────────────╯

$ echo $?
0
```

- Exit codes: 0 (healthy), 1 (degraded), 2 (critical)
- `--json/-j` — machine-readable JSON output
- `--source/-S` (auto|pushgateway|exposition) — data source
- Thresholds configurable in `sase.yml` under `telemetry.health_thresholds`

## Catalog System

A new `src/sase/telemetry/catalog.py` module provides structured metadata derived from `METRIC_DEFS`:

```python
@dataclass(frozen=True)
class MetricInfo:
    attr: str              # "AGENT_RUNS"
    kind: str              # "counter"
    prometheus_name: str   # "sase_agent_runs_total"
    description: str       # "Total agent runs"
    labels: list[str]      # ["llm_provider", "status", "workflow"]
    subsystem: str         # "agent"

SUBSYSTEMS: dict[str, list[MetricInfo]]  # grouped by subsystem
```

Subsystem assignment is derived from the `-- Comment` markers in `METRIC_DEFS` or from the metric prefix (e.g.,
`sase_agent_*` -> "agent", `sase_llm_*` -> "llm"). The catalog is the single source of truth for all CLI rendering.

## Scrape Client

A new `src/sase/telemetry/scrape.py` module handles fetching and parsing metrics:

```python
@dataclass(frozen=True)
class MetricSample:
    name: str           # "sase_agent_runs_total"
    labels: dict        # {"llm_provider": "claude", "status": "ok"}
    value: float        # 42.0
    metric_type: str    # "counter" | "gauge" | "histogram" | "summary" | "untyped"

def scrape(url: str, timeout: float = 2.0) -> list[MetricSample]: ...
def check_reachable(url: str, timeout: float = 2.0) -> bool: ...
```

- Uses `urllib.request` (stdlib) — no new dependency needed
- Parses standard Prometheus text exposition format (`# TYPE`, `# HELP`, metric lines)
- Histogram bucket lines (`_bucket`, `_count`, `_sum`) are included as raw samples; percentile computation is a separate
  utility function
- All network errors caught and surfaced gracefully (never crashes)

## Phase Breakdown

### Phase 1: Foundation — CLI Scaffolding + Status + List

**Goal**: Working `sase telemetry` command with two subcommands that are immediately useful without external
infrastructure.

**Files to modify:**

- `src/sase/main/parser_commands.py` — add `register_telemetry_parser()` with all 5 subcommand parsers
- `src/sase/main/parser.py` — import and register (alphabetically between `search` and `xprompt`)
- `src/sase/main/entry.py` — add `telemetry` dispatch (between `search` and `xprompt`)

**Files to create:**

- `src/sase/main/telemetry_handler.py` — dispatch to sub-handlers
- `src/sase/telemetry/catalog.py` — `MetricInfo` dataclass + `SUBSYSTEMS` dict + `get_catalog()` function
- `src/sase/telemetry/cli_status.py` — `status` subcommand (config display + connectivity probes)
- `src/sase/telemetry/cli_list.py` — `list` subcommand (metric catalog with Rich tables)
- `tests/telemetry/test_catalog.py` — catalog correctness tests
- `tests/telemetry/test_cli_status.py` — status output tests (mock connectivity)
- `tests/telemetry/test_cli_list.py` — list output/filtering tests

### Phase 2: Data Layer + Snapshot

**Goal**: Fetch live metrics from external sources and display current values.

**Files to create:**

- `src/sase/telemetry/scrape.py` — HTTP client + Prometheus text format parser
- `src/sase/telemetry/cli_snapshot.py` — `snapshot` subcommand (fetch, parse, render with Rich)
- `tests/telemetry/test_scrape.py` — parser tests with sample Prometheus text
- `tests/telemetry/test_cli_snapshot.py` — snapshot rendering tests

**Dependencies**: Phase 1 (catalog, CLI scaffolding)

### Phase 3: Dashboard + Health

**Goal**: The showpiece live dashboard and the scriptable health check.

**Files to create:**

- `src/sase/telemetry/cli_dashboard.py` — Rich Live auto-refreshing dashboard
- `src/sase/telemetry/cli_health.py` — health check with thresholds and exit codes

**Files to modify:**

- `src/sase/default_config.yml` — add `telemetry.health_thresholds` config section
- `src/sase/telemetry/_config.py` — add health threshold fields to config dataclass

**Files to create:**

- `tests/telemetry/test_cli_dashboard.py` — dashboard rendering tests
- `tests/telemetry/test_cli_health.py` — health check logic + exit code tests

**Dependencies**: Phase 2 (scrape client)

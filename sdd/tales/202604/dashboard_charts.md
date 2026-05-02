---
create_time: 2026-04-08 02:06:26
status: done
prompt: sdd/prompts/202604/dashboard_charts.md
---

# Plan: Improve `sase telemetry dashboard` with Historical Charts

## Problem

The current `sase telemetry dashboard` is a plain text table that scrapes **current** metric values and displays them as
numbers in Rich panels. It has no charting, no historical data, and no visual appeal. Meanwhile, the monitoring stack
already includes Prometheus (port 9090) with full time-series history — we just never query it.

## Design

### Architecture Overview

```
Prometheus (9090)                    Pushgateway / Exposition
       |                                       |
  /api/v1/query_range              HTTP scrape (current values)
       |                                       |
  prom_query.py (NEW)                   scrape.py (existing)
       |                                       |
  charts.py (NEW)                    Summary stat panels
       |                                       |
       +------ cli_dashboard.py (ENHANCED) ----+
                         |
              Rich Live display + plotext charts
```

### New dependency: `plotext`

Terminal charting library. Supports line charts, bar charts, with color. Renders to strings via `plotext.build()` which
we embed inside Rich panels.

### New module: `src/sase/telemetry/prom_query.py`

Lightweight Prometheus HTTP API client:

- `TimeSeries` dataclass: `metric: str`, `labels: dict[str, str]`, `points: list[tuple[float, float]]`
- `query_range(base_url, query, start, end, step) -> list[TimeSeries]` — calls `/api/v1/query_range`
- `query_instant(base_url, query) -> list[TimeSeries]` — calls `/api/v1/query`
- `check_prometheus_reachable(base_url) -> bool`
- Uses stdlib `urllib.request` (consistent with `scrape.py`)
- Reads Prometheus URL from telemetry config (new `prometheus_url` field, default `localhost:9090`)

### New module: `src/sase/telemetry/charts.py`

Chart rendering functions, each returning a Rich renderable:

- `render_line_chart(series, title, y_label, width, height) -> Panel`
- `render_bar_chart(labels, values, title, ...) -> Panel`
- `render_sparkline(values, title) -> Text` (for inline summary stats)
- Uses plotext to render to string, wraps in Rich Panel

### Enhanced dashboard with two modes

**Summary mode** (default — enhanced version of what exists today):

- Top row: Large styled stat panels for key gauges (Active Agents, Active Workspaces, Active Beads) with color
  thresholds (green/yellow/red)
- Bottom rows: Compact subsystem metric tables with improved formatting, color-coded values

**Charts mode** (`-c/--charts` flag):

- Queries Prometheus for historical data over the configured time range
- Renders a grid of 6 chart panels:
  1. **Agent Run Duration** — line chart, p50 + p95 over time
  2. **Active Agents** — line chart of gauge over time
  3. **Agent Throughput** — bar chart of run rate by status (ok/error)
  4. **LLM Token Usage** — multi-line chart of input/output/cache token rates
  5. **LLM Latency** — line chart of p50/p95 invocation duration
  6. **Error Rate** — line chart of agent + LLM error rates over time
- Auto-refreshes (default 15s for charts mode since range queries are heavier)
- Falls back gracefully to summary mode with a warning if Prometheus is unreachable

### New CLI arguments

- `-c / --charts` — Enable charts mode with historical data from Prometheus
- `-r / --range` — Time range: `1h`, `6h`, `24h`, `7d` (default: `1h`)
- `-s / --subsystem` — Focus on a single subsystem (larger charts, more detail)

### Config update

Add `prometheus_url` to `_TelemetryConfig` in `_config.py`, default `localhost:9090`. Loaded from
`telemetry.prometheus.url` in sase config.

## Phases

### Phase 1: Prometheus query client + config update

- Add `prometheus_url` to `_TelemetryConfig` in `_config.py`
- Create `src/sase/telemetry/prom_query.py`
- Tests in `tests/telemetry/test_prom_query.py`

### Phase 2: Chart rendering module

- Add `plotext` to `pyproject.toml`
- Create `src/sase/telemetry/charts.py`
- Tests in `tests/telemetry/test_charts.py`

### Phase 3: Enhanced summary mode

- Rework `_build_dashboard` with styled stat panels on top, improved tables below
- Color coding for healthy/warning/critical values
- Better metric label formatting

### Phase 4: Charts mode integration

- Add chart layout to `cli_dashboard.py` using prom_query + charts modules
- Build the 6 chart panels with PromQL queries
- Wire into the Rich Live refresh loop

### Phase 5: CLI arguments + parser updates

- Add `-c/--charts`, `-r/--range`, `-s/--subsystem` to dashboard parser
- Wire through `handle_telemetry_dashboard`

### Phase 6: Tests for enhanced dashboard

- Dashboard layout tests (summary and charts modes)
- Fallback behavior when Prometheus unreachable
- Integration tests for chart rendering in panels

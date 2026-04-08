# Telemetry

This document describes the Prometheus-based telemetry system in sase. Telemetry tracks metrics across all major
subsystems — agent lifecycle, LLM providers, axe daemon, hooks, beads, VCS/workspace, and notifications — and provides
CLI tools for monitoring, health checks, and a bundled Docker Compose monitoring stack.

## Table of Contents

- [Overview](#overview)
- [Configuration](#configuration)
- [CLI Commands](#cli-commands)
  - [status](#sase-telemetry-status)
  - [list](#sase-telemetry-list)
  - [snapshot](#sase-telemetry-snapshot)
  - [dashboard](#sase-telemetry-dashboard)
  - [health](#sase-telemetry-health)
  - [export-config](#sase-telemetry-export-config)
- [Architecture](#architecture)
- [Metric Catalog](#metric-catalog)
- [Monitoring Stack](#monitoring-stack)
- [Integration Points](#integration-points)

## Overview

The telemetry system uses [Prometheus](https://prometheus.io/) metrics to instrument sase internals. Key design
principles:

- **Zero-cost when disabled**: All metrics are lightweight no-op stubs when `telemetry.enabled` is `false` (the
  default). There is no runtime overhead unless telemetry is explicitly enabled.
- **Dual data collection**: Short-lived processes (agents) push metrics to a Push Gateway. Long-lived processes (axe
  daemon) expose metrics via an HTTP endpoint for Prometheus to scrape.
- **33 metrics across 7 subsystems**: Comprehensive coverage of the full sase lifecycle.

## Configuration

Telemetry is configured under the `telemetry` key in `sase.yml`:

```yaml
telemetry:
  enabled: false # Toggle telemetry on/off globally
  prometheus:
    exposition_port: 9464 # HTTP server port for axe and agents
    pushgateway_url: "localhost:9091" # Push Gateway address
  health_thresholds:
    error_rate_warn: 10.0 # % threshold for warn status
    error_rate_critical: 25.0 # % threshold for critical status
    retry_rate_warn: 10.0
    retry_rate_critical: 25.0
    p95_latency_warn: 300.0 # seconds
    p95_latency_critical: 600.0
```

| Field                                       | Type  | Default          | Description                                  |
| ------------------------------------------- | ----- | ---------------- | -------------------------------------------- |
| `telemetry.enabled`                         | bool  | `false`          | Enable or disable telemetry globally.        |
| `telemetry.prometheus.exposition_port`      | int   | `9464`           | HTTP server port for metric exposition.      |
| `telemetry.prometheus.pushgateway_url`      | str   | `localhost:9091` | Prometheus Push Gateway address.             |
| `telemetry.health_thresholds.*_warn`        | float | varies           | Percentage threshold for WARN health status. |
| `telemetry.health_thresholds.*_critical`    | float | varies           | Percentage threshold for CRITICAL status.    |
| `telemetry.health_thresholds.p95_latency_*` | float | 300/600          | P95 latency thresholds in seconds.           |

Source: `src/sase/default_config.yml`, `src/sase/telemetry/_config.py`

## CLI Commands

### `sase telemetry status`

Quick health check and configuration display. Shows telemetry enabled/disabled status, metric counts by type, and
reachability of the Push Gateway and HTTP exposition server.

```bash
sase telemetry status
```

### `sase telemetry list`

Display the metric catalog from internal definitions, grouped by subsystem.

```bash
sase telemetry list                      # All metrics
sase telemetry list -s "Agent Lifecycle" # Filter by subsystem
sase telemetry list -t counter           # Filter by type (counter, gauge, histogram)
```

| Flag              | Values                          | Default | Description           |
| ----------------- | ------------------------------- | ------- | --------------------- |
| `-s, --subsystem` | subsystem name                  | -       | Filter to a subsystem |
| `-t, --type`      | `counter`, `gauge`, `histogram` | -       | Filter by metric type |

### `sase telemetry snapshot`

Fetch and display current metric values from the Push Gateway or exposition endpoint.

```bash
sase telemetry snapshot                          # Rich table (default)
sase telemetry snapshot -f json                  # JSON output
sase telemetry snapshot -f prometheus            # Raw Prometheus text format
sase telemetry snapshot -S pushgateway           # Force pushgateway source
```

| Flag              | Values                              | Default | Description         |
| ----------------- | ----------------------------------- | ------- | ------------------- |
| `-S, --source`    | `auto`, `pushgateway`, `exposition` | `auto`  | Data source         |
| `-f, --format`    | `rich`, `json`, `prometheus`        | `rich`  | Output format       |
| `-s, --subsystem` | subsystem name                      | -       | Filter by subsystem |

### `sase telemetry dashboard`

Live auto-refreshing TUI dashboard with two modes: summary (default) and charts.

```bash
sase telemetry dashboard                  # Summary mode, 5s refresh
sase telemetry dashboard -c               # Charts mode with historical data
sase telemetry dashboard -c -r 24h        # Charts over last 24 hours
sase telemetry dashboard -c -s "LLM Provider"  # Focus on one subsystem
sase telemetry dashboard -i 10            # 10-second refresh interval
```

| Flag              | Values                              | Default | Description                                 |
| ----------------- | ----------------------------------- | ------- | ------------------------------------------- |
| `-i, --interval`  | int (seconds)                       | `5`     | Refresh interval                            |
| `-S, --source`    | `auto`, `pushgateway`, `exposition` | `auto`  | Data source                                 |
| `-c, --charts`    | flag                                | -       | Enable charts mode with historical data     |
| `-r, --range`     | `1h`, `6h`, `24h`, `7d`             | `1h`    | Time range for charts                       |
| `-s, --subsystem` | subsystem name                      | -       | Focus on a single subsystem (larger charts) |

**Summary mode** shows styled stat panels with color-coded gauges (Active Agents, Active Workspaces, Active Beads) and
compact subsystem metric tables.

**Charts mode** (`-c`) renders historical line and bar charts via Prometheus range queries, showing: Agent Run Duration,
Active Agents, Agent Throughput, LLM Token Usage, LLM Latency, and Error Rate. Falls back to summary mode when
Prometheus is unreachable.

### `sase telemetry health`

Traffic-light health assessment with OK/WARN/CRITICAL status for each subsystem based on configured thresholds.

```bash
sase telemetry health                    # Rich output
sase telemetry health -j                 # Machine-readable JSON
```

| Flag           | Values                              | Default | Description |
| -------------- | ----------------------------------- | ------- | ----------- |
| `-j, --json`   | flag                                | -       | JSON output |
| `-S, --source` | `auto`, `pushgateway`, `exposition` | `auto`  | Data source |

Exit codes: `0` (healthy), `1` (degraded/warn), `2` (critical).

### `sase telemetry export-config`

Export the bundled monitoring stack (Docker Compose, Prometheus config, Grafana dashboard) to a local directory.

```bash
sase telemetry export-config                     # Default: ./sase-monitoring/
sase telemetry export-config -o /tmp/monitoring  # Custom output directory
sase telemetry export-config -f                  # Overwrite existing
```

| Flag               | Values | Default              | Description                   |
| ------------------ | ------ | -------------------- | ----------------------------- |
| `-o, --output-dir` | path   | `./sase-monitoring/` | Target directory              |
| `-f, --force`      | flag   | -                    | Overwrite target if it exists |

After exporting, start the stack with:

```bash
cd sase-monitoring && docker compose up -d
```

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    sase telemetry CLI                     │
│  status · list · snapshot · dashboard · health · export   │
├──────────────────────────────────────────────────────────┤
│                       Scrape Client                       │
│          (fetches from Push Gateway or exposition)        │
├─────────────────────┬────────────────────────────────────┤
│   Push Gateway      │   HTTP Exposition Server           │
│ (short-lived procs) │   (long-lived: axe daemon)         │
├─────────────────────┴────────────────────────────────────┤
│                  Prometheus Metrics Layer                  │
│        metrics.py (26 singletons, stub/real switch)       │
├──────────────────────────────────────────────────────────┤
│                   Instrumentation Points                  │
│  Agent · LLM · Axe · Hooks · Beads · VCS · Notifications │
└──────────────────────────────────────────────────────────┘
```

### Source Layout

| File / Directory                   | Purpose                                       |
| ---------------------------------- | --------------------------------------------- |
| `src/sase/telemetry/__init__.py`   | Public API exports                            |
| `src/sase/telemetry/metrics.py`    | Module-level metric singletons (26 attrs)     |
| `src/sase/telemetry/_registry.py`  | Init, Push Gateway integration, atexit        |
| `src/sase/telemetry/_stubs.py`     | No-op stub classes (zero overhead)            |
| `src/sase/telemetry/_config.py`    | Configuration loading from sase.yml           |
| `src/sase/telemetry/catalog.py`    | Structured metric catalog and grouping        |
| `src/sase/telemetry/scrape.py`     | HTTP client and Prometheus text parser        |
| `src/sase/telemetry/prom_query.py` | Prometheus HTTP API client (range queries)    |
| `src/sase/telemetry/charts.py`     | Terminal chart rendering via plotext          |
| `src/sase/telemetry/cli_*.py`      | CLI subcommand handlers                       |
| `src/sase/telemetry/monitoring/`   | Bundled Docker Compose + Prometheus + Grafana |

## Metric Catalog

33 metrics organized into 7 subsystems:

### Agent Lifecycle

| Prometheus Name                   | Type      | Labels                         | Description             |
| --------------------------------- | --------- | ------------------------------ | ----------------------- |
| `sase_agent_runs_total`           | counter   | llm_provider, status, workflow | Total agent runs        |
| `sase_agent_run_duration_seconds` | histogram | llm_provider, workflow         | Agent run duration      |
| `sase_agent_active`               | gauge     | llm_provider, project          | Currently active agents |
| `sase_agent_spawns_total`         | counter   | llm_provider, project          | Total agent spawns      |
| `sase_agent_kills_total`          | counter   | reason                         | Total agent kills       |

### LLM Provider

| Prometheus Name                        | Type      | Labels               | Description             |
| -------------------------------------- | --------- | -------------------- | ----------------------- |
| `sase_llm_invocations_total`           | counter   | provider, status     | Total LLM invocations   |
| `sase_llm_invocation_duration_seconds` | histogram | provider             | Invocation duration     |
| `sase_llm_errors_total`                | counter   | provider, error_type | LLM errors              |
| `sase_llm_retries_total`               | counter   | provider             | LLM retries             |
| `sase_llm_input_tokens_total`          | counter   | provider             | Input tokens consumed   |
| `sase_llm_output_tokens_total`         | counter   | provider             | Output tokens generated |
| `sase_llm_cache_read_tokens_total`     | counter   | provider             | Cache-read tokens       |

### Axe Orchestrator

| Prometheus Name                      | Type      | Labels     | Description         |
| ------------------------------------ | --------- | ---------- | ------------------- |
| `sase_axe_cycles_total`              | counter   | cycle_type | Total axe cycles    |
| `sase_axe_cycle_duration_seconds`    | histogram | cycle_type | Cycle duration      |
| `sase_axe_lumberjacks_active`        | gauge     | -          | Active lumberjacks  |
| `sase_axe_lumberjack_restarts_total` | counter   | -          | Lumberjack restarts |
| `sase_axe_errors_total`              | counter   | error_type | Axe errors          |

### Hooks / Mentors / Workflows

| Prometheus Name                  | Type      | Labels            | Description               |
| -------------------------------- | --------- | ----------------- | ------------------------- |
| `sase_hook_executions_total`     | counter   | hook_type, status | Hook executions           |
| `sase_hook_duration_seconds`     | histogram | hook_type         | Hook duration             |
| `sase_hook_retries_total`        | counter   | hook_type         | Hook retries              |
| `sase_mentor_executions_total`   | counter   | status            | Mentor executions         |
| `sase_workflow_executions_total` | counter   | workflow, status  | Workflow executions       |
| `sase_workflow_duration_seconds` | histogram | workflow          | Workflow duration         |
| `sase_zombie_detections_total`   | counter   | -                 | Zombie process detections |

### Beads

| Prometheus Name                      | Type    | Labels                 | Description             |
| ------------------------------------ | ------- | ---------------------- | ----------------------- |
| `sase_bead_operations_total`         | counter | operation              | Bead CRUD operations    |
| `sase_bead_status_transitions_total` | counter | from_status, to_status | Bead status transitions |
| `sase_bead_active`                   | gauge   | project, status        | Active beads            |

### VCS / Workspace

| Prometheus Name                     | Type    | Labels                      | Description            |
| ----------------------------------- | ------- | --------------------------- | ---------------------- |
| `sase_vcs_commits_total`            | counter | provider, type              | VCS commits            |
| `sase_vcs_operations_total`         | counter | provider, operation, status | VCS operations         |
| `sase_workspace_acquisitions_total` | counter | project                     | Workspace acquisitions |
| `sase_workspace_releases_total`     | counter | project                     | Workspace releases     |
| `sase_workspace_active`             | gauge   | project                     | Active workspaces      |

### Notifications

| Prometheus Name                 | Type    | Labels       | Description        |
| ------------------------------- | ------- | ------------ | ------------------ |
| `sase_notifications_sent_total` | counter | type, status | Notifications sent |

## Monitoring Stack

The `sase telemetry export-config` command exports a ready-to-use Docker Compose stack:

### Services

| Service      | Port | Description                                                    |
| ------------ | ---- | -------------------------------------------------------------- |
| Push Gateway | 9091 | Receives metrics from short-lived agent processes              |
| Prometheus   | 9090 | Scrapes Push Gateway and axe exposition server; stores metrics |
| Grafana      | 3000 | Pre-configured dashboard with panels for all subsystems        |

### Prometheus Scrape Configuration

Prometheus is configured with two scrape jobs:

- **`sase_axe`**: Scrapes the axe daemon's HTTP exposition server (port 9464)
- **`pushgateway`**: Scrapes the Push Gateway (port 9091)

Global scrape interval: 15 seconds.

### Alerting Rules

20+ alert rules covering:

- Agent error rate thresholds (10%, 25%)
- Agent p95 latency thresholds (300s, 600s)
- LLM error rate and retry rate
- Axe cycle errors
- Hook retry rates
- Workspace release failures

Alert labels use `severity: warning` and `severity: critical`.

### Grafana Dashboard

A pre-built Grafana dashboard is automatically provisioned with panels for all telemetry subsystems, accessible at
`http://localhost:3000` after starting the stack.

## Integration Points

Telemetry is instrumented across the codebase:

| Subsystem     | Location                            | What is tracked                      |
| ------------- | ----------------------------------- | ------------------------------------ |
| Agent         | `src/sase/agent/launcher.py`        | Runs, duration, spawns, kills        |
| LLM Provider  | `src/sase/llm_provider/_invoke.py`  | Invocations, tokens, errors, retries |
| Axe           | `src/sase/axe/orchestrator.py`      | Cycles, errors, lumberjack activity  |
| Hooks/Mentors | Hook execution modules              | Execution counts, durations, retries |
| Beads         | `src/sase/bead/project.py`          | CRUD operations, status transitions  |
| VCS           | VCS operation modules               | Commits, operations                  |
| Notifications | `src/sase/notifications/senders.py` | Notifications sent                   |

The axe orchestrator calls `init_telemetry(start_http_server=True)` on startup to begin exposing metrics. Agent
processes use `push_metrics()` to send data to the Push Gateway on exit via an `atexit` handler.

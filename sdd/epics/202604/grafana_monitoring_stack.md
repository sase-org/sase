---
create_time: 2026-04-08 01:05:07
status: done
bead_id: sase-f
prompt: sdd/prompts/202604/grafana_monitoring_stack.md
---

# Plan: Prometheus Alerting Rules + Grafana Dashboard Provisioning

## Goal

Ship a turnkey monitoring stack that lets users go from `sase telemetry` metrics to a full Grafana dashboard and
Prometheus alerting rules with minimal effort. The deliverables:

1. **Docker Compose stack** — Prometheus + Push Gateway + Grafana, pre-wired
2. **Prometheus alerting rules** — aligned with existing `health_thresholds` config
3. **Grafana dashboard JSON** — panels covering all 8 subsystems (33 metrics)
4. **`sase telemetry export-config` CLI** — writes all config files to a target directory

## Where Things Live

All monitoring infrastructure config will live under `src/sase/telemetry/monitoring/` as bundled package data. This
keeps the config co-located with the telemetry code and makes it accessible via `importlib.resources` for the
`export-config` CLI command.

```
src/sase/telemetry/monitoring/
  docker-compose.yml
  prometheus/
    prometheus.yml        # scrape config
    alerts.yml            # alerting rules
  grafana/
    provisioning/
      datasources/
        prometheus.yml    # auto-configure Prometheus datasource
      dashboards/
        dashboard.yml     # dashboard provisioning config
    dashboards/
      sase.json           # the main dashboard
```

---

## Phase 1: Docker Compose + Prometheus Scrape Config

**Bead:** `sase-f.1`

Create the foundational infrastructure that gets Prometheus + Push Gateway + Grafana running with a single
`docker compose up`.

### Deliverables

- `src/sase/telemetry/monitoring/docker-compose.yml` — Three services:
  - **pushgateway** (prom/pushgateway, port 9091)
  - **prometheus** (prom/prometheus, port 9090) — mounts `prometheus/` for config
  - **grafana** (grafana/grafana, port 3000) — mounts `grafana/` for provisioning

- `src/sase/telemetry/monitoring/prometheus/prometheus.yml` — Scrape config:
  - Job `sase_axe`: scrapes `host.docker.internal:9464` (the Axe HTTP exposition endpoint)
  - Job `pushgateway`: scrapes the push gateway container with `honor_labels: true`
  - `rule_files` entry pointing to `alerts.yml` (populated in Phase 2)
  - 15s scrape interval

- `src/sase/telemetry/monitoring/grafana/provisioning/datasources/prometheus.yml` — Auto-configures Prometheus as the
  default Grafana datasource (URL: `http://prometheus:9090`)

- `src/sase/telemetry/monitoring/grafana/provisioning/dashboards/dashboard.yml` — Tells Grafana to load dashboards from
  `/var/lib/grafana/dashboards/`

- Empty placeholder files where Phase 2 and 3 will add content:
  - `src/sase/telemetry/monitoring/prometheus/alerts.yml` (empty `groups: []`)
  - `src/sase/telemetry/monitoring/grafana/dashboards/sase.json` (minimal valid dashboard)

### Key Design Decisions

- Use `host.docker.internal` for the Axe exposition endpoint since sase runs on the host, not in Docker. Add
  `extra_hosts` mapping for Linux compatibility.
- Grafana provisioning (datasources + dashboard directory) means zero manual setup after `docker compose up`.
- The Push Gateway service has no persistence volume — this is intentional for a dev/local monitoring setup. Users who
  want persistence can add a volume.

---

## Phase 2: Prometheus Alerting Rules

**Bead:** `sase-f.2`

Write alerting rules that mirror the existing `health_thresholds` config and cover the key failure/degradation
scenarios.

### Deliverables

- `src/sase/telemetry/monitoring/prometheus/alerts.yml` — Alert rules organized by subsystem:

#### Agent Alerts

- **SaseAgentHighErrorRate** —
  `rate(sase_agent_runs_total{status="error"}[5m]) / rate(sase_agent_runs_total[5m]) > 0.10` (warn) / `> 0.25`
  (critical). Mirrors `error_rate_warn`/`error_rate_critical`.
- **SaseAgentRunSlow** — `histogram_quantile(0.95, rate(sase_agent_run_duration_seconds_bucket[5m])) > 300` (warn) /
  `> 600` (critical). Mirrors `p95_latency_warn`/`p95_latency_critical`.

#### LLM Alerts

- **SaseLlmHighErrorRate** — Same error rate thresholds applied to `sase_llm_errors_total / sase_llm_invocations_total`.
- **SaseLlmHighRetryRate** — `rate(sase_llm_retries_total[5m]) / rate(sase_llm_invocations_total[5m])` against
  `retry_rate_warn`/`retry_rate_critical`.

#### Axe Alerts

- **SaseAxeErrors** — `increase(sase_axe_errors_total[5m]) >= 5` (critical). Matches the hardcoded threshold in
  `cli_health.py`.
- **SaseAxeLumberjackRestartStorm** — `increase(sase_axe_lumberjack_restarts_total[5m]) >= 3`. Detects thrashing.

#### Hook Alerts

- **SaseHookHighRetryRate** — Same retry rate thresholds applied to hooks.

#### Operational Alerts

- **SaseZombieDetected** — `increase(sase_zombie_detections_total[5m]) > 0`. Any zombie detection is worth alerting on.
- **SasePushGatewayDown** — `up{job="pushgateway"} == 0` for 2 minutes.

### Key Design Decisions

- Thresholds are hardcoded in the YAML to match the defaults in `default_config.yml`. This is intentional — Prometheus
  alerting rules are static config, not dynamically generated from sase config. Document the correspondence clearly in
  comments.
- Use `for: 2m` on rate-based alerts to avoid firing on transient spikes.
- All alerts include `severity` label (warning/critical) and descriptive `summary`/`description` annotations for
  Alertmanager routing.

---

## Phase 3: Grafana Dashboard JSON

**Bead:** `sase-f.3`

Build a comprehensive Grafana dashboard with panels organized by subsystem.

### Deliverables

- `src/sase/telemetry/monitoring/grafana/dashboards/sase.json` — A provisioned Grafana dashboard with:

#### Row 1: Overview

- **Active Agents** (stat panel) — `sase_agent_active`
- **Active Workspaces** (stat panel) — `sase_workspace_active`
- **Active Beads** (stat panel) — `sase_bead_active`
- **Active Lumberjacks** (stat panel) — `sase_axe_lumberjacks_active`

#### Row 2: Agent Lifecycle

- **Agent Runs/min** (time series) — `rate(sase_agent_runs_total[5m])` split by `status`
- **Agent Run Duration Percentiles** (time series) — p50/p95/p99 from `sase_agent_run_duration_seconds`
- **Agent Error Rate %** (time series) — errors/total \* 100

#### Row 3: LLM Provider

- **LLM Invocations/min** (time series) — `rate(sase_llm_invocations_total[5m])` by `provider`
- **LLM Error Rate %** (time series) — errors/invocations by `provider`
- **LLM Latency Percentiles** (time series) — from `sase_llm_invocation_duration_seconds`
- **Token Consumption** (stacked time series) — input + output tokens by `provider`

#### Row 4: Axe Orchestrator

- **Axe Cycles/min** (time series) — by `cycle_type`
- **Axe Cycle Duration** (time series) — p95 from histogram
- **Axe Errors** (time series) — `rate(sase_axe_errors_total[5m])` by `error_type`
- **Lumberjack Restarts** (time series) — `increase(sase_axe_lumberjack_restarts_total[1h])`

#### Row 5: Hooks & Workflows

- **Hook Executions/min** (time series) — by `hook_type`, `status`
- **Hook Duration Percentiles** (time series) — from histogram
- **Workflow Executions** (time series) — by `workflow`, `status`
- **Hook Retry Rate %** (time series)

#### Row 6: Beads & VCS

- **Bead Operations** (time series) — by `operation`
- **Bead Status Transitions** (table/heatmap) — `from_status` x `to_status`
- **VCS Operations** (time series) — by `provider`, `operation`, `status`
- **VCS Commits** (time series) — by `provider`, `type`

#### Row 7: Notifications

- **Notifications Sent** (time series) — by `type`, `status`

### Key Design Decisions

- Use Grafana dashboard JSON format (not the API model) — this is what Grafana provisioning expects.
- Set `"editable": true` so users can customize after import.
- Use template variables for time range (`$__rate_interval`) but not for label filtering — keep it simple for v1.
- Dashboard UID: `sase-overview` (stable for cross-linking).

---

## Phase 4: `sase telemetry export-config` CLI Command

**Bead:** `sase-f.4`

Add a CLI command that copies the bundled monitoring config to a user-specified directory, making it trivial to get
started.

### Deliverables

- `src/sase/telemetry/cli_export_config.py` — Handler for the new subcommand:

  ```
  sase telemetry export-config [-o/--output-dir DIR]
  ```

  - Default output: `./sase-monitoring/`
  - Copies the entire `monitoring/` tree from package data to the target directory
  - Uses `importlib.resources` to access bundled files
  - Prints a summary of what was written and next-steps instructions (docker compose up, etc.)
  - Warns (does not overwrite) if the target directory already exists, unless `--force`/`-f` is passed

- Register the subcommand in `parser_commands.py` (add `export-config` parser with `-o`/`--output-dir` and
  `-f`/`--force` args)

- Add dispatch in `telemetry_handler.py` (new `if sub == "export-config"` branch)

- `tests/telemetry/test_cli_export_config.py` — Tests:
  - Config files are written to the specified output directory
  - Directory structure is correct
  - `--force` overwrites existing directory
  - Default output directory is `./sase-monitoring/`
  - All expected files are present (docker-compose.yml, prometheus.yml, alerts.yml, sase.json, provisioning configs)

### Key Design Decisions

- Use `importlib.resources` (not `__file__` relative paths) to access package data — this works correctly with installed
  packages, editable installs, and zip imports.
- Add `monitoring/` to package data in `pyproject.toml` (hatchling config).
- The output is a standalone directory that users can `cd` into and `docker compose up` — no sase dependency at runtime
  for the monitoring stack itself.

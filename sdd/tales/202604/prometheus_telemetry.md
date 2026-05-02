---
create_time: 2026-04-07 22:02:29
status: wip
prompt: sdd/prompts/202604/prometheus_telemetry.md
---

# Plan: Prometheus Telemetry Integration

## Overview

Add Prometheus metrics to sase, covering the axe daemon (HTTP exposition), agent runners (push gateway), and key
subsystems (LLM providers, hooks/mentors, beads, workspaces). The integration complements existing JSONL logs and
`AxeMetrics`/`LumberjackMetrics` dataclasses — it does not replace them.

The `prometheus_client` library (zero dependencies) is the only new dependency.

## Phase 1: Core Telemetry Module

**Goal:** Create `src/sase/telemetry/` with metric definitions, registry helpers, and configuration. Everything else
depends on this.

**Files to create:**

- `src/sase/telemetry/__init__.py` — re-exports public API
- `src/sase/telemetry/config.py` — `TelemetryConfig` dataclass, loaded from sase config's `telemetry` section
  - Fields: `enabled: bool`, `pushgateway_url: str`, `exposition_port: int`
  - A `get_telemetry_config()` function that reads from the sase config system
  - When `enabled=False`, all metric operations become no-ops (use `prometheus_client.values.MutexValue` or simply gate
    at the call sites — the library handles unregistered metrics gracefully)
- `src/sase/telemetry/registry.py` — registry management
  - `start_exposition_server(port)` — wraps `prometheus_client.start_http_server()` for axe daemon
  - `push_metrics(job, grouping_key)` — wraps `pushadd_to_gateway()` with try/except (never crashes on failure)
  - `register_push_on_exit(job, **grouping_key)` — `atexit.register()` wrapper for agent runners
  - Uses dedicated `CollectorRegistry()` for push gateway, not the global registry
- `src/sase/telemetry/metrics.py` — ALL metric definitions as module-level singletons

**Metric definitions (module-level singletons in metrics.py):**

```
# Agent lifecycle
AGENT_RUNS_TOTAL          Counter   [llm_provider, status, workflow]
AGENT_RUN_DURATION        Histogram [llm_provider, workflow]         buckets=[10,30,60,120,300,600,1800,3600]
AGENT_ACTIVE              Gauge     [llm_provider, project]
AGENT_SPAWNS_TOTAL        Counter   [llm_provider, project]
AGENT_KILLS_TOTAL         Counter   [reason]

# LLM provider
LLM_INVOCATIONS_TOTAL     Counter   [provider, status]
LLM_INVOCATION_DURATION   Histogram [provider]
LLM_ERRORS_TOTAL          Counter   [provider, error_type]
LLM_RETRIES_TOTAL         Counter   [provider]

# Axe orchestrator
AXE_CYCLES_TOTAL          Counter   [cycle_type]
AXE_CYCLE_DURATION        Histogram [cycle_type]
AXE_LUMBERJACKS_ACTIVE    Gauge     []
AXE_LUMBERJACK_RESTARTS   Counter   []
AXE_ERRORS_TOTAL          Counter   [error_type]

# Hooks / mentors / workflows
HOOK_EXECUTIONS_TOTAL     Counter   [hook_type, status]
HOOK_DURATION             Histogram [hook_type]
HOOK_RETRIES_TOTAL        Counter   [hook_type]
MENTOR_EXECUTIONS_TOTAL   Counter   [status]
WORKFLOW_EXECUTIONS_TOTAL Counter   [workflow, status]
WORKFLOW_DURATION          Histogram [workflow]
ZOMBIE_DETECTIONS_TOTAL   Counter   []

# Beads
BEAD_OPERATIONS_TOTAL     Counter   [operation]
BEAD_STATUS_TRANSITIONS   Counter   [from_status, to_status]
BEAD_ACTIVE               Gauge     [project, status]

# VCS / workspace
VCS_COMMITS_TOTAL         Counter   [provider, type]
VCS_OPERATIONS_TOTAL      Counter   [provider, operation, status]
WORKSPACE_ACQUISITIONS    Counter   [project]
WORKSPACE_RELEASES        Counter   [project]
WORKSPACE_ACTIVE          Gauge     [project]
```

**Files to modify:**

- `pyproject.toml` — add `prometheus-client>=0.20.0` to dependencies
- `src/sase/default_config.yml` — add `telemetry` section:
  ```yaml
  telemetry:
    enabled: false
    prometheus:
      pushgateway_url: "localhost:9091"
      exposition_port: 9102
  ```

**Tests to create:**

- `tests/telemetry/test_config.py` — config loading, defaults, disabled state
- `tests/telemetry/test_registry.py` — exposition server start, push_metrics with mock gateway, graceful failure when
  gateway is down
- `tests/telemetry/test_metrics.py` — verify all metrics are registered, correct types, label names

## Phase 2: Axe Orchestrator & Lumberjack Instrumentation

**Goal:** Wire Prometheus into the axe daemon — the highest-value integration since it's long-running and directly
scrapeable.

**Files to modify:**

- `src/sase/axe/orchestrator.py`
  - In `run()`: call `start_exposition_server(config.exposition_port)` after signal setup (after line ~151), gated on
    `telemetry.enabled`
  - In the main loop: set `AXE_LUMBERJACKS_ACTIVE` gauge to current child count
  - On child restart: increment `AXE_LUMBERJACK_RESTARTS`
  - On error: increment `AXE_ERRORS_TOTAL`

- `src/sase/axe/lumberjack.py`
  - In `_run_tick()`: wrap cycle execution with `AXE_CYCLE_DURATION.labels(cycle_type=...).time()` context manager
  - After line 187 (`self._metrics.cycles_run += 1`): increment `AXE_CYCLES_TOTAL`
  - After line 236 (`self._metrics.errors_encountered += 1`): increment `AXE_ERRORS_TOTAL`

- `src/sase/axe/hook_jobs.py` — in `HookJobRunner`:
  - After line 92 (`self.metrics.hooks_started += hooks_started`): increment `HOOK_EXECUTIONS_TOTAL`
  - After line 115 (`self.metrics.mentors_started += mentors_started`): increment `MENTOR_EXECUTIONS_TOTAL`
  - After line 144 (`self.metrics.workflows_started += started`): increment `WORKFLOW_EXECUTIONS_TOTAL`
  - After line 172 (`self.metrics.zombies_detected += len(updates)`): increment `ZOMBIE_DETECTIONS_TOTAL`

**Design note:** Prometheus counters are incremented _alongside_ existing `AxeMetrics`/`LumberjackMetrics` increments —
no removal of the existing disk-based metrics system.

**Tests:**

- `tests/axe/test_telemetry.py` — verify orchestrator starts exposition server, cycle/hook/zombie metrics increment
  correctly using `prometheus_client.REGISTRY.get_sample_value()`

## Phase 3: Agent Lifecycle & LLM Provider Instrumentation

**Goal:** Instrument the agent execution path and LLM invocation layer. Register push-on-exit for agent runners.

**Files to modify:**

- `src/sase/axe/run_agent_runner.py`
  - Near line 88 (start_time): increment `AGENT_ACTIVE` gauge, call `register_push_on_exit()`
  - After execution completes (~line 302): observe `AGENT_RUN_DURATION`, increment `AGENT_RUNS_TOTAL` with status label,
    decrement `AGENT_ACTIVE`

- `src/sase/agent/launcher.py`
  - In `spawn_agent_subprocess()` after successful Popen: increment `AGENT_SPAWNS_TOTAL`

- `src/sase/llm_provider/_invoke.py`
  - Wrap `provider.invoke()` call (~line 170-177) with timing:
    ```python
    with LLM_INVOCATION_DURATION.labels(provider=provider_name).time():
        result = provider.invoke(...)
    LLM_INVOCATIONS_TOTAL.labels(provider=provider_name, status='success').inc()
    ```
  - In error handling paths (~line 190-222): increment `LLM_ERRORS_TOTAL.labels(provider=provider_name, error_type=...)`
    and `LLM_INVOCATIONS_TOTAL.labels(provider=..., status='error')`

- `src/sase/llm_provider/base.py`
  - Consider adding retry counting in the base class if there's a retry loop, incrementing `LLM_RETRIES_TOTAL`

**Tests:**

- `tests/llm_provider/test_telemetry.py` — verify invocation counter/histogram/error metrics via mocked provider calls
- `tests/agent/test_telemetry.py` — verify spawn counter, active gauge, run duration histogram

## Phase 4: Remaining Subsystems (Beads, Workspace, VCS)

**Goal:** Instrument bead operations, workspace management, and VCS operations.

**Files to modify:**

- `src/sase/bead/project.py`
  - In `create()` after line 108: increment `BEAD_OPERATIONS_TOTAL.labels(operation='create')`
  - In `update()` after line 138: increment `BEAD_OPERATIONS_TOTAL.labels(operation='update')`
  - In `close()`: increment `BEAD_OPERATIONS_TOTAL.labels(operation='close')` and
    `BEAD_STATUS_TRANSITIONS.labels(from_status=old, to_status='CLOSED')`

- `src/sase/running_field/_operations.py`
  - In `claim_workspace()`: increment `WORKSPACE_ACQUISITIONS` on success, inc `WORKSPACE_ACTIVE`
  - In `release_workspace()`: increment `WORKSPACE_RELEASES` on success, dec `WORKSPACE_ACTIVE`

- VCS provider layer (find the commit/mail/submit operations):
  - Increment `VCS_COMMITS_TOTAL` and `VCS_OPERATIONS_TOTAL` at appropriate points

**Tests:**

- `tests/bead/test_telemetry.py` — verify bead CRUD metrics
- `tests/running_field/test_telemetry.py` — verify workspace claim/release metrics

## Phase 5: Integration Testing & Polish

**Goal:** End-to-end validation, `just check` pass, documentation updates.

**Tasks:**

- Integration test: start axe orchestrator with telemetry enabled, scrape `/metrics` endpoint, verify expected metric
  families are present
- Integration test: mock pushgateway server, run agent completion path, verify metrics are pushed
- Run `just check` and fix any lint/type/test issues across all phases
- Update `sdd/research/202604/prometheus_telemetry.md` with implementation notes (what was built, any deviations from the research
  plan)
- Verify all metrics follow naming convention: `sase_<subsystem>_<name>_<unit>`
- Verify all labels are bounded enums (no unbounded cardinality)

## Risk & Design Decisions

- **Telemetry disabled by default** — `enabled: false` in default config. No performance impact for users who don't want
  it.
- **Never crash on metrics failure** — all push gateway calls wrapped in try/except. HTTP server failure during axe
  startup should log a warning but not prevent axe from running.
- **No removal of existing metrics** — `AxeMetrics`/`LumberjackMetrics` disk writes continue unchanged. Prometheus
  counters are incremented alongside them.
- **Module-level singletons** — metrics defined once at module level, never inside functions (avoids `ValueError` on
  re-registration).
- **Bounded labels only** — provider (~3 values), status (~4 values), cycle_type (~3 values), etc. No PIDs, branch
  names, error messages, or file paths as labels.

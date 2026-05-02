---
status: draft
---

# Prometheus Telemetry Integration

## Goal

Add opt-in Prometheus metrics to sase so that agent runs, axe/lumberjack cycles, LLM invocations, hooks, beads, VCS
operations, and workspaces are observable via real-time dashboards and alerting. The existing JSONL logs and JSON state
files remain untouched; Prometheus complements them.

## Design Decisions

### Opt-in with Zero-Cost Disabled Path

Telemetry is off by default (`telemetry.enabled: false` in `default_config.yml`). When disabled, all metric recording
calls must be true no-ops: no `prometheus_client` import at module load, no metric object creation, no label allocation.
This is achieved with a thin wrapper layer that checks the enabled flag once at init and either returns real
`prometheus_client` metric objects or lightweight stub objects whose `inc()`, `observe()`, `set()`, `time()`, `labels()`
methods are all no-ops.

### Exposition Strategy

| Runtime                         | Strategy                                                 | Rationale                                       |
| ------------------------------- | -------------------------------------------------------- | ----------------------------------------------- |
| `axe` orchestrator              | HTTP server (`start_http_server()`) on configurable port | Long-lived; Prometheus scrapes on interval      |
| Agent runners                   | `pushadd_to_gateway()` on exit via `atexit`              | Medium-lived; push final metrics on completion  |
| CLI commands (`commit`, `bead`) | Push Gateway or skip                                     | Most too brief; only instrument high-value ones |

Push Gateway uses a dedicated `CollectorRegistry()` (not the global one), `pushadd_to_gateway()` (POST/merge, not
PUT/replace), and all push calls are wrapped in try/except so a downed pushgateway never crashes anything.

### Metric Naming Convention

All metrics: `sase_<subsystem>_<name>_<unit>`. Subsystems: `agent`, `axe`, `hook`, `llm`, `bead`, `vcs`, `workspace`,
`notification`. Units: `_seconds` for durations, `_total` suffix for counters. Histograms for all latencies (not
Summary, since Python's Summary can't compute quantiles).

### Label Cardinality

Every label value comes from a known bounded enum. No PIDs, branch names, error messages, or file paths as labels.
Target <500 series per metric.

### Module-Level Singletons

All metrics are defined as module-level singletons in `src/sase/telemetry/metrics.py`. Never created inside functions
(would raise `ValueError` on second call).

## New Module: `src/sase/telemetry/`

```
src/sase/telemetry/
    __init__.py          # re-exports: init_telemetry, metrics, push_metrics
    _config.py           # TelemetryConfig dataclass, load from merged config
    _registry.py         # registry management, push/exposition helpers
    _stubs.py            # no-op stub classes for disabled mode
    metrics.py           # metric definitions (module-level singletons)
```

### `_config.py`

```python
@dataclass
class TelemetryConfig:
    enabled: bool = False
    exposition_port: int = 9464
    pushgateway_url: str = "localhost:9091"
```

Loaded from `telemetry:` section of merged config. Accessed via `get_telemetry_config()` which caches after first call.

### `_stubs.py`

Lightweight no-op classes: `StubCounter`, `StubGauge`, `StubHistogram` that match the `prometheus_client` API surface
used by sase (`.inc()`, `.dec()`, `.set()`, `.observe()`, `.labels()`, `.time()`). `labels()` returns `self` so chained
calls like `METRIC.labels(foo="bar").inc()` work as no-ops.

### `_registry.py`

- `init_telemetry()` — Called once at process startup. If enabled, imports `prometheus_client`, creates real metrics. If
  disabled, populates `metrics.py` singletons with stubs. For axe, starts the HTTP exposition server.
- `push_metrics(job, grouping_key)` — For agent runners / CLI. Uses dedicated `CollectorRegistry`, wraps in try/except.
- `register_push_on_exit(job, **grouping_key)` — Registers `atexit` handler to push on process exit.

### `metrics.py`

Module-level variables initialized to stubs. `init_telemetry()` replaces them with real prometheus_client objects when
enabled. Grouped by subsystem:

**Agent Lifecycle** (5 metrics):

- `AGENT_RUNS` — Counter, labels: `llm_provider`, `status`, `workflow`
- `AGENT_RUN_DURATION` — Histogram, labels: `llm_provider`, `workflow`, buckets:
  `[10, 30, 60, 120, 300, 600, 1800, 3600]`
- `AGENT_ACTIVE` — Gauge, labels: `llm_provider`, `project`
- `AGENT_SPAWNS` — Counter, labels: `llm_provider`, `project`
- `AGENT_KILLS` — Counter, labels: `reason`

**LLM Provider** (4 metrics):

- `LLM_INVOCATIONS` — Counter, labels: `provider`, `status`
- `LLM_INVOCATION_DURATION` — Histogram, labels: `provider`
- `LLM_ERRORS` — Counter, labels: `provider`, `error_type`
- `LLM_RETRIES` — Counter, labels: `provider`

**Axe Orchestrator** (5 metrics):

- `AXE_CYCLES` — Counter, labels: `cycle_type`
- `AXE_CYCLE_DURATION` — Histogram, labels: `cycle_type`
- `AXE_LUMBERJACKS_ACTIVE` — Gauge
- `AXE_LUMBERJACK_RESTARTS` — Counter
- `AXE_ERRORS` — Counter, labels: `error_type`

**Hooks / Mentors / Workflows** (7 metrics):

- `HOOK_EXECUTIONS` — Counter, labels: `hook_type`, `status`
- `HOOK_DURATION` — Histogram, labels: `hook_type`
- `HOOK_RETRIES` — Counter, labels: `hook_type`
- `MENTOR_EXECUTIONS` — Counter, labels: `status`
- `WORKFLOW_EXECUTIONS` — Counter, labels: `workflow`, `status`
- `WORKFLOW_DURATION` — Histogram, labels: `workflow`
- `ZOMBIE_DETECTIONS` — Counter

**Beads** (3 metrics):

- `BEAD_OPERATIONS` — Counter, labels: `operation`
- `BEAD_STATUS_TRANSITIONS` — Counter, labels: `from_status`, `to_status`
- `BEAD_ACTIVE` — Gauge, labels: `project`, `status`

**VCS / Workspace** (5 metrics):

- `VCS_COMMITS` — Counter, labels: `provider`, `type`
- `VCS_OPERATIONS` — Counter, labels: `provider`, `operation`, `status`
- `WORKSPACE_ACQUISITIONS` — Counter, labels: `project`
- `WORKSPACE_RELEASES` — Counter, labels: `project`
- `WORKSPACE_ACTIVE` — Gauge, labels: `project`

**Notifications** (1 metric):

- `NOTIFICATIONS_SENT` — Counter, labels: `type`, `status`

## Config Addition

Add to `src/sase/default_config.yml`:

```yaml
telemetry:
  enabled: false
  prometheus:
    exposition_port: 9464
    pushgateway_url: "localhost:9091"
```

## Instrumentation Points

### Phase 1: Foundation (no instrumentation yet)

Create the `src/sase/telemetry/` package, add `prometheus_client` to `pyproject.toml` dependencies, add `telemetry:`
section to `default_config.yml`, implement config loading, stubs, registry management, and all metric definitions. Write
tests for config loading, stub behavior, and metric creation.

Files to create:

- `src/sase/telemetry/__init__.py`
- `src/sase/telemetry/_config.py`
- `src/sase/telemetry/_registry.py`
- `src/sase/telemetry/_stubs.py`
- `src/sase/telemetry/metrics.py`
- `tests/telemetry/__init__.py`
- `tests/telemetry/test_config.py`
- `tests/telemetry/test_stubs.py`
- `tests/telemetry/test_registry.py`
- `tests/telemetry/test_metrics.py`

Files to modify:

- `pyproject.toml` — add `prometheus_client` dependency
- `src/sase/default_config.yml` — add `telemetry:` section

### Phase 2: Axe / Lumberjack Instrumentation

Wire metrics into the axe daemon. The orchestrator starts the HTTP exposition server. Lumberjacks record cycle counts,
durations, chop executions, and errors.

Files to modify:

- `src/sase/axe/orchestrator.py` — Call `init_telemetry()` on startup; start exposition server; track
  `AXE_LUMBERJACKS_ACTIVE` gauge on spawn/exit; increment `AXE_LUMBERJACK_RESTARTS` on child restart
- `src/sase/axe/lumberjack.py` — In `_run_tick()`: increment `AXE_CYCLES` and observe `AXE_CYCLE_DURATION`. In
  `_handle_error()`: increment `AXE_ERRORS`. In chop execution: increment `HOOK_EXECUTIONS` / observe `HOOK_DURATION`
  based on chop type

### Phase 3: Agent Lifecycle Instrumentation

Wire metrics into agent spawning and execution. Agent runners push metrics on exit.

Files to modify:

- `src/sase/agent/launcher.py` — In `spawn_agent_subprocess()`: increment `AGENT_SPAWNS`. Set env var for telemetry
  config so child process can init
- `src/sase/axe/run_agent_runner.py` — Call `init_telemetry()` at start; `register_push_on_exit()`. On completion:
  increment `AGENT_RUNS` with status label, observe `AGENT_RUN_DURATION`. Track `AGENT_ACTIVE` gauge (inc on start, dec
  on finish)
- `src/sase/axe/run_agent_exec.py` — Increment `AGENT_KILLS` when agent is killed (with reason label)

### Phase 4: LLM Provider Instrumentation

Wire metrics into the LLM invocation pipeline.

Files to modify:

- `src/sase/llm_provider/_invoke.py` — In `invoke_agent()`: increment `LLM_INVOCATIONS`, observe
  `LLM_INVOCATION_DURATION`, increment `LLM_ERRORS` on failure (with error_type label from exception class)
- `src/sase/llm_provider/retry_config.py` — Increment `LLM_RETRIES` when retry is triggered

### Phase 5: Hook / Mentor / Workflow Instrumentation

Wire metrics into the chop scripts and workflow runners.

Files to modify:

- `src/sase/axe/hook_jobs.py` — In `run_hook_checks()`: increment `HOOK_EXECUTIONS` per hook started/completed. In
  `run_mentor_checks()`: increment `MENTOR_EXECUTIONS`. Track `ZOMBIE_DETECTIONS`
- `src/sase/ace/scheduler/hook_checks.py` — In `check_hooks()`: observe `HOOK_DURATION` per hook completion
- `src/sase/ace/scheduler/workflows_runner/completer.py` — In `check_and_complete_workflows()`: increment
  `WORKFLOW_EXECUTIONS`, observe `WORKFLOW_DURATION`

### Phase 6: Bead Instrumentation

Wire metrics into bead CRUD operations.

Files to modify:

- `src/sase/bead/project.py` — In `create()`: increment `BEAD_OPERATIONS` with `operation=create`. In `update()`:
  increment with `operation=update`. In `close()`: increment with `operation=close` and record
  `BEAD_STATUS_TRANSITIONS`. In `list_issues()` with ready filter: set `BEAD_ACTIVE` gauge

### Phase 7: VCS / Workspace / Notification Instrumentation

Wire metrics into remaining subsystems.

Files to modify:

- `src/sase/running_field/_operations.py` — In `claim_workspace()`: increment `WORKSPACE_ACQUISITIONS`, adjust
  `WORKSPACE_ACTIVE` gauge. In `release_workspace()`: increment `WORKSPACE_RELEASES`, adjust gauge
- `src/sase/vcs_provider/plugins/bare_git.py` — In `commit()`: increment `VCS_COMMITS`. In `mail()`, `revert()`, etc.:
  increment `VCS_OPERATIONS`
- `src/sase/notifications/senders.py` — In each `notify_*()` function: increment `NOTIFICATIONS_SENT` with appropriate
  `type` label

### Phase 8: Tests

Integration tests verifying metrics are recorded at each instrumentation point. Test both enabled and disabled (stub)
paths.

Files to create/modify:

- `tests/telemetry/test_instrumentation.py` — Integration tests for each instrumented subsystem
- Existing test files may need `init_telemetry()` calls in fixtures

## Risks

- **Multi-process metric sharing**: Lumberjacks run as separate processes. Each gets its own metric state. The
  orchestrator's HTTP server only exposes its own process metrics. Lumberjack metrics need either: (a) each lumberjack
  pushes to pushgateway, or (b) the orchestrator reads lumberjack JSON state files and exposes them as custom collector.
  Option (b) is simpler since lumberjack state files already exist. Implement a custom `Collector` in the orchestrator
  that reads `~/.sase/axe/lumberjacks/*/metrics.json` and translates to Prometheus metrics.

- **Import cost**: `prometheus_client` is lightweight but still an import. The stub path ensures zero import cost when
  disabled — `prometheus_client` is only imported inside `init_telemetry()` when `enabled=True`.

- **Pushgateway availability**: Agent runners and CLI commands push to pushgateway. If it's down, metrics are silently
  lost. This is acceptable — metrics are best-effort, never blocking.

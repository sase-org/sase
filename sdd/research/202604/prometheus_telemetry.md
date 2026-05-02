# Prometheus Telemetry Integration Research

## Context

Sase has two distinct runtime profiles that need different exposition strategies:

- **Short-lived CLI commands** (`sase commit`, `sase bead`, `sase xprompt`, etc.) - run for seconds to minutes
- **Long-running daemons** (`sase axe`, agent runners, lumberjacks) - run for hours/days

Sase already has structured logging (`runs.jsonl`, `events.jsonl`) and in-memory metrics (`AxeMetrics` dataclass in
`axe/state.py`). Prometheus would complement these with real-time, queryable, aggregatable time-series data.

## Library

The official `prometheus_client` Python library (v0.24+, zero dependencies). Metric operations (`inc()`, `observe()`,
`set()`) are thread-safe and non-blocking.

## Exposition Strategy

| Runtime Profile                  | Strategy                                                              | Rationale                                                                                         |
| -------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `axe` orchestrator / lumberjacks | HTTP exposition server (`start_http_server()`) on a configurable port | Long-lived, Prometheus scrapes on interval                                                        |
| Agent runners (medium-lived)     | Push Gateway (`pushadd_to_gateway()`) on completion                   | Run minutes to hours, push final metrics on exit                                                  |
| Short-lived CLI commands         | Push Gateway or skip                                                  | Most CLI commands are too brief to warrant metrics; instrument only high-value ones like `commit` |

Key implementation notes:

- Use a **dedicated `CollectorRegistry()`** for Push Gateway (not the global registry, which includes process/GC
  collectors irrelevant for batch jobs)
- Use `pushadd_to_gateway()` (POST/merge), not `push_to_gateway()` (PUT/replace), since multiple agents push
  concurrently
- Wrap push calls in try/except so a downed pushgateway never crashes the CLI
- Use `atexit.register()` for push-on-exit in agent runners

## Naming Convention

All metrics use the pattern: `sase_<subsystem>_<name>_<unit>`

Namespace: `sase`. Subsystems: `agent`, `axe`, `hook`, `llm`, `bead`, `vcs`, `workspace`.

Units are always base units: `_seconds` (not ms), `_bytes` (not kb). Counters always end in `_total`.

## Proposed Metrics

### Agent Lifecycle

| Metric                            | Type      | Labels                               | Description                                         |
| --------------------------------- | --------- | ------------------------------------ | --------------------------------------------------- |
| `sase_agent_runs_total`           | Counter   | `llm_provider`, `status`, `workflow` | Total agent runs completed                          |
| `sase_agent_run_duration_seconds` | Histogram | `llm_provider`, `workflow`           | Wall-clock duration of agent runs                   |
| `sase_agent_active_count`         | Gauge     | `llm_provider`, `project`            | Currently running agents                            |
| `sase_agent_spawns_total`         | Counter   | `llm_provider`, `project`            | Agent subprocess spawn events                       |
| `sase_agent_kills_total`          | Counter   | `reason`                             | Agent terminations (user-initiated, timeout, error) |

Histogram buckets for run duration: `[10, 30, 60, 120, 300, 600, 1800, 3600]` (10s to 1h).

### LLM Provider

| Metric                                 | Type      | Labels                   | Description                  |
| -------------------------------------- | --------- | ------------------------ | ---------------------------- |
| `sase_llm_invocations_total`           | Counter   | `provider`, `status`     | Total LLM invocations        |
| `sase_llm_invocation_duration_seconds` | Histogram | `provider`               | Time from invoke to response |
| `sase_llm_errors_total`                | Counter   | `provider`, `error_type` | LLM invocation errors        |
| `sase_llm_retries_total`               | Counter   | `provider`               | Transient error retries      |

Providers: `claude`, `gemini`, `codex`. Status: `success`, `error`. Error types: `timeout`, `rate_limit`,
`auth_failure`, `invocation_error`.

### Axe Orchestrator

| Metric                               | Type      | Labels       | Description                               |
| ------------------------------------ | --------- | ------------ | ----------------------------------------- |
| `sase_axe_cycles_total`              | Counter   | `cycle_type` | Completed scheduler cycles                |
| `sase_axe_cycle_duration_seconds`    | Histogram | `cycle_type` | Time per scheduler cycle                  |
| `sase_axe_lumberjacks_active`        | Gauge     | -            | Currently running lumberjack subprocesses |
| `sase_axe_lumberjack_restarts_total` | Counter   | -            | Lumberjack crash restarts                 |
| `sase_axe_errors_total`              | Counter   | `error_type` | Orchestrator errors                       |

Cycle types: `full`, `hook`, `comment`.

### Hooks / Mentors / Workflows

| Metric                           | Type      | Labels                | Description                       |
| -------------------------------- | --------- | --------------------- | --------------------------------- |
| `sase_hook_executions_total`     | Counter   | `hook_type`, `status` | Hook runs                         |
| `sase_hook_duration_seconds`     | Histogram | `hook_type`           | Hook execution time               |
| `sase_hook_retries_total`        | Counter   | `hook_type`           | Transient error retries (up to 3) |
| `sase_mentor_executions_total`   | Counter   | `status`              | Mentor comment cycles             |
| `sase_workflow_executions_total` | Counter   | `workflow`, `status`  | Workflow runs                     |
| `sase_workflow_duration_seconds` | Histogram | `workflow`            | Workflow execution time           |
| `sase_zombie_detections_total`   | Counter   | -                     | Zombie process detections         |

Hook types: `start`, `stop`, `mentor`. Status: `success`, `error`, `timeout`, `killed`.

### Beads (Task Tracking)

| Metric                               | Type    | Labels                     | Description                   |
| ------------------------------------ | ------- | -------------------------- | ----------------------------- |
| `sase_bead_operations_total`         | Counter | `operation`                | Bead CRUD operations          |
| `sase_bead_status_transitions_total` | Counter | `from_status`, `to_status` | Status changes                |
| `sase_bead_active_count`             | Gauge   | `project`, `status`        | Current bead counts by status |

Operations: `create`, `close`, `update`, `ready`, `sync`.

### VCS / Workspace

| Metric                              | Type    | Labels                            | Description                           |
| ----------------------------------- | ------- | --------------------------------- | ------------------------------------- |
| `sase_vcs_commits_total`            | Counter | `provider`, `type`                | Commits created                       |
| `sase_vcs_operations_total`         | Counter | `provider`, `operation`, `status` | VCS operations (mail, submit, revert) |
| `sase_workspace_acquisitions_total` | Counter | `project`                         | Workspace checkouts                   |
| `sase_workspace_releases_total`     | Counter | `project`                         | Workspace releases                    |
| `sase_workspace_active_count`       | Gauge   | `project`                         | Currently held workspaces             |

Commit types: `create`, `amend`. VCS operations: `mail`, `submit`, `revert`, `restore`.

### Notifications

| Metric                          | Type    | Labels           | Description              |
| ------------------------------- | ------- | ---------------- | ------------------------ |
| `sase_notifications_sent_total` | Counter | `type`, `status` | Notifications dispatched |

Types: `workflow_complete`, `sync_result`, `error_digest`, `hitl_request`, `user_question`, `plan_approval`.

## Label Design Principles

**Keep cardinality bounded.** Every label value must come from a known, small set. The total number of time series for a
metric is the product of all label cardinality. Target < 500 series per metric.

Good labels (bounded enums):

- `llm_provider`: claude, gemini, codex (~3 values)
- `status`: success, error, timeout, killed (~4 values)
- `cycle_type`: full, hook, comment (~3 values)
- `hook_type`: start, stop, mentor (~3 values)
- `operation`: create, close, update, ready, sync (~5 values)

Avoid as labels (unbounded):

- `project` name (use only where essential, e.g. workspace gauges; accept the cardinality cost)
- `branch` name (unbounded)
- `workspace_num` (not useful as dimension)
- `error_message` (unbounded text)
- `file_path` (unbounded)
- `agent_id` or `pid` (unique per run)

## Implementation Sketch

### Module structure

```
src/sase/telemetry/
    __init__.py          # re-exports public API
    metrics.py           # metric definitions (module-level singletons)
    registry.py          # registry management, push/exposition helpers
    config.py            # telemetry config (enabled, pushgateway addr, port)
```

### Metric definition pattern

```python
# src/sase/telemetry/metrics.py
from prometheus_client import Counter, Gauge, Histogram

AGENT_RUNS = Counter(
    'runs_total', 'Total agent runs',
    ['llm_provider', 'status', 'workflow'],
    namespace='sase', subsystem='agent',
)
AGENT_RUN_DURATION = Histogram(
    'run_duration_seconds', 'Agent run duration',
    ['llm_provider', 'workflow'],
    namespace='sase', subsystem='agent',
    buckets=[10, 30, 60, 120, 300, 600, 1800, 3600],
)
AGENT_ACTIVE = Gauge(
    'active_count', 'Currently running agents',
    ['llm_provider', 'project'],
    namespace='sase', subsystem='agent',
)
```

### Instrumentation pattern

```python
# In agent/launcher.py or similar
from sase.telemetry.metrics import AGENT_RUNS, AGENT_RUN_DURATION, AGENT_ACTIVE

def run_agent(provider: str, workflow: str, project: str):
    AGENT_ACTIVE.labels(llm_provider=provider, project=project).inc()
    with AGENT_RUN_DURATION.labels(llm_provider=provider, workflow=workflow).time():
        try:
            result = do_agent_work()
            AGENT_RUNS.labels(llm_provider=provider, status='success', workflow=workflow).inc()
        except Exception:
            AGENT_RUNS.labels(llm_provider=provider, status='error', workflow=workflow).inc()
            raise
        finally:
            AGENT_ACTIVE.labels(llm_provider=provider, project=project).dec()
```

### Configuration

Add to `default_config.yml`:

```yaml
telemetry:
  enabled: false
  prometheus:
    pushgateway_url: "localhost:9091"
    exposition_port: 9090 # for axe daemon
```

### Exposition wiring

```python
# src/sase/telemetry/registry.py
import atexit
from prometheus_client import (
    CollectorRegistry, start_http_server, pushadd_to_gateway,
    REGISTRY,
)

def start_exposition_server(port: int = 9090) -> None:
    """For long-lived processes (axe)."""
    start_http_server(port)

def push_metrics(job: str, grouping_key: dict[str, str] | None = None) -> None:
    """For short/medium-lived processes (agents, CLI)."""
    registry = CollectorRegistry()
    # ... copy/collect relevant metrics ...
    try:
        pushadd_to_gateway('localhost:9091', job=job,
                           registry=registry, grouping_key=grouping_key)
    except Exception:
        pass  # never crash on metrics push failure

def register_push_on_exit(job: str, **grouping_key: str) -> None:
    """Register atexit handler to push metrics when process exits."""
    atexit.register(push_metrics, job=job, grouping_key=grouping_key)
```

## Pitfalls to Avoid

1. **Never create metrics inside functions** - define them as module-level singletons. Creating inside a function raises
   `ValueError` on second call.
2. **Always use base units** - seconds, bytes. Let Grafana format for display.
3. **Counter names must end in `_total`** - the `namespace`/`subsystem` params auto-prepend, but the name itself needs
   `_total`.
4. **Use Histogram, not Summary, for latencies** - Python's Summary doesn't compute quantiles. Histograms are also
   aggregatable across instances.
5. **Don't use the global registry with Push Gateway** - use a dedicated `CollectorRegistry()`.
6. **Gracefully handle pushgateway unavailability** - wrap in try/except, never crash the tool.
7. **Avoid unbounded label cardinality** - no PIDs, branch names, error messages, or file paths as labels.

## Relationship to Existing Logging

Prometheus metrics and the existing JSONL logs serve different purposes:

| Concern       | JSONL Logs (`runs.jsonl`, `events.jsonl`) | Prometheus Metrics                   |
| ------------- | ----------------------------------------- | ------------------------------------ |
| Query pattern | Post-hoc analysis, grep/jq                | Real-time dashboards, alerts         |
| Retention     | Append-forever, manual rotation           | Configurable retention in Prometheus |
| Aggregation   | Manual (scripts)                          | Native (PromQL)                      |
| Alerting      | None                                      | Alertmanager integration             |
| Granularity   | Per-event detail (paths, branch names)    | Aggregate counts/rates/distributions |

They are complementary. Logs answer "what happened to this specific run?" while metrics answer "how are things going
overall?" The `AxeMetrics` dataclass in `axe/state.py` is a natural migration candidate - its fields map directly to
Prometheus counters.

---
create_time: 2026-04-11 22:59:47
status: done
prompt: sdd/prompts/202604/fix_prometheus_metrics.md
---

# Fix Prometheus Metrics Tracking and Display for Agent Invocations

## Problem

Two user-reported symptoms:

1. **No data in "Agent Run Duration" chart** (charts mode) - always empty
2. **Only 1 LLM invocation shown in summary dashboard** over 7 days - known to be wrong

## Root Cause Analysis

After thorough investigation, the root cause is **pushgateway group key collision** combined with **per-process fresh
registries**.

### How it works today

Each agent runner process (`run_agent_runner.py`):

1. Creates a **fresh** `CollectorRegistry` with all counters starting at 0
2. Records metrics during the run (AGENT_RUNS, LLM_INVOCATIONS, AGENT_RUN_DURATION, etc.)
3. On exit, pushes to pushgateway with `job="agent_runner"` and `grouping_key={"workflow": workflow_name}`

### Why it breaks

All agent runs using the same workflow name (typically `"run"`) share the **same pushgateway group**. Each push
**replaces** the previous group's metric families. Since each process starts with fresh counters at 0:

- Agent A finishes: pushes `LLM_INVOCATIONS=5, AGENT_RUNS=1` to group `(agent_runner, workflow=run)`
- Agent B finishes: pushes `LLM_INVOCATIONS=3, AGENT_RUNS=1` to the **same group** — overwrites A's data
- Dashboard scrapes pushgateway: sees only B's metrics (`LLM_INVOCATIONS=3`)

This explains why the dashboard shows only 1 LLM invocation — it's the count from the single most recent agent run.

### Why Agent Run Duration chart is empty

The charts mode queries Prometheus with PromQL range queries like:

```
histogram_quantile(0.50, sum(rate(sase_agent_run_duration_seconds_bucket[1d])) by (le))
```

This requires Prometheus to have **historical scrape data**. Even if Prometheus is running and scraping the pushgateway:

- The pushgateway only has the latest run's single data point (due to overwrites)
- `rate()` over a single data point returns nothing
- So the chart is always empty

## Fix: Unique Grouping Keys per Agent Run

### Core change

Add a unique **instance identifier** to the pushgateway grouping key so each agent run gets its own group. Use the
existing `timestamp` (already available in the runner) as the instance key.

**`src/sase/axe/run_agent_runner.py`**: Add `instance=timestamp` to both `register_push_on_exit()` (line 113) and the
inline `push_metrics()` call (line 238).

This ensures each agent run pushes to its own pushgateway group. The dashboard's `_pick_key_metrics` already sums across
all groups, so cumulative totals would now be correct.

### Apply same fix to other runners

The same collision issue affects other runners that share grouping keys:

- **`mentor_runner.py`**: `job="mentor-runner", mentor=<name>` — multiple runs with same name collide
- **`fix_hook_runner.py`**: `job="fix-hook-runner"` with NO grouping key — ALL runs collide
- **`summarize_hook_runner.py`**: `job="summarize-hook-runner"` with NO grouping key — same issue
- **`crs_runner.py`**: `job="crs-runner"` with NO grouping key — same issue

Each needs a unique instance identifier added to their grouping key.

### Stale group cleanup

With unique keys, pushgateway groups accumulate indefinitely. Add a `cleanup_stale_groups()` function to `_registry.py`
that:

1. Lists groups on the pushgateway via its admin API
2. Identifies runner groups older than a configurable threshold (default: 7 days)
3. Deletes stale groups

Wire it into the orchestrator's periodic tasks (every 6 hours).

### Dashboard histogram aggregation fix

With multiple pushgateway groups, `compute_percentiles()` in `scrape.py` receives multiple `_bucket` samples per `le`
bound. Currently it just appends `(bound, value)` pairs — with multiple groups this produces duplicate bounds. Fix:
aggregate bucket counts by `le` bound before computing percentiles.

## Phases

### Phase 1: Unique grouping keys for all runners

- Add `instance` key to grouping keys in all 5 runner files
- This is the core fix that resolves both reported symptoms

### Phase 2: Stale group cleanup

- Add `cleanup_stale_groups()` to `_registry.py`
- Wire into orchestrator periodic tasks

### Phase 3: Fix histogram aggregation

- Update `compute_percentiles()` in `scrape.py` to sum bucket counts by `le` bound across groups

---
create_time: 2026-04-11 22:20:49
status: done
prompt: sdd/prompts/202604/fix_histogram_quantile_queries.md
---

# Plan: Fix histogram_quantile PromQL Queries for Duration Charts

## Problem

The "Agent Run Duration" and "LLM Latency" charts on the telemetry dashboard show "No data available" even when
histogram data has been recorded. The root cause is that the `histogram_quantile` PromQL queries are missing the
standard `sum(...) by (le)` aggregation, which causes failures when the histogram metrics have extra labels beyond `le`.

## Root Cause Analysis

### The PromQL queries lack bucket aggregation

The current queries are:

```
histogram_quantile(0.50, rate(sase_agent_run_duration_seconds_bucket[15m]))
histogram_quantile(0.95, rate(sase_agent_run_duration_seconds_bucket[15m]))
```

The `histogram_quantile` function expects a vector where `le` is the only distinguishing label. But the underlying
metrics carry extra labels:

- `sase_agent_run_duration_seconds_bucket` has labels: `llm_provider`, `workflow`, `le`
- `sase_llm_invocation_duration_seconds_bucket` has labels: `provider`, `le`

Without `sum(...) by (le)`, `histogram_quantile` returns one time series per unique combination of non-`le` labels. The
dashboard code (`cli_dashboard.py:334`) only takes `result[0]` from each query, so:

1. If multiple `(llm_provider, workflow)` combinations exist, only the first (arbitrary) one is used — data from other
   combinations is silently dropped.
2. Prometheus may return an all-NaN series as `result[0]` (from a label combination with no recent activity), causing
   the chart to show "No data available" even when other combinations have data.
3. Even with a single label combination, the lack of aggregation produces non-standard queries that Prometheus may
   handle inconsistently.

The standard pattern is:

```
histogram_quantile(0.50, sum(rate(sase_agent_run_duration_seconds_bucket[15m])) by (le))
```

This aggregates all label combinations into a single vector keyed only by `le`, producing exactly one output series —
which is what the dashboard expects.

### Same issue affects LLM Latency

The "LLM Latency" chart uses the identical pattern:

```
histogram_quantile(0.50, rate(sase_llm_invocation_duration_seconds_bucket[15m]))
```

The `sase_llm_invocation_duration_seconds` histogram has a `provider` label, so the same aggregation issue applies.

## Plan

### Step 1: Add `sum(...) by (le)` to both histogram quantile queries

**File:** `src/sase/telemetry/cli_dashboard.py`, lines 249-250 and 283-284

Change the Agent Run Duration queries from:

```python
f"histogram_quantile(0.50, rate(sase_agent_run_duration_seconds_bucket[{w}]))"
f"histogram_quantile(0.95, rate(sase_agent_run_duration_seconds_bucket[{w}]))"
```

to:

```python
f"histogram_quantile(0.50, sum(rate(sase_agent_run_duration_seconds_bucket[{w}])) by (le))"
f"histogram_quantile(0.95, sum(rate(sase_agent_run_duration_seconds_bucket[{w}])) by (le))"
```

Apply the same change to the LLM Latency queries (lines 283-284).

### Step 2: Run checks

Run `just install && just check` to verify no regressions.

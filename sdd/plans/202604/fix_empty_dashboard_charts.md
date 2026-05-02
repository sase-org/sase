---
create_time: 2026-04-08 21:27:30
status: done
prompt: sdd/prompts/202604/fix_empty_dashboard_charts.md
---

# Fix Empty Telemetry Dashboard Charts

## Problem

Running `sase telemetry dashboard -c` shows "No data available" for 4 of 6 charts despite telemetry data existing in
Prometheus. The affected charts are: Agent Run Duration, Active Agents, LLM Latency, and Error Rate. Meanwhile, Agent
Throughput and LLM Token Usage render (showing zero values).

## Root Cause Analysis

There are two distinct root causes:

### 1. NaN values from `histogram_quantile` crash plotext (Agent Run Duration, LLM Latency)

The PromQL queries use `histogram_quantile(p, rate(bucket[5m]))`. When histogram buckets have no new observations in the
5-minute rate window, `rate()` returns 0 for all buckets. `histogram_quantile()` on all-zero rates is mathematically
undefined and returns **NaN**.

The NaN data flows through unchecked:

1. Prometheus returns `"NaN"` strings in the JSON response
2. `prom_query.py:_fetch_and_parse()` line 90 converts these to `float('nan')` — the points list is **non-empty**
3. `charts.py:render_line_chart()` line 40 checks `if not ts.points` — passes (list has NaN entries)
4. plotext receives NaN y-values via `plt.plot(xs, ys)` and fails during `plt.build()`
5. The `except (IndexError, ValueError)` at line 66 catches the crash → "No data available"

**Why counters work but histograms don't**: `rate()` on a constant counter returns `0.0` (a valid float).
`histogram_quantile()` on zero-rate buckets returns `NaN` (not a valid float). Prometheus includes both in the response,
but only NaN causes plotext to crash.

### 2. Hardcoded 5-minute rate window is too narrow

All PromQL queries use a hardcoded `[5m]` rate window regardless of the dashboard time range. If an agent completed 10
minutes ago, the 5-minute window contains zero observations — even though the dashboard is showing a 1-hour or 24-hour
range. This makes the NaN problem much worse: data that IS in Prometheus and IS within the visible time range gets
missed because the rate window is too small.

### Secondary issues

- **Active Agents (gauge)**: Queries `sase_agent_active` directly (no histogram_quantile). If the metric exists with
  value 0, it should render. The "No data available" likely means the metric doesn't exist in Prometheus (e.g.,
  pushgateway restarted, or no agents have run since telemetry was enabled). This is a data availability issue, not a
  code bug.
- **Error Rate**: Error counters (`status="error"`, `sase_llm_errors_total`) were never incremented, so those label
  combinations don't exist in Prometheus. This is expected behavior — no errors means no error data.

## Fix

### Phase 1: Filter NaN values in `prom_query.py`

**File**: `src/sase/telemetry/prom_query.py`, `_fetch_and_parse()` function (line 90)

Add `math.isnan()` filtering when parsing Prometheus range query results. NaN values should be excluded from the points
list so they never reach the chart renderer.

```python
# Before:
points = [(float(ts), float(val)) for ts, val in r.get("values", [])]

# After: filter NaN values that histogram_quantile produces for zero-rate buckets
raw_points = [(float(ts), float(val)) for ts, val in r.get("values", [])]
points = [(ts, val) for ts, val in raw_points if not math.isnan(val)]
```

This is a defensive fix — it prevents NaN-related plotext crashes. Histogram charts will still show "No data available"
when all values are NaN (which is correct: you can't display a percentile that doesn't exist). But this prevents
corrupted charts and makes the behavior consistent.

### Phase 2: Scale rate window with dashboard time range

**File**: `src/sase/telemetry/cli_dashboard.py`

Replace the hardcoded `[5m]` rate windows in `_CHART_SPECS` with a dynamic window proportional to the dashboard time
range. This ensures observations within the visible time window are captured by the rate computation.

Add a rate window mapping:

```python
_RATE_WINDOW_FOR_RANGE: dict[str, str] = {
    "1h": "15m",
    "6h": "1h",
    "24h": "4h",
    "7d": "1d",
}
```

Convert `_CHART_SPECS` from a static list to a function `_get_chart_specs(rate_window: str)` that interpolates the
window into PromQL queries. For example:

```
histogram_quantile(0.50, rate(sase_agent_run_duration_seconds_bucket[{rate_window}]))
```

This way, a 1-hour dashboard uses 15-minute rate windows — if any agent ran in the last 15 minutes, the histogram has
non-zero rates and `histogram_quantile` returns valid percentiles instead of NaN.

### Phase 3: Update `_build_charts_dashboard` to use dynamic rate window

**File**: `src/sase/telemetry/cli_dashboard.py`, `_build_charts_dashboard()` function

Pass `range_key` to the new `_get_chart_specs()` function so the rate window is computed from the dashboard's time range
selection.

## Files Changed

| File                                  | Change                                                                                                           |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `src/sase/telemetry/prom_query.py`    | Filter NaN values in `_fetch_and_parse()`                                                                        |
| `src/sase/telemetry/cli_dashboard.py` | Add `_RATE_WINDOW_FOR_RANGE`, convert `_CHART_SPECS` to `_get_chart_specs()`, update `_build_charts_dashboard()` |

## Testing

- Run `just check` to verify lint/type/test pass
- Manual verification: `sase telemetry dashboard -c` should show histogram charts with data (if agents have run within
  the rate window) or clean "No data available" (if not) — never a crashed chart

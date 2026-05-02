---
create_time: 2026-04-11 20:59:16
status: done
prompt: sdd/prompts/202604/fix_dashboard_charts.md
---

# Plan: Fix Telemetry Dashboard Charts

## Problem

Running `sase telemetry dashboard -c` shows most charts broken — 4 of 6 display "No data available" and 1 shows
incorrect zero values. Only "LLM Token Usage" renders with actual data (though with raw Unix timestamps on the x-axis).

## Root Cause Analysis

### Issue 1: Status label mismatch (primary bug)

The agent runner records metrics with `status="success"` / `status="failed"`, but the PromQL queries in the dashboard
expect `status="ok"` / `status="error"`.

- **Recording** (`src/sase/axe/run_agent_runner.py:400`):

  ```python
  AGENT_RUNS.labels(..., status="success" if success else "failed", ...).inc()
  ```

- **Querying** (`src/sase/telemetry/cli_dashboard.py:264-292`):

  ```python
  rate(sase_agent_runs_total{status="ok"}[...])
  rate(sase_agent_runs_total{status="error"}[...])
  ```

- The LLM side (`src/sase/llm_provider/_invoke.py:193-219`) correctly uses `"ok"` / `"error"`, so the mismatch is only
  on the agent runner side.

**Charts affected:**

- **Agent Throughput**: Queries match nothing → bar chart renders with 0.0 values (looks like it works but data is
  wrong)
- **Error Rate**: The `agent errors` query matches nothing → contributes to "No data available"

### Issue 2: X-axis shows raw Unix timestamps

The line chart renderer (`src/sase/telemetry/charts.py:53`) passes raw float timestamps to plotext as x-coordinates.
plotext treats them as plain numbers, displaying values like `1775685213.9` on the x-axis instead of human-readable
dates.

**Charts affected:** All line charts (visible on LLM Token Usage since it's the only one rendering data)

### Non-issues (legitimate behavior)

- **Agent Run Duration** and **LLM Latency**: These use `histogram_quantile(rate(...))`. When no observations exist in
  the rate window, all bucket rates are 0, histogram_quantile returns NaN for every point, the NaN filter removes them
  all, and the chart correctly shows "No data available". This is expected when there's genuinely no histogram data.
- **Active Agents**: The `sase_agent_active` gauge is 0 when no agents are running. If no agents ran during the queried
  time range, "No data available" is correct.

## Plan

### Step 1: Fix status label mismatch in agent runner

**File:** `src/sase/axe/run_agent_runner.py:400`

Change `status="success"` → `status="ok"` and `status="failed"` → `status="error"` to match the PromQL queries and the
convention already used by the LLM provider.

### Step 2: Format x-axis timestamps as dates in line charts

**File:** `src/sase/telemetry/charts.py`

In `render_line_chart`, convert the raw Unix timestamps to human-readable date strings before passing them to plotext.
Use `plotext`'s `date_form()` to configure date formatting, and convert timestamps to date strings via
`datetime.fromtimestamp()`. Choose a format appropriate for the data density (e.g., `"d/m H:M"` or `"m/d H:M"`).

### Step 3: Run checks

Run `just install && just check` to verify no regressions.

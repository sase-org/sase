---
create_time: 2026-04-23 17:27:27
status: done
prompt: sdd/prompts/202604/fix_agent_metrics_stub_binding_1.md
---
# Fix: Agent Lifecycle Metrics Never Reach Pushgateway

## Problem

The `sase_agent_*` Prometheus metrics (`sase_agent_runs_total`, `sase_agent_run_duration_seconds_*`,
`sase_agent_active`, `sase_agent_spawns_total`, `sase_agent_kills_total`) have **zero series** in Prometheus, despite:

- `sase telemetry status` reporting enabled + pushgateway reachable
- 1207 `agent_runner` job groups existing on the pushgateway
- Metrics being properly defined in `src/sase/telemetry/metrics.py` (lines 19–23, 85–124)
- Increment sites existing in `run_agent_runner.py` (lines 247, 380, 385, 388), `run_agent_exec.py` (line 367), and
  `launcher.py` (line 128)

All 1207 `agent_runner` pushes carry only the label-less metrics (`sase_axe_lumberjacks_active`,
`sase_axe_lumberjack_restarts_total`, `sase_zombie_detections_total` — each with value `0`), plus
`sase_notifications_sent_total` when notifications fired. None carry any `sase_agent_*` family.

The same root cause affects LLM metrics: `sase_llm_invocations_total` appears only from `summarize-hook-runner`, never
from agent runs — despite the `LLM_*` instrumentation in `src/sase/llm_provider/_invoke.py` being wired correctly.

## Root Cause

**`from sase.telemetry.metrics import X` binds a name to a stub object at module-load time. When `init_telemetry()`
later runs, it replaces `sase.telemetry.metrics.X` via `setattr`, but modules that already imported `X` keep their stub
binding — all subsequent `.labels().inc()` calls are no-ops.**

Concretely, in `_create_real_metrics()` (`src/sase/telemetry/_registry.py:74`):

```python
for attr, kind, name, doc, labelnames, extra in METRIC_DEFS:
    cls = factory[kind]
    metric = cls(name, doc, labelnames=labelnames, registry=reg, **extra)
    setattr(m, attr, metric)   # replaces module attribute only
```

Call-site evidence:

| File                       | Line  | Import style                                                                                    | Result                                                                                                                                                                                                                                 |
| -------------------------- | ----- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `axe/run_agent_runner.py`  | 39–44 | `from sase.telemetry.metrics import AGENT_RUNS, AGENT_RUN_DURATION, AGENT_ACTIVE` at module top | **stub — imported before line 96's `init_telemetry()`**                                                                                                                                                                                |
| `axe/run_agent_exec.py`    | 27    | `from sase.telemetry.metrics import AGENT_KILLS` at module top                                  | **stub — imported transitively from run_agent_runner before init**                                                                                                                                                                     |
| `agent/launcher.py`        | 13    | `from sase.telemetry.metrics import AGENT_SPAWNS` at module top                                 | **stub — launcher process also lacks `init_telemetry()` entirely**                                                                                                                                                                     |
| `llm_provider/_invoke.py`  | 16    | `from sase.telemetry.metrics import LLM_INVOCATIONS, ...` at module top                         | **stub when imported transitively in contexts where `init_telemetry()` already ran** — actually works for `summarize-hook-runner` because `_invoke` happens to be imported lazily there, but dead for every agent-runner-side LLM call |
| `notifications/senders.py` | 10    | `from sase.telemetry.metrics import NOTIFICATIONS_SENT` at module top                           | **works — `senders` is lazy-imported from `run_agent_runner.py:482` _after_ `init_telemetry()`**                                                                                                                                       |

The label-less metrics (`AXE_LUMBERJACKS_ACTIVE`, `AXE_LUMBERJACK_RESTARTS`, `ZOMBIE_DETECTIONS`) appear in every
agent_runner push simply because `prometheus_client` emits default-zero samples for label-less Counters/Gauges
regardless of whether they were ever touched — they are "ghost" samples, not real telemetry.

### Secondary issues found while diagnosing

1. **`AGENT_SPAWNS` lives in a process that never initializes telemetry.** `launcher.py:128` calls
   `AGENT_SPAWNS.labels(llm_provider="", project=project_name).inc()` inside `spawn_agent_subprocess` — the TUI / CLI
   parent process that calls this has no `init_telemetry()` _and_ no `register_push_on_exit()`. Even if the stub binding
   were fixed, this metric would never be pushed.
2. **`AGENT_SPAWNS.llm_provider` is hardcoded to `""`.** The launcher doesn't parse directives to discover the LLM
   provider — that extraction happens later inside `run_agent_runner.py`. So the label is perpetually empty and useless.
3. **`AGENT_KILLS` only tracks user-signalled kills.** `run_agent_exec.py:367` increments with `reason="user"`, but
   there are no counters for errors, timeouts, or orchestrator-initiated kills.

## Goals

1. **Make agent lifecycle metrics actually reach Prometheus** — `sase_agent_runs_total`,
   `sase_agent_run_duration_seconds`, `sase_agent_active`, `sase_agent_spawns_total`, `sase_agent_kills_total` must
   populate for every agent run within a day of this fix.
2. **Fix the class of bug, not just the symptom.** Every metric that uses the `from X import Y` pattern from a module
   loaded before `init_telemetry()` is affected — this includes much of the LLM, workflow, VCS, and hook metric surface
   area. A one-line fix in the stub layer repairs them all at once.
3. **Surface a simple regression test** so this can't silently rot again.

Non-goals:

- Do not redesign `METRIC_DEFS` or metric naming.
- Do not change pushgateway / scrape infrastructure (the group-key collision fix in
  `plans/202604/fix_prometheus_metrics.md` already addressed that layer).
- Do not attempt to populate labels that aren't available at the call site (e.g., launcher has no llm_provider).

## Design

### Part 1 — Primary fix: make stubs forward to the real metric

Change the stubs in `src/sase/telemetry/_stubs.py` to hold an optional `_real` attribute. When telemetry is enabled,
`_create_real_metrics()` sets `stub._real = real_metric` instead of replacing the module attribute. Every stub method
becomes a thin delegate:

```python
class StubCounter:
    _real: object | None = None

    def inc(self, amount: float = 1) -> None:
        if self._real is not None:
            self._real.inc(amount)

    def labels(self, *args, **kwargs):
        if self._real is not None:
            return self._real.labels(*args, **kwargs)
        return self
```

Similarly for `StubGauge` (adds `dec`, `set`) and `StubHistogram` (adds `observe`, `time`).

In `_create_real_metrics()`:

```python
for attr, kind, name, doc, labelnames, extra in METRIC_DEFS:
    cls = factory[kind]
    real = cls(name, doc, labelnames=labelnames, registry=reg, **extra)
    stub = getattr(m, attr)
    stub._real = real
    setattr(m, attr, real)  # keep for post-init imports — no double-emit since
                             # stub delegates to the same `real` object
```

Keeping `setattr` preserves zero-indirection access for late imports; `stub._real` handles the pre-init imports. Both
paths resolve to the **same** real metric object, so there is no double-counting.

**Why this approach:**

- Minimal churn: no call-site changes across ~20 files.
- Backwards-compatible with the disabled-telemetry path (stubs without `_real` remain no-ops).
- Symmetric: fixes every affected metric family simultaneously, not just `AGENT_*`.

Rejected alternatives:

- **Refactor every call site to `metrics.AGENT_RUNS.labels(...)`.** Touches ~25 files and introduces an attribute lookup
  on every hot-path `.inc()`. Fragile against future imports regressing the pattern.
- **Force import ordering (init_telemetry before any metric import).** Not enforceable across subprocess entry points
  and lazy imports; one accidental top-level `import X` anywhere in the dependency graph re-breaks it.
- **Mutate stubs' class (`stub.__class__ = RealCounter`).** Prometheus metric classes aren't designed for that and the
  registry state wouldn't track; brittle.

### Part 2 — Secondary fix: move `AGENT_SPAWNS` increment into `run_agent_runner.py`

Remove `AGENT_SPAWNS.labels(...).inc()` from `agent/launcher.py:128`. Drop the
`from sase.telemetry.metrics import AGENT_SPAWNS` import there. Add the increment inside `run_agent_runner.py` next to
`AGENT_ACTIVE.labels(...).inc()` (line ~247), where:

- `init_telemetry()` has already run
- `agent_llm_provider` is known (extracted from directives)
- `register_push_on_exit()` is already in place

This simultaneously fixes issue 1 (no telemetry in launcher process) and issue 2 (empty `llm_provider` label). Spawn and
active-gauge-inc then happen in the same frame, which is semantically clean: "the agent_runner process has started →
spawn counter ticks, active gauge ticks up."

### Part 3 — Secondary fix: widen `AGENT_KILLS` coverage

In `run_agent_runner.py`, inside the inner `except Exception` branch (around line 342–372), add
`AGENT_KILLS.labels(reason="error").inc()` when the agent failed due to an unhandled exception. Leave the existing
`AGENT_KILLS.labels(reason="user").inc()` in `run_agent_exec.py:367` untouched. Document the two reasons (`user`,
`error`) in the metric docstring in `metrics.py`.

This is intentionally a small delta — not reinventing kill taxonomy. `AGENT_RUNS{status="error"}` already counts error
completions; `AGENT_KILLS{reason="error"}` is redundant-but-useful as a dimension for "abrupt terminations" dashboards
to match the existing `reason="user"` counter.

### Part 4 — Regression test

Add `tests/telemetry/test_stub_forwarding.py` with two cases:

1. **Import-before-init still counts.** Import a module that grabs a metric via `from X import Y` at module load, call
   `init_telemetry()`, exercise `.labels(...).inc()`, then assert the value is reflected in the registry via
   `prometheus_client.generate_latest(registry)` or a direct `_value.get()` probe.
2. **Import-after-init still counts.** Same pattern but import after init — ensures the `setattr` path is preserved.

These are pure unit tests against the telemetry subsystem; no pushgateway / Prometheus dependency.

### Part 5 — Cleanup of pushgateway noise (optional, defer if out of scope)

Each agent_runner push includes ghost zero-samples for `sase_axe_lumberjacks_active`,
`sase_axe_lumberjack_restarts_total`, and `sase_zombie_detections_total` because those metrics have no labelnames.
That's cosmetic, not a data-correctness issue, but it bloats pushgateway memory and generates misleading series in
Prometheus (1207 ghost copies of `sase_axe_lumberjacks_active`). If we want to address it:

- Add label `source` to the three label-less metrics so they no longer default-emit from unrelated processes, **OR**
- Filter the push payload in `push_metrics()` to exclude metric families whose owning subsystem doesn't match the job
  name.

Recommend **defer** to a follow-up CL — the current plan's primary goal is wiring up the missing agent metrics, and this
cleanup is a separable concern with its own design tradeoffs (filtering is surprising; adding labels is a breaking
change for dashboards that consume those metric names).

## Rollout / Verification

1. Land the stub-forwarding fix + `AGENT_SPAWNS` move + `AGENT_KILLS` expansion + unit test in one CL.
2. After merge, run one agent: `sase run --daemon 'hello'` (home mode).
3. Wait ~1 minute for atexit push + Prometheus scrape (15s interval).
4. Verify:
   ```
   curl -s 'http://localhost:9090/api/v1/query?query=sase_agent_runs_total' | jq
   curl -s 'http://localhost:9090/api/v1/query?query=sase_agent_run_duration_seconds_count' | jq
   curl -s 'http://localhost:9090/api/v1/query?query=sase_agent_spawns_total' | jq
   ```
   Each should return at least one series with the expected label set (`llm_provider`, `project`, `workflow`, `status`
   where applicable).
5. Spot-check that `sase_llm_invocations_total` now has additional series beyond `summarize-hook-runner` — i.e., from
   actual agent runs with `provider=claude|gemini|codex|external`.

## Scope Boundary

Explicitly out of scope:

- Rewriting the agent-runtime telemetry surface or adding new dashboards.
- Backfilling historical data (impossible — data was never captured).
- Fixing the separate `plans/202604/fix_prometheus_metrics.md` concern (already merged as fa43e95d).
- Instrumentation parity across every subsystem — this CL only verifies `AGENT_*` works; if other families are found
  still empty after the stub fix (unlikely but possible), those are separate follow-ups.

## Files Touched

| File                                      | Change                                                                                                         |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `src/sase/telemetry/_stubs.py`            | Stubs gain `_real` delegation                                                                                  |
| `src/sase/telemetry/_registry.py`         | `_create_real_metrics` sets `stub._real` in addition to `setattr`                                              |
| `src/sase/agent/launcher.py`              | Remove `AGENT_SPAWNS` import and call site                                                                     |
| `src/sase/axe/run_agent_runner.py`        | Add `AGENT_SPAWNS.inc()` alongside `AGENT_ACTIVE.inc()`; add `AGENT_KILLS(reason="error")` in exception branch |
| `src/sase/telemetry/metrics.py`           | Docstring update for `AGENT_KILLS` reasons                                                                     |
| `tests/telemetry/test_stub_forwarding.py` | New regression test                                                                                            |

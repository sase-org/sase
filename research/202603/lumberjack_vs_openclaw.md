# Lumberjack vs OpenClaw: Feature Gap Analysis

## Overview

This document compares sase's lumberjack/axe scheduling system with OpenClaw's cron/heartbeat automation system,
identifies feature gaps, and recommends improvements.

OpenClaw is an open-source AI assistant (310k+ GitHub stars) with a built-in Gateway daemon that provides cron
scheduling, heartbeat monitoring, and multi-channel delivery. Its automation features have become a de facto standard
that users expect.

## Feature Comparison

### 1. Schedule Types

| Feature                           | Sase Lumberjacks                    | OpenClaw                               |
| --------------------------------- | ----------------------------------- | -------------------------------------- |
| Fixed interval                    | Yes (per-lumberjack)                | Yes (`every` type)                     |
| Per-chop throttle (`run_every`)   | Yes (duration strings)              | N/A (each job is independent)          |
| Cron expressions (5-field)        | **No**                              | Yes (5/6-field, via croner)            |
| One-shot scheduled jobs           | **No** (only foreground `chop run`) | Yes (`at` type, auto-deletes)          |
| Timezone-aware scheduling         | **No** (hardcoded Eastern)          | Yes (per-job IANA timezone)            |
| Stagger window for load spreading | **No**                              | Yes (up to 5 min deterministic jitter) |

**Gap**: Lumberjacks only support fixed-interval scheduling. Users who need "run at 7am weekdays" or "run once tomorrow
at 3pm" cannot express this today.

### 2. Error Handling & Retry

| Feature                                     | Sase Lumberjacks               | OpenClaw                                  |
| ------------------------------------------- | ------------------------------ | ----------------------------------------- |
| Error logging                               | Yes (last 100, with traceback) | Yes (per-job JSONL history)               |
| Error digest notifications                  | Yes (hourly chop)              | Yes (configurable)                        |
| Automatic retry on failure                  | **No**                         | Yes (up to 3 retries)                     |
| Exponential backoff                         | **No**                         | Yes (30s -> 1m -> 5m -> 15m -> 60m)       |
| Transient vs permanent error classification | **No**                         | Yes (rate limit, network, overload)       |
| Configurable retry policy per job           | **No**                         | Yes (maxAttempts, backoffMs, error types) |
| Backoff reset on success                    | **No**                         | Yes                                       |

**Gap**: When a chop fails, sase logs the error and moves on. There is no retry mechanism. For transient failures
(network timeouts, rate limits), this means the chop silently fails until the next scheduled cycle.

### 3. Job Lifecycle Management

| Feature                      | Sase Lumberjacks                     | OpenClaw                    |
| ---------------------------- | ------------------------------------ | --------------------------- |
| Start/stop all               | Yes (`axe start/stop`)               | Yes (gateway start/stop)    |
| List jobs                    | Yes (`chop list`, `lumberjack list`) | Yes (`cron list`)           |
| Run job manually             | Yes (`chop run <name>`)              | Yes (`cron run <jobId>`)    |
| View status                  | Yes (`lumberjack status`)            | Yes (`cron status`)         |
| Pause/resume individual jobs | **No**                               | Yes (`cron disable/enable`) |
| Edit job config at runtime   | **No** (requires restart)            | Yes (`cron edit`)           |
| Delete individual jobs       | **No** (config-driven only)          | Yes (`cron rm`)             |
| Add jobs at runtime          | **No** (requires restart)            | Yes (`cron add`)            |

**Gap**: Lumberjacks are entirely config-driven. Any change to chop configuration requires editing YAML and restarting
the orchestrator. OpenClaw allows dynamic job management (add, edit, delete, pause, resume) without restarts.

### 4. Run History & Observability

| Feature                     | Sase Lumberjacks                     | OpenClaw                                     |
| --------------------------- | ------------------------------------ | -------------------------------------------- |
| Last-run timestamps         | Yes (per-chop, for throttling)       | Yes                                          |
| Aggregate metrics           | Yes (cycles, chops executed, errors) | Yes (Prometheus metrics)                     |
| Per-execution history log   | **No**                               | Yes (JSONL per job, auto-pruned)             |
| Execution duration tracking | **No**                               | Yes                                          |
| View run history CLI        | **No**                               | Yes (`cron runs --id <jobId>`)               |
| Structured result objects   | **No** (stdout/stderr only)          | Yes (JSON event payloads)                    |
| Prometheus/metrics export   | **No**                               | Yes (queue depth, run duration, retry count) |

**Gap**: Sase tracks coarse metrics (total cycles, total errors) but doesn't record per-execution history. You can't ask
"when did chop X last succeed?" or "how long did chop X take on its last 5 runs?" OpenClaw stores detailed JSONL run
history per job.

### 5. Output Delivery

| Feature                               | Sase Lumberjacks                | OpenClaw                          |
| ------------------------------------- | ------------------------------- | --------------------------------- |
| Log to file                           | Yes (per-lumberjack output.log) | Yes                               |
| View in TUI                           | Yes (ACE lumberjack tab)        | Yes (via channels)                |
| Webhook delivery                      | **No**                          | Yes (HTTP POST with JSON payload) |
| Chat delivery (Slack, Telegram, etc.) | **No** (at core level)          | Yes (announce to any channel)     |
| Configurable delivery mode per job    | **No**                          | Yes (none, announce, webhook)     |

**Gap**: Chop output goes to log files and the ACE TUI. There's no way to route job results to external services.
OpenClaw can deliver results via webhook or announce them to any connected chat channel.

### 6. Health & Liveness

| Feature                              | Sase Lumberjacks   | OpenClaw                     |
| ------------------------------------ | ------------------ | ---------------------------- |
| PID-based liveness check             | Yes                | Yes                          |
| Automatic restart of crashed workers | Yes (orchestrator) | Yes (gateway)                |
| Status files updated periodically    | Yes (every 5s)     | Yes                          |
| Configurable heartbeat prompts       | **No**             | Yes (custom heartbeat tasks) |
| Health check endpoints (HTTP/WS)     | **No**             | Yes (WebSocket RPC)          |
| Alerting thresholds                  | **No**             | Yes (configurable)           |

**Gap**: Lumberjack health is limited to "is the process alive?" checks. There are no application- level health probes,
no configurable alerting thresholds, and no external health endpoints.

### 7. Concurrency Control

| Feature                    | Sase Lumberjacks                          | OpenClaw                         |
| -------------------------- | ----------------------------------------- | -------------------------------- |
| Global concurrency limits  | Yes (max_hook_runners, max_agent_runners) | Yes (maxConcurrent)              |
| Cross-process coordination | Yes (fcntl.flock)                         | Yes (lane queue)                 |
| Per-session serialization  | **No**                                    | Yes (one active run per session) |
| Zombie process detection   | Yes (configurable timeout)                | N/A                              |

**Parity**: Sase actually has good concurrency control with its SharedRunnerPool. The zombie detection feature is a
strength over OpenClaw.

## Recommended Improvements

Ordered by impact and feasibility:

### P0: High Impact, Moderate Effort

#### 1. Cron Expression Support

Add cron expression scheduling as an alternative to fixed intervals. This is the single most requested scheduling
feature across all automation tools.

```yaml
lumberjacks:
  reports:
    cron: "0 7 * * 1-5" # 7am weekdays
    timezone: "America/New_York"
    chops:
      - name: daily_report
```

**Approach**: Use the `croniter` library (pure Python, well-maintained) to parse cron expressions. Keep the existing
interval-based scheduling as the default. Add a `cron` field to LumberjackConfig as an alternative to `interval`.

#### 2. Per-Chop Enable/Disable

Allow disabling individual chops without removing them from config or restarting.

```bash
sase axe chop disable comment_checks
sase axe chop enable comment_checks
```

**Approach**: Store enabled/disabled state in a `chop_state.json` file alongside `chop_timestamps.json`. Check state
before executing each chop in the lumberjack loop.

#### 3. Retry with Backoff

Add configurable retry for failed chops, with exponential backoff.

```yaml
chops:
  - name: cl_submitted_checks
    retry:
      max_attempts: 3
      backoff: [30, 60, 300] # seconds
      on: [network, rate_limit] # optional error type filter
```

**Approach**: Wrap chop execution in a retry loop. Classify exceptions into transient/permanent categories. Track retry
state in lumberjack memory (no persistence needed -- retries happen within a single cycle).

### P1: Medium Impact, Low-to-Moderate Effort

#### 4. Per-Execution Run History

Store structured execution records for each chop run.

```bash
sase axe chop runs comment_checks        # last 20 runs
sase axe chop runs comment_checks --all  # full history
```

**Approach**: Write a JSONL file per chop under `~/.sase/axe/lumberjacks/{name}/runs/{chop}.jsonl` with fields:
`timestamp`, `duration_ms`, `success`, `error` (if any). Auto-prune to last N entries (e.g., 100). Add a `chop runs` CLI
command.

#### 5. One-Shot Scheduled Jobs

Allow scheduling a chop to run once at a specific time.

```bash
sase axe chop schedule comment_checks --at "2026-03-22 14:00"
sase axe chop schedule comment_checks --in "2h"
```

**Approach**: Store scheduled one-shots in `~/.sase/axe/scheduled.json`. Have a built-in chop in the `hooks` lumberjack
(1-second interval) that checks for due one-shots and executes them. Remove from the file after execution.

#### 6. Configurable Timezone

Replace the hardcoded Eastern timezone with a configurable option.

```yaml
axe:
  timezone: "America/Los_Angeles"
```

**Approach**: Add a `timezone` field to AxeConfig (defaulting to `America/New_York` for backward compatibility). Use
`zoneinfo.ZoneInfo` (stdlib in 3.9+) throughout axe code instead of the hardcoded `EASTERN_TZ`.

### P2: Lower Priority, Higher Effort

#### 7. Webhook Delivery for Chop Results

Allow chops to deliver results to external endpoints.

```yaml
chops:
  - name: error_digest
    delivery:
      mode: webhook
      url: "https://hooks.slack.com/..."
```

**Approach**: After chop execution, POST a JSON payload (chop name, timestamp, duration, success, stdout snippet) to the
configured URL. Use `httpx` (already a dependency) for async delivery. Failure to deliver should not fail the chop
itself.

#### 8. Prometheus Metrics Export

Expose metrics in Prometheus format for external monitoring.

**Approach**: Add an optional lightweight HTTP endpoint (e.g., on a configurable port) that serves `/metrics` in
Prometheus exposition format. Expose counters for chop executions, errors, and histograms for execution duration.

#### 9. Runtime Job Management (Add/Edit/Delete)

Allow adding, editing, and removing chops without restarting the orchestrator.

**Approach**: This is the most complex change. Would require the orchestrator to watch for config changes (via file
watcher or signal) and hot-reload lumberjack configurations. Consider a simpler intermediate step: support a
`sase axe reload` command that gracefully restarts all lumberjacks with updated config.

## What Sase Already Does Well

- **Multi-process architecture**: The orchestrator/lumberjack split with automatic restart is solid.
- **Concurrency control**: SharedRunnerPool with fcntl locking is robust and battle-tested.
- **Zombie detection**: Configurable zombie timeout is a feature OpenClaw lacks.
- **TUI integration**: ACE's lumberjack tab provides live monitoring that OpenClaw users need third-party tools
  (ClaWatch, Mission Control) to get.
- **Agent-based chops**: First-class support for launching AI agents as background jobs is a differentiator.

## Sources

- [OpenClaw Cron Jobs Documentation](https://docs.openclaw.ai/automation/cron-jobs)
- [OpenClaw Heartbeat Documentation](https://docs.openclaw.ai/gateway/heartbeat)
- [OpenClaw Health Monitoring (DeepWiki)](https://deepwiki.com/openclaw/openclaw/14.1-health-monitoring)
- [OpenClaw Concurrency & Retry Control (LumaDock)](https://lumadock.com/tutorials/openclaw-concurrency-retry-control)
- [OpenClaw Skills Documentation](https://docs.openclaw.ai/tools/skills)
- [OpenClaw GitHub](https://github.com/openclaw/openclaw)

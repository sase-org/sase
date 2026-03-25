# Axe — Background Automation Daemon

## Overview

Axe is the background automation subsystem of sase. It monitors ChangeSpecs and automatically executes lifecycle jobs
(hooks, mentors, workflows) on fixed intervals. Axe uses a multi-process architecture: an **Orchestrator** spawns
multiple **Lumberjacks**, each running a subset of jobs on independent schedules.

## Architecture

```
┌──────────────────────────────────────────────┐
│              Orchestrator                    │
│  (spawns & monitors all lumberjacks)         │
├──────────┬──────────┬────────────┬───────────┤
│  hooks   │  checks  │  comments  │ housekeep │
│  (1s)    │  (5min)  │  (1min)    │ (1hr)     │
│          │          │            │           │
│ hook_    │ cl_sub-  │ comment_   │ error_    │
│ checks   │ mitted_  │ checks     │ digest    │
│ mentor_  │ checks   │            │           │
│ checks   │ stale_   │            │           │
│ workflow_│ running_ │            │           │
│ checks   │ cleanup  │            │           │
│ ...      │          │            │           │
└──────────┴──────────┴────────────┴───────────┘
```

### Key Concepts

- **Orchestrator**: Parent process that spawns and monitors all lumberjack processes. Detects crashes and restarts
  failed lumberjacks automatically. Forwards SIGTERM to all children on shutdown.

- **Lumberjack**: Individual scheduler loop that runs a subset of jobs on a fixed interval. Each lumberjack has a name
  (e.g., "hooks", "checks"), runs one or more chops per cycle, and maintains independent state and metrics.

- **Chop**: A single job unit executed by a lumberjack. Can be a script (external executable that reads context JSON) or
  an agent (background process launched via the agent launcher). Chops can be configured with custom environment
  variables and run frequency.

## CLI Commands

| Command                       | Description                                     |
| ----------------------------- | ----------------------------------------------- |
| `sase axe start`              | Start the orchestrator (spawns all lumberjacks) |
| `sase axe stop`               | Stop the orchestrator gracefully                |
| `sase axe chop list`          | List all available chops                        |
| `sase axe chop run <name>`    | Run a single chop in foreground (one-shot)      |
| `sase axe lumberjack list`    | List configured lumberjacks and their chops     |
| `sase axe lumberjack run <n>` | Run a single lumberjack in foreground           |
| `sase axe lumberjack status`  | Show status of all lumberjacks                  |

### Examples

```bash
# Start/stop the daemon
sase axe start
sase axe stop

# Inspect lumberjacks
sase axe lumberjack list
sase axe lumberjack status

# Run a single lumberjack for debugging
sase axe lumberjack run hooks

# Run a single chop once
sase axe chop run hook_checks
```

## Default Lumberjacks

Axe ships with four default lumberjacks:

### hooks (1-second interval)

High-frequency hook lifecycle management:

| Chop                    | Description                                   |
| ----------------------- | --------------------------------------------- |
| `hook_checks`           | Complete finished hooks, start stale ones     |
| `mentor_checks`         | Start mentors once hook prerequisites are met |
| `workflow_checks`       | Complete/start CRS and fix-hook workflows     |
| `pending_checks_poll`   | Poll background check results                 |
| `comment_zombie_checks` | Mark old comment threads as ZOMBIE            |
| `suffix_transforms`     | Strip stale suffixes, update mail-readiness   |
| `orphan_cleanup`        | Release workspace claims for dead processes   |
| `wait_checks`           | Resolve agent wait dependencies               |

### checks (5-minute interval)

Lower-frequency status checks:

| Chop                    | Description                                  |
| ----------------------- | -------------------------------------------- |
| `cl_submitted_checks`   | Start CL submission status checks            |
| `stale_running_cleanup` | Release workspace claims from dead processes |

### comments (1-minute interval)

Comment polling:

| Chop             | Description                   |
| ---------------- | ----------------------------- |
| `comment_checks` | Start critique comment checks |

### housekeeping (1-hour interval)

Periodic maintenance:

| Chop           | Description                     |
| -------------- | ------------------------------- |
| `error_digest` | Send error notification digests |

## Configuration

Axe is configured in `sase.yml` under the `axe:` section. See [`docs/configuration.md`](configuration.md) for the full
configuration reference.

### Global Settings

| Setting                  | Default | Description                               |
| ------------------------ | ------- | ----------------------------------------- |
| `max_hook_runners`       | 3       | Concurrent hook runners allowed globally  |
| `max_agent_runners`      | 3       | Concurrent agent runners allowed globally |
| `zombie_timeout_seconds` | 7200    | Timeout for marking jobs as zombie        |
| `query`                  | `""`    | Optional query filter for all changespecs |
| `chop_script_dirs`       | `[]`    | Directories to search for chop scripts    |

### Lumberjack Configuration

```yaml
axe:
  lumberjacks:
    my_lumberjack:
      interval: 60 # Seconds between cycles
      chops:
        - name: my_chop
          description: "What this chop does"
          agent: my_agent # Optional — runs as background agent process
          run_every: "5m" # Time-based duration: run at most once per 5 minutes
          env:
            MY_VAR: "value" # Custom environment variables
```

## Concurrency Management

Axe uses a cross-process runner pool to enforce global concurrency limits. The `SharedRunnerPool` uses `fcntl.flock` on
a shared file (`~/.sase/axe/shared/runner_count`) to coordinate runner slots across all lumberjack processes atomically.

Hook runners and agent runners have separate limits (`max_hook_runners` and `max_agent_runners`), allowing fine-grained
control over background resource usage.

## State Directory

```
~/.sase/axe/
├── orchestrator.pid                # Orchestrator PID
├── logs/
│   ├── axe.log                     # Orchestrator startup log
│   └── lumberjack-{name}.log       # Per-lumberjack logs
├── lumberjacks/
│   └── {name}/                     # Per-lumberjack state
│       ├── pid                     # Lumberjack PID
│       ├── status.json             # Current status (updated every 5s)
│       ├── metrics.json            # Cumulative metrics (updated every 30s)
│       └── logs/
│           └── output.log          # Lumberjack output log
├── shared/
│   └── runner_count                # Cross-process runner counter
└── recent_errors.json              # Last 100 errors encountered
```

## Error Reporting

When an axe runner (CRS, fix-hook, mentor, summarize-hook) encounters an error, the system captures structured error
information:

- **done.json** — Written to the runner's artifacts directory on completion. Includes `error` (summary string) and
  `traceback` (formatted traceback) fields when the run fails.
- **error_report.md** — A formatted markdown error report written to the artifacts directory, containing model,
  workflow, CL name, duration, error message, and traceback.
- **Notifications** — Error notifications are sent with a `ViewErrorReport` action, allowing you to view the full error
  report from the ACE notification panel.

The `error_digest` chop in the housekeeping lumberjack periodically sends digest notifications summarizing recent errors
from `recent_errors.json`.

## Process Lifecycle

1. `sase axe start` spawns the orchestrator as a detached background process
2. The orchestrator spawns all configured lumberjacks as child processes
3. Each lumberjack runs its chops on its configured interval
4. The orchestrator monitors children and restarts any that exit unexpectedly
5. `sase axe stop` sends SIGTERM to the orchestrator, which forwards it to all children
6. If children don't exit within 10 seconds, SIGKILL is sent

## ACE Integration

The Axe tab in the ACE TUI provides live monitoring of the daemon:

- View lumberjack status, uptime, and error counts
- Read lumberjack output logs
- Start/stop the orchestrator (`X` key or `!x`)
- See current runner counts

See [`docs/ace.md`](ace.md) for the full Axe tab keybinding reference.

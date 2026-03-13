# Axe — Background Automation Daemon

## Overview

Axe is the background automation subsystem of sase. It monitors ChangeSpecs and automatically executes lifecycle jobs
(hooks, mentors, workflows) on fixed intervals. Axe uses a multi-process architecture: an **Orchestrator** spawns
multiple **Jacks**, each running a subset of jobs on independent schedules.

## Architecture

```
┌──────────────────────────────────────────────┐
│              Orchestrator                    │
│  (spawns & monitors all jacks)         │
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

- **Orchestrator**: Parent process that spawns and monitors all jack processes. Detects crashes and restarts failed
  jacks automatically. Forwards SIGTERM to all children on shutdown.

- **Jack**: Individual scheduler loop that runs a subset of jobs on a fixed interval. Each jack has a name (e.g.,
  "hooks", "checks"), runs one or more chops per cycle, and maintains independent state and metrics.

- **Chop**: A single job unit executed by a jack. Can be a script (external executable that reads context JSON) or an
  agent (background process launched via agent_launcher). Chops can be configured with custom environment variables and
  run frequency.

## CLI Commands

| Command                    | Description                                |
| -------------------------- | ------------------------------------------ |
| `sase axe start`           | Start the orchestrator (spawns all jacks)  |
| `sase axe stop`            | Stop the orchestrator gracefully           |
| `sase axe chop list`       | List all available chops                   |
| `sase axe chop run <name>` | Run a single chop in foreground (one-shot) |
| `sase axe jack list`       | List configured jacks and their chops      |
| `sase axe jack run <n>`    | Run a single jack in foreground            |
| `sase axe jack status`     | Show status of all jacks                   |

### Examples

```bash
# Start/stop the daemon
sase axe start
sase axe stop

# Inspect jacks
sase axe jack list
sase axe jack status

# Run a single jack for debugging
sase axe jack run hooks

# Run a single chop once
sase axe chop run hook_checks
```

## Default Jacks

Axe ships with four default jacks:

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
| `max_agent_retries`      | 3       | Retry attempts for failed agent launches  |
| `zombie_timeout_seconds` | 7200    | Timeout for marking jobs as zombie        |
| `query`                  | `""`    | Optional query filter for all changespecs |
| `chop_script_dirs`       | `[]`    | Directories to search for chop scripts    |

### Jack Configuration

```yaml
axe:
  jacks:
    my_jack:
      interval: 60 # Seconds between cycles
      chops:
        - name: my_chop
          description: "What this chop does"
          agent: my_agent # Optional — runs as background agent process
          run_every: 5 # Run every 5th cycle (default: 1)
          env:
            MY_VAR: "value" # Custom environment variables
```

## Concurrency Management

Axe uses a cross-process runner pool to enforce global concurrency limits. The `SharedRunnerPool` uses `fcntl.flock` on
a shared file (`~/.sase/axe/shared/runner_count`) to coordinate runner slots across all jack processes atomically.

Hook runners and agent runners have separate limits (`max_hook_runners` and `max_agent_runners`), allowing fine-grained
control over background resource usage.

## State Directory

```
~/.sase/axe/
├── orchestrator.pid                # Orchestrator PID
├── logs/
│   ├── axe.log                     # Orchestrator startup log
│   └── jack-{name}.log       # Per-jack logs
├── jacks/
│   └── {name}/                     # Per-jack state
│       ├── pid                     # Jack PID
│       ├── status.json             # Current status (updated every 5s)
│       ├── metrics.json            # Cumulative metrics (updated every 30s)
│       └── logs/
│           └── output.log          # Jack output log
├── shared/
│   └── runner_count                # Cross-process runner counter
└── recent_errors.json              # Last 100 errors encountered
```

## Process Lifecycle

1. `sase axe start` spawns the orchestrator as a detached background process
2. The orchestrator spawns all configured jacks as child processes
3. Each jack runs its chops on its configured interval
4. The orchestrator monitors children and restarts any that exit unexpectedly
5. `sase axe stop` sends SIGTERM to the orchestrator, which forwards it to all children
6. If children don't exit within 10 seconds, SIGKILL is sent

## ACE Integration

The Axe tab in the ACE TUI provides live monitoring of the daemon:

- View jack status, uptime, and error counts
- Read jack output logs
- Start/stop the orchestrator (`X` key or `!x`)
- See current runner counts

See [`docs/ace.md`](ace.md) for the full Axe tab keybinding reference.

# Axe — Background Automation Daemon

## Overview

Axe is the background automation subsystem of sase. It monitors ChangeSpecs and automatically executes lifecycle jobs
(hooks, mentors, workflows) on fixed intervals. Axe uses a multi-process architecture: an **Orchestrator** spawns
multiple **Lumberjacks**, each running a subset of jobs on independent schedules.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator                          │
│  (spawns & monitors all lumberjacks)                    │
├──────────┬──────────┬──────────┬────────────┬───────────┤
│  hooks   │  waits   │  checks  │  comments  │ housekeep │
│  (5s)    │  (2s)    │  (5min)  │  (1min)    │ (1hr)     │
│          │          │          │            │           │
│ hook_    │ wait_    │ cl_sub-  │ comment_   │ error_    │
│ checks   │ checks   │ mitted_  │ checks     │ digest    │
│ mentor_  │          │ checks   │            │           │
│ checks   │          │ stale_   │            │           │
│ workflow_│          │ running_ │            │           │
│ checks   │          │ cleanup  │            │           │
│ ...      │          │          │            │           │
└──────────┴──────────┴──────────┴────────────┴───────────┘
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

Axe ships with five default lumberjacks:

### hooks (5-second interval)

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

### waits (2-second interval)

Fast-polling agent dependency resolution:

| Chop          | Description                                                           |
| ------------- | --------------------------------------------------------------------- |
| `wait_checks` | Resolve agent wait dependencies and write `ready.json` when satisfied |

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

| Chop           | Description                                                                     |
| -------------- | ------------------------------------------------------------------------------- |
| `error_digest` | Send error notification digests (creates `ViewErrorReport` notification action) |

The `error_digest` chop summarizes recent errors into a digest file stored at
`~/.sase/axe/error_digests/digest_<timestamp>.txt`. The notification includes a `ViewErrorReport` action that opens the
digest in `$EDITOR` when selected in the ACE notification modal.

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
      chop_timeout: "60s" # Default timeout for all chops in this lumberjack
      chops:
        - name: my_chop
          description: "What this chop does"
          agent: my_agent # Optional — runs as background agent process
          run_every: "5m" # Time-based duration: run at most once per 5 minutes
          timeout: "30s" # Per-chop timeout (overrides chop_timeout)
          env:
            MY_VAR: "value" # Custom environment variables
```

#### Chop Fields

| Field         | Type             | Description                                                            |
| ------------- | ---------------- | ---------------------------------------------------------------------- |
| `name`        | `str`            | Chop identifier (required)                                             |
| `description` | `str`            | Human-readable description (required)                                  |
| `agent`       | `str \| null`    | XPrompt/agent name — runs as a background agent process                |
| `run_every`   | `str \| null`    | Duration string (e.g., `"5m"`, `"2h"`) — run at most once per interval |
| `timeout`     | `str \| null`    | Per-chop timeout duration (overrides the lumberjack's `chop_timeout`)  |
| `env`         | `dict[str, str]` | Custom environment variables passed to the chop                        |

### Agent Chops and Visibility

When a chop has an `agent` field, axe launches a real background agent (via the same launcher as `sase run`) instead of
shelling out to a chop script. Configured agent chops are **visible by default** in the Agents tab — recurring infra
agents (e.g. orchestration housekeepers) show up alongside user-launched agents so their state, retries, and last output
are discoverable. Use the prompt-side `%hide` directive if a particular chop should remain hidden.

`sase axe chop run <agent-chop>` follows the same path as the scheduled lumberjack tick, so a one-shot run records the
same chop registry metadata as the periodic invocation.

### Chop-Agent Registry

Each lumberjack maintains a durable JSON registry of the agents it has launched at
`~/.sase/axe/lumberjacks/<name>/agent_chops.json`. Records carry the lumberjack/chop names, a normalized `prompt_hash`,
the launched PID, the agent's artifacts timestamp, and a per-launch UUID. The registry is what lets a recurring chop
dedup against an in-flight run with the same prompt body, survive lumberjack restarts (sase-12 perf overhaul), and be
reattributed correctly in the Agents tab. The metadata is also propagated into the agent's `agent_meta.json` via the env
vars `SASE_CHOP_LUMBERJACK`, `SASE_CHOP_NAME`, `SASE_CHOP_RUN_ID`, and `SASE_CHOP_PROMPT_HASH` (see
`build_chop_launch_env()` in `src/sase/axe/chop_agents.py`).

## Concurrency Management

Axe uses a cross-process runner pool to enforce global concurrency limits. The `SharedRunnerPool` uses `fcntl.flock` on
a shared file (`~/.sase/axe/shared/runner_count`) to coordinate runner slots across all lumberjack processes atomically.

Hook runners and agent runners have separate limits (`max_hook_runners` and `max_agent_runners`), allowing fine-grained
control over background resource usage.

## Agent Completion Artifacts

When an agent run finalizes, axe writes the normal completion metadata and sends the workflow-complete notification.
Successful runs also scan the agent workspace for generated image files (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`) and
Markdown files (`.md`, `.markdown`). Markdown sources are rendered to PDFs under the agent artifact directory, then the
generated PDF paths are appended after the standard chat/diff notification attachments and before image attachments. The
PDF list is persisted as `done.json.markdown_pdf_paths`; the image list is persisted as `done.json.image_paths`.

The scan uses git name-status output, untracked files, saved diff metadata, and the latest commit when the agent
committed or opened a PR. Deleted, missing, unsupported, and duplicate paths are ignored. PDF rendering is best-effort:
missing conversion tools or render failures omit that source without failing the agent run. See
[`agent_images.md`](agent_images.md) for the full contract.

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
│       ├── agent_chops.json        # Durable registry of agents launched by this lumberjack's chops
│       └── logs/
│           └── output.log          # Lumberjack output log
├── shared/
│   └── runner_count                # Cross-process runner counter
├── error_digests/                   # Error digest files for ViewErrorReport
│   └── digest_<timestamp>.txt      # Summarized error reports
└── recent_errors.json              # Last 100 errors encountered
```

## Process Lifecycle

1. `sase axe start` checks for an existing orchestrator via PID file. If one is running, it sends SIGTERM (waits 15
   seconds) then SIGKILL if needed, preventing duplicate orchestrators from corrupting shared state
2. The orchestrator spawns all configured lumberjacks as child processes
3. Each lumberjack runs its chops on its configured interval
4. The orchestrator monitors children and restarts any that exit unexpectedly
5. `sase axe stop` sends SIGTERM to the orchestrator, which forwards it to all children
6. If children don't exit within 10 seconds, SIGKILL is sent

## ACE Integration

The Axe tab in the ACE TUI provides live monitoring of the daemon:

- View lumberjack status, uptime, and error counts
- Read lumberjack output logs
- Start/stop the orchestrator (`x` key or `!x`)
- See current runner counts
- Footer shows daemon status: RUNNING, STOPPED, STARTING, STOPPING, or RESTARTING

The RESTARTING indicator appears when `sase ace --restart-axe` (`-R`) is used — the daemon restarts in the background
while the TUI starts up normally.

See [`docs/ace.md`](ace.md) for the full Axe tab keybinding reference.

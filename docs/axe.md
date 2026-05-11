# Axe — Background Automation Daemon

## Overview

Axe is the background automation subsystem of sase. It watches ChangeSpecs (the per-CL/PR records that sase uses to
track work) and periodically runs lifecycle jobs such as hook completion, mentor launch, workflow cleanup, comment
polling, `%wait` dependency checks, and error digests.

Axe uses a multi-process architecture: an **Orchestrator** spawns multiple **Lumberjacks**, and each lumberjack runs a
subset of jobs on its own schedule. The ACE TUI starts axe automatically unless launched with `sase ace --no-axe`;
operators can also manage it directly with `sase axe start` and `sase axe stop`.

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
  failed lumberjacks automatically. Holds the axe lifecycle lock while running and forwards SIGTERM to all children on
  shutdown.

- **Lumberjack**: Individual scheduler loop that runs a subset of jobs on a fixed interval. Each lumberjack has a name
  (e.g., "hooks", "checks"), runs one or more chops per cycle, and maintains independent state and metrics.

- **Chop**: A single job unit executed by a lumberjack. Can be a script (external executable that reads context JSON) or
  an agent (background process launched via the agent launcher). Chops can be configured with custom environment
  variables and run frequency.

## CLI Commands

| Command                          | Description                                     |
| -------------------------------- | ----------------------------------------------- |
| `sase axe start`                 | Start the orchestrator (spawns all lumberjacks) |
| `sase axe stop`                  | Stop the orchestrator gracefully                |
| `sase axe chop list`             | List configured chops                           |
| `sase axe chop run <name>`       | Run a single chop in the foreground             |
| `sase axe lumberjack list`       | List configured lumberjacks and their chops     |
| `sase axe lumberjack run <name>` | Run a single lumberjack in the foreground       |
| `sase axe lumberjack status`     | Show status of all lumberjacks                  |
| `sase axe maintenance enter`     | Pause lumberjack ticks until maintenance exits  |
| `sase axe maintenance exit`      | Clear the maintenance marker                    |
| `sase axe maintenance status`    | Show whether maintenance mode is active         |

### Examples

```bash
# Start/stop the daemon
sase axe start
sase axe stop

# Run axe against only matching ChangeSpecs
sase axe start --query '!!! OR @@@'

# Inspect lumberjacks
sase axe lumberjack list
sase axe lumberjack status

# Run a single lumberjack for debugging
sase axe lumberjack run hooks

# Run a single chop once
sase axe chop run hook_checks

# Pause/resume scheduled lumberjack work
sase axe maintenance enter --reason "install plugin update"
sase axe maintenance status
sase axe maintenance exit
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

| Chop          | Description                                                       |
| ------------- | ----------------------------------------------------------------- |
| `wait_checks` | Resolve successful agent wait dependencies and write `ready.json` |

`wait_checks` only unblocks a named dependency when the newest matching agent, or the newest matching workflow root and
all of its children, has a `done.json` outcome of `"completed"`. Failed, killed, crashed, still-running, malformed, or
missing `done.json` artifacts do not satisfy `%wait`; the dependent agent remains parked until a later successful run of
the same dependency name appears.

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

The `query` setting uses the same ChangeSpec query language as ACE. CLI flags on `sase axe start` and
`sase axe lumberjack run` override the configured query, runner limits, and zombie timeout for that process.

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

### Script Chops

When a chop does not have an `agent` field, axe treats it as an external executable. The executable is resolved in this
order:

1. An executable named exactly like the chop in one of `axe.chop_script_dirs`.
2. An executable named `sase_chop_<name>` beside the running Python interpreter.
3. An executable named `sase_chop_<name>` on `$PATH`.

Axe runs script chops as:

```bash
<script> --context <context.json>
```

The context file contains the effective runner limits, zombie timeout, query, lumberjack name, lumberjack state
directory, and paths to serialized `all_changespecs.json` and `filtered_changespecs.json` files. Scheduled script chops
within one lumberjack tick run concurrently; use `timeout` or `chop_timeout` to keep a slow script from blocking later
ticks indefinitely.

Script chop stdout and stderr are streamed to the chop's per-run log file while the subprocess is still alive (see
[Chop Run History](#chop-run-history) below). The Axe-tab dashboard tails that file so a long-running chop's output
becomes visible immediately rather than only after process exit.

### Agent Chops and Visibility

When a chop has an `agent` field, axe launches a real background agent (via the same launcher as `sase run`) instead of
shelling out to a chop script. Configured agent chops are **visible by default** in the Agents tab — recurring infra
agents (e.g. orchestration housekeepers) show up alongside user-launched agents so their state, retries, and last output
are discoverable. Use the prompt-side `%hide` directive if a particular chop should remain hidden.

Specialized review agents launched by axe runners (mentor, CRS, fix-hook, and summarize-hook review agents) write
Agents-tab metadata as well. They persist the same `review` tag that a `%group:review` prompt would produce, so ACE
groups them in the `@review` side panel instead of hiding them among untagged automation rows.

During a scheduled lumberjack tick, script chops are still dispatched concurrently, but eligible agent chops are
launched sequentially in their configured order. That keeps multiple same-tick `run_every` agent chops from racing each
other for workspace allocation while preserving parallel script execution.

`sase axe chop run <agent-chop>` follows the same path as the scheduled lumberjack tick, so a one-shot run records the
same chop registry metadata as the periodic invocation.

### Chop Run History

Each lumberjack tick (and each `sase axe chop run …`) records the attempt under
`~/.sase/axe/lumberjacks/<lumberjack>/chops/<chop>/`. The newest 10 runs per chop are retained; older runs are pruned on
the next launch. A live `index.json` lists run IDs newest-first, and each run has its own metadata JSON plus an output
log:

```
~/.sase/axe/lumberjacks/<lumberjack>/chops/<chop>/
├── index.json              # Ordered run IDs (newest first)
└── <run_id>/
    ├── metadata.json       # status, started_at, finished_at, pid, source, started_by, exit code
    └── output.log          # Streamed stdout+stderr from the chop process
```

A run is created in `running` state before the subprocess is launched and finalized (`completed`, `failed`, or
`timeout`) on exit. `finished_at` is `null` while the run is still active. Pruning never deletes an in-flight run, so a
slow chop is safe even if its `MAX_CHOP_RUN_HISTORY` window shifts during execution.

### AXE Tab Views

The Axe tab sidebar emits each lumberjack as a top-level row with its configured chops as indented children, followed by
any background commands (`!!`). Selection drives three distinct dashboard views:

- **Lumberjack overview** — selecting a lumberjack row shows its status, interval, cycle count, error count, and a
  per-chop table with each chop's last-run status, relative timestamp, and elapsed runtime. Running chops report live
  elapsed time instead of `0ms`.
- **Chop detail** — selecting a chop row renders the latest run's metadata (`● running` status with live elapsed
  runtime, PID, and a `Source:` chip for non-scheduled runs) and tails its `output.log`. While the run is still
  producing nothing, the panel shows a `Waiting for output…` placeholder; the exit code is suppressed until the run
  finalizes. Sidebar chop rows render a `[●]` marker when the newest cached run is active.
- **Background command output** — the existing live output stream for the focused `!!` row.

`Ctrl+N` / `Ctrl+P` on the Axe tab page through the focused chop's run history (newest run first). The viewer pins to
the run you selected so that a new run prepended by a fresh tick does not bump you forward; if the pinned run is pruned
or itself becomes newest, the pin is cleared.

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
Markdown files (`.md`, `.markdown`). When 10 or fewer Markdown sources are discovered after filtering, they are rendered
to PDFs under the agent artifact directory, then the generated PDF paths are appended after the standard chat/diff
notification attachments and before image attachments. The PDF list is persisted as `done.json.markdown_pdf_paths`; the
image list is persisted as `done.json.image_paths`.

The scan uses git name-status output, untracked files, saved diff metadata, and the latest commit when the agent
committed or opened a PR. Deleted, missing, unsupported, and duplicate paths are ignored. If more than 10 Markdown
sources remain, Axe skips Markdown PDF rendering for that completion and adds a note to the notification. PDF rendering
is otherwise best-effort: missing conversion tools or render failures omit that source without failing the agent run.
Generated Markdown PDFs are optimized for narrow viewers with a small portrait page, small margins, and larger type. As
PDFs are prepared, axe updates `workflow_state.json.pdf_status` and a compact `activity` label so ACE can show live
finalization progress such as `PDF 2/4 <path>` or `PDFs done 3/4 (1 skipped)`. See [`agent_images.md`](agent_images.md)
for the full contract.

The Agents tab exposes completion artifacts through the `A` action. When artifacts exist, ACE opens the artifact panel
for selection. Chat transcripts, plan files, generated PDFs/images, prompt-referenced images from saved prompt
artifacts, and explicit artifacts created with `sase artifact create -p <path> [-n <label>] [-k <kind>]` all participate
in the same list. Explicit artifacts are stored under `~/.sase/artifacts/` with a persistent association so they remain
available after dismissing and later reviving the agent. ACE shows the picker even for a single artifact; `m` marks
rows, `Enter` opens the marked set or highlighted row, and `A` opens the full list. Only one plan artifact is listed for
an agent, preferring the committed SDD plan path when one exists. Inside tmux, artifact viewing opens in a right-side
tmux pane, collapses the Agents list while live, uses `l` to focus the pane, and uses `A` to close it; outside tmux, ACE
suspends and uses the current pane. The viewer supports images, Markdown, and PDFs, wraps `j`/`k` page navigation at the
ends, uses `n`/`p` for artifact-sequence navigation, and warns when required terminal/rendering tools are missing. The
direct agent run-log binding is `V`.

## Maintenance Mode

Maintenance mode is a lightweight pause switch for scheduled axe work. `sase axe maintenance enter --reason <text>`
writes `~/.sase/axe/maintenance.json` with the reason, caller PID, and start timestamp. Each lumberjack checks that
marker at the start of every tick; while it is active, the lumberjack records a cycle and skips the chop execution for
that tick.

Use maintenance mode before operations that temporarily make scheduled work unsafe or noisy, such as installing plugin
updates, moving workspace directories, or running one-off cleanup. `sase axe maintenance exit` removes the marker.
`sase axe maintenance status` exits 0 when active and 1 when inactive, so scripts can use it as a guard. The next
lumberjack tick clears stale markers automatically when they are older than 24 hours, malformed, or owned by a PID that
is no longer running.

## State Directory

```
~/.sase/axe/
├── orchestrator.pid                # Orchestrator PID
├── orchestrator.lock               # Exclusive lifecycle lock held by the live orchestrator
├── maintenance.json                # Optional maintenance marker that pauses lumberjack ticks
├── logs/
│   ├── axe.log                     # Orchestrator startup log
│   └── lumberjack-{name}.log       # Per-lumberjack logs
├── lumberjacks/
│   └── {name}/                     # Per-lumberjack state
│       ├── pid                     # Lumberjack PID
│       ├── status.json             # Current status (updated every 5s)
│       ├── metrics.json            # Cumulative metrics (updated every 30s)
│       ├── chop_timestamps.json    # Last successful run_every timestamp per chop
│       ├── agent_chops.json        # Durable registry of agents launched by this lumberjack's chops
│       ├── chops/                  # Per-chop run history (newest 10 runs per chop)
│       │   └── {chop}/
│       │       ├── index.json      # Ordered run IDs (newest first)
│       │       └── {run_id}/
│       │           ├── metadata.json
│       │           └── output.log
│       ├── tick/
│       │   ├── context.json        # Context passed to script chops
│       │   ├── all_changespecs.json
│       │   └── filtered_changespecs.json
│       └── logs/
│           └── output.log          # Lumberjack output log
├── shared/
│   └── runner_count                # Cross-process runner counter
├── error_digests/                   # Error digest files for ViewErrorReport
│   └── digest_<timestamp>.txt      # Summarized error reports
└── recent_errors.json              # Last 100 errors encountered
```

## Process Lifecycle

1. `sase axe start` first checks for a live orchestrator PID. If one exists, start is a no-op and returns the existing
   PID.
2. If no live PID exists, startup acquires `~/.sase/axe/orchestrator.lock` and hands that lock to the detached
   orchestrator process. Concurrent starts wait briefly and then return the live PID or decline to start.
3. The orchestrator removes stale PID files, adopts/holds the lifecycle lock, writes `orchestrator.pid`, and spawns all
   configured lumberjacks as child processes.
4. Each lumberjack runs its chops on its configured interval, unless maintenance mode is active.
5. The orchestrator monitors children and restarts any that exit unexpectedly.
6. `sase axe stop` sends SIGTERM to the orchestrator, which forwards it to all children. If the orchestrator does not
   exit within the stop timeout, the stopper escalates to SIGKILL and cleans up stale PID files.

## ACE Integration

The Axe tab in the ACE TUI provides live monitoring of the daemon:

- A lumberjack tree sidebar (lumberjack rows + their chops as children + background-command rows)
- A lumberjack overview, per-chop detail view, and run-history pager (see [AXE Tab Views](#axe-tab-views))
- Start/stop the orchestrator (`x` key or `!x`) and runner counts
- Footer shows daemon status: RUNNING, STOPPED, STARTING, STOPPING, or RESTARTING

The RESTARTING indicator appears when `sase ace --restart-axe` (`-R`) is used — the daemon restarts in the background
while the TUI starts up normally.

See [`docs/ace.md`](ace.md) for the full Axe tab keybinding reference.

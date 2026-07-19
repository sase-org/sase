# Axe — Background Automation Daemon

## Overview

Axe is the background automation subsystem of sase. It watches ChangeSpecs (the per-PR records that sase uses to track
work) and periodically runs lifecycle jobs such as hook completion, mentor launch, workflow cleanup, comment polling,
`%wait` dependency checks, and error digests.

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
│  (5s)    │  (10s)   │  (5min)  │  (1min)    │ (1hr)     │
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

- **Chop**: A single script-only job unit executed by a lumberjack. The executable reads context JSON and may return a
  structured result containing validated agent-launch proposals. The runner, never the script, launches those agents.
  Chops can declare cadence, triggers, guards, target fan-out, environment, and dedupe policy.

## CLI Commands

`sase axe chop` and `sase axe lumberjack` default to their `list` views when invoked without a nested subcommand.

| Command                                    | Description                                            |
| ------------------------------------------ | ------------------------------------------------------ |
| `sase axe start`                           | Start the orchestrator (spawns all lumberjacks)        |
| `sase axe stop`                            | Stop the orchestrator gracefully                       |
| `sase axe chop list`                       | List configured chops with status (`-a` adds scripts)  |
| `sase axe chop doctor`                     | Diagnose configured/available chops and Telegram setup |
| `sase axe chop run <name>`                 | Run a single chop in the foreground                    |
| `sase axe chop run <name> -L <lumberjack>` | Run a single chop attributed to a specific lumberjack  |
| `sase axe lumberjack list`                 | List configured lumberjacks and their chops            |
| `sase axe lumberjack run <name>`           | Run a single lumberjack in the foreground              |
| `sase axe lumberjack status`               | Show status of all lumberjacks                         |
| `sase axe maintenance enter`               | Pause lumberjack ticks until maintenance exits         |
| `sase axe maintenance exit`                | Clear the maintenance marker                           |
| `sase axe maintenance status`              | Show whether maintenance mode is active                |

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

# Inspect configured chops and discoverable scripts
sase axe chop list
sase axe chop list --available --verbose
sase axe chop doctor            # exits 1 if a configured script chop cannot be resolved

# Run a single chop once
sase axe chop run hook_checks

# Preview a proposal-emitting chop without launching agents
sase axe chop run 'refresh_docs[sase]' -L docs --dry-run --chop-verbose

# Disambiguate when the same chop name appears in multiple lumberjacks
sase axe chop run hook_checks --lumberjack hooks   # -L is the short form

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
| `stale_running_cleanup` | Release workspace claims from dead processes  |

### waits (10-second interval)

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

| Chop                    | Description                         |
| ----------------------- | ----------------------------------- |
| `pr_submitted_checks`   | Start PR submission status checks   |
| `stale_running_cleanup` | Backstop dead-process claim cleanup |

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

| Setting                          | Default  | Description                                             |
| -------------------------------- | -------- | ------------------------------------------------------- |
| `max_hook_runners`               | 3        | Concurrent hook runners allowed globally                |
| `max_agent_runners`              | 3        | Concurrent agent runners allowed globally               |
| `zombie_timeout_seconds`         | 7200     | Timeout for marking jobs as zombie                      |
| `query`                          | `""`     | Optional query filter for all changespecs               |
| `chop_script_dirs`               | `[]`     | Directories to search for chop scripts                  |
| `lumberjack_log_max_bytes`       | 52428800 | Maximum bytes retained for each bounded lumberjack log  |
| `verbose_lumberjack_diagnostics` | false    | Include verbose diagnostics in chop script context JSON |

The `query` setting uses the same ChangeSpec query language as ACE. CLI flags on `sase axe start` and
`sase axe lumberjack run` override the configured query, runner limits, and zombie timeout for that process.

### Lumberjack Configuration

```yaml
axe:
  lumberjacks:
    my_lumberjack:
      interval: 60 # Seconds between cycles
      chop_timeout: "60s" # Default timeout for all chops in this lumberjack
      env: # Inherited by every chop; individual chop env wins
        API_TOKEN: { env: MY_API_TOKEN }
      chops:
        my_chop:
          script: my_chop_executable # Optional; defaults to name
          description: "What this chop does"
          run_every: "1h30m" # Run at most once per compound duration
          timeout: "30s" # Per-chop timeout (overrides chop_timeout)
          env:
            MY_VAR: "value" # Custom environment variables
          inhibit_if:
            agent_hood: { hood: busy_workers }
          trigger:
            git.commits_since:
              project: "{target.name}"
              threshold: 10
              checkpoint: on_action_success
          once_per: "{target.name}:{proposal.id}"
          for_each:
            source: projects # One stable my_chop[project] instance per enabled project
            vcs: [git, gh]
```

#### Chop Fields

| Field         | Type                   | Description                                                                           |
| ------------- | ---------------------- | ------------------------------------------------------------------------------------- |
| `name`        | `str`                  | Chop identity in legacy list form; map form uses the mapping key                      |
| `script`      | `str \| null`          | Exact executable name; defaults to the chop identity                                  |
| `enabled`     | `bool`                 | Soft-disable a keyed entry without deleting the packaged/base configuration           |
| `description` | `str`                  | Human-readable description                                                            |
| `run_every`   | `str \| null`          | Positive compound duration (e.g., `"5m"`, `"1h30m"`, `"1d"`)                          |
| `timeout`     | `str \| null`          | Per-chop timeout duration (overrides the lumberjack's `chop_timeout`)                 |
| `env`         | `dict[str, env-value]` | Values merged over lumberjack env; literals or `{env:}`, `{file:}`, `{pass:}` refs    |
| `inhibit_if`  | list or map            | `changespec` / `agent_hood` guards evaluated before the script                        |
| `trigger`     | string or map          | `always` or `git.commits_since`; scheduled runs fire only when it accepts             |
| `once_per`    | string or object       | Bounded per-proposal dedupe-key template                                              |
| `for_each`    | list or source         | Literal target objects or `source: projects`, expanded to stable per-target instances |
| `vars`        | `dict`                 | Non-secret configuration copied into the script context                               |

Map-form chops compose by identity across config layers. A higher-priority layer can patch a single field or set
`enabled: false` while retaining the rest of a packaged entry. Legacy list form remains accepted. Target instances use
names such as `my_chop[sase-core]`, with independent cadence, run history, checkpoints, and dedupe state. Literal
targets may include an `overrides:` object for per-target fields such as `run_every`; the `projects` source accepts
`name`/`names` and `vcs` filters.

Configuration is validated fail-closed. Unknown fields, duplicate chop identities, and invalid or non-positive durations
produce actionable errors with their config paths. Secret references resolve at dispatch and fail closed with
provider-specific diagnostics. Legacy `agent:` and `xprompt:` chop fields are rejected: scheduled agent work must
originate from a script's structured launch proposals.

### Script Chops

Every chop is an external executable. Axe resolves the exact configured `script` value (or `name` when `script` is
omitted) in this order:

1. An exact-name executable in one of `axe.chop_script_dirs`.
2. An exact-name executable beside the running Python interpreter.
3. An exact-name executable on `$PATH`.

No prefix is added automatically. Builtin chops therefore declare names such as `script: sase_chop_hook_checks`
explicitly. The available-script inventory still scans `$PATH` for `sase_chop_*` executables as a discovery convenience,
but resolution always uses the configured full name.

Axe runs script chops as:

```bash
<script> --context <context.json>
```

The context file contains the effective runner limits, zombie timeout, query, lumberjack name, lumberjack state
directory, paths to serialized `all_changespecs.json` and `filtered_changespecs.json` files, the current `target`,
configured `vars`, and the run-local result path. The result path is also exported as `SASE_CHOP_RESULT_FILE`.
`SASE_CHOP_VERBOSE` enables opt-in debug output. Target fields are exported as `SASE_CHOP_TARGET_<FIELD>` along with
`SASE_CHOP_TARGET_KEY`. Scheduled script chops within one lumberjack tick run concurrently; use `timeout` or
`chop_timeout` to keep a slow script from blocking later ticks indefinitely.

Script chop stdout and stderr are streamed to the chop's per-run log file while the subprocess is still alive (see
[Chop Run History](#chop-run-history) below). The Axe-tab dashboard tails that file so a long-running chop's output
becomes visible immediately rather than only after process exit.

Chop output is part of the operator contract. Every actual chop run should write a compact, human-readable summary for
both no-op and action paths. At minimum, include the chop identity or run scope, counts of inspected/skipped/updated or
launched items, an explicit no-op reason, and bounded identifiers for any affected items. Avoid tokens, full
notification bodies, full prompts, and unbounded command output in ordinary AXE logs.

#### Structured Results and Launch Proposals

Exit-code-only scripts remain supported: exit zero means `success`, a non-zero exit means `failure`, and no result file
is required. A proposal-emitting script atomically writes a schema-versioned JSON document to `SASE_CHOP_RESULT_FILE`:

```json
{
  "schema_version": 1,
  "status": "ok",
  "summary": "refresh_docs: targets=1 proposals=2",
  "counters": { "targets": 1, "proposals": 2 },
  "proposed_launches": [
    {
      "id": "update",
      "prompt": "Refresh the user documentation.",
      "workspace": "gh:sase-org/sase"
    },
    {
      "id": "polish",
      "prompt": "Fact-check and polish the documentation update.",
      "workspace": "gh:sase-org/sase",
      "wait_on": "update"
    }
  ]
}
```

Result `status` is `ok`, `no_op`, or `check_error`. Results can also carry a `reason`, integer `counters`, and relative
`evidence` file paths. Each proposal requires `prompt` and `workspace`; optional fields are `id`, `agent_name`, `tribe`,
`model`, `effort`, `env`, `dedupe_key`, and `wait_on` (an earlier proposal index or ID).

The runner validates the full document before launching anything. It injects the workspace reference, a deterministic
agent name and `tribe=chop` in one `%id(...)` directive, model/effort directives, and a `%wait` dependency for
`wait_on`, then launches proposals in document order. Standalone `#!workflow` references are forbidden in proposal
prompts; reusable inline `#xprompt` references remain valid. The runner records every launched agent in
`agent_chops.json` and finalizes the chop only when the linked agents reach terminal state.

A launcher can still fail partway through an otherwise valid batch. When at least one proposal already started, the chop
remains active as `launched` until those agents finish, then finalizes as `action_failed` with both the launch error and
any agent failures. Once-per keys for accepted proposals that never started are released immediately; a started proposal
keeps its key while it runs, then releases it only if that agent fails. Successful work remains de-duplicated. A
key-release error is appended to the chop output and does not replace the original launch or agent outcome.

Python chop packages should use the public `sase.chops` SDK (`load_chop_invocation`, `ChopLogger`, `ChopResultBuilder`,
and `launch_proposal`) for argument parsing, summaries, validation, and atomic result writes.

#### Triggers, Guards, Dedupe, and Targets

Policy is runner-owned and evaluated before the script:

- `run_every` limits cadence for each expanded chop instance.
- `inhibit_if` supports `changespec` and `agent_hood` guards. A matching guard records a visible `skipped` run with its
  reason.
- `trigger` defaults to `always`. `git.commits_since` observes a project repository, fires when its threshold is met,
  and owns its checkpoint under the chop's state directory. A missing checkpoint fires once so a new chop is not
  silently inert.
- Checkpoint policy can be `on_observation`, `on_action_accepted`, or `on_action_success`. The last option advances only
  after every linked proposal agent succeeds.
- `once_per` renders a bounded per-proposal key; a proposal's own `dedupe_key` takes precedence. Duplicate proposals are
  skipped without relaunching work. Accepted keys remain reserved for successful launches, but are released when their
  proposal never starts or its launched agent reaches terminal failure, allowing a later run to retry that work.
- `for_each` accepts literal target rows or `source: projects`. Expansion creates stable instances such as
  `refresh_docs[sase-core]`, each with independent cadence, history, checkpoints, and dedupe state. Target overrides can
  patch per-instance fields such as `run_every` and trigger thresholds.

Manual CLI/TUI runs bypass configured triggers because the operator explicitly requested a run, but still honor guards.
Pass `-f/--force` on the CLI to bypass both for that run.

Once-per filtering keeps proposal chains connected. If a surviving proposal's `wait_on` points to a duplicate, AXE
follows the skipped proposal's own dependency until it reaches the nearest earlier proposal that also survived the
filter. If no such proposal exists, AXE removes the wait. Dry-run and recorded proposal previews put the resulting
dependency in `wait_on` and explain the change in `dedupe_reason`, so removing duplicate work does not also discard a
new downstream proposal.

#### Builtin `refresh_docs`

`sase_chop_refresh_docs` replaces the former scheduled xprompt workflow. It expects an expanded target with a
`workspace`, then emits an `update` proposal and a `polish` proposal whose `wait_on` points to `update`. Commit counting
and checkpoints belong to `git.commits_since`; project fan-out belongs to `for_each`:

```yaml
axe:
  lumberjacks:
    docs:
      interval: 300
      chops:
        refresh_docs:
          script: sase_chop_refresh_docs
          description: Refresh documentation after meaningful repository drift
          run_every: "30m"
          trigger:
            git.commits_since:
              project: "{target.name}"
              threshold: 25
              checkpoint: on_action_success
          for_each:
            source: projects
            vcs: [git, gh]
```

The builtin supplies plain-language update and polish prompts. Override them with non-blank `vars.prompt` and
`vars.polish_prompt` strings. The script only proposes work; it never calls `sase run` or updates marker files.

### Manual Chop Runs

Scheduled lumberjack ticks are not the only way a chop runs. Operators can launch any configured chop on demand from
both the CLI and the ACE TUI; manual runs share the same execution path, run history, and live-output streaming as
scheduled runs.

**From the CLI:**

```bash
sase axe chop run <chop>                       # name must be unique across lumberjacks
sase axe chop run <chop> --lumberjack <lj>     # explicit lumberjack (short form: -L <lj>)
sase axe chop run <chop> --dry-run             # -n: validate and preview; launch nothing
sase axe chop run <chop> --chop-verbose        # -V: script diagnostics + full result
sase axe chop run <chop> --force               # -f: bypass guards (triggers already bypassed)
```

When the same chop name appears under multiple lumberjacks, `sase axe chop run <chop>` fails with an unambiguous error
listing the candidate lumberjacks. Pass `-L/--lumberjack` to pick one. The manual run is recorded under
`~/.sase/axe/lumberjacks/<lumberjack>/chops/<chop>/` exactly like a scheduled run, except its metadata is tagged with
`source = "manual"` (vs `"scheduled"`).

**From the ACE TUI:**

On the Axe tab, press `r` while a chop row is selected to launch that exact `(lumberjack, chop)` manually. The run uses
the chop's configured script, environment, and timeout, but bypasses any `run_every` cadence because the user explicitly
asked for it. The TUI does not block while the script runs; once the subprocess starts, the new run becomes the newest
entry in the chop's run history and the detail panel switches to it.

If the selected chop already has a live script run in flight for the same `(lumberjack, chop)`, `r` notifies and skips
the launch rather than starting an overlapping duplicate. On non-chop rows — lumberjack rows and running bgcmd rows —
`r` is a no-op; on a completed bgcmd row, `r` continues to re-run the bgcmd.

Manual runs participate in `Ctrl+N` / `Ctrl+P` history navigation just like scheduled runs. The chop-detail header marks
them with a `Source: manual` chip so it is easy to tell at a glance why a run started.

### Chop Run History

Every chop execution — whether kicked off by a scheduled lumberjack tick or by `sase axe chop run …` — is recorded as a
separate run under `~/.sase/axe/lumberjacks/<lumberjack>/chops/<chop>/`. Each run is assigned a sortable, microsecond-
precision `run_id`. `index.json` (kept next to `runs/`) lists the chop's run IDs newest-first:

```
~/.sase/axe/lumberjacks/<lumberjack>/chops/<chop>/
├── index.json              # Ordered run IDs (newest first)
└── runs/
    ├── <run_id>.json         # Run metadata (see below)
    ├── <run_id>.log          # Streamed stdout+stderr from the chop process
    ├── <run_id>.context.json # Private context passed to this invocation
    └── <run_id>.result.json  # Structured result, when the script writes one
```

Each `<run_id>.json` is a serialized `ChopRunEntry` (see `src/sase/axe/state.py`). The most relevant fields are
`status`, `started_at`, `finished_at`, `duration_ms`, `exit_code`, `pid`, `source` (`scheduled`, `manual`, or
`oneshot`), `started_by`, `output_bytes`, `result`, proposal previews, launches, and the recorded skip/error `reason`.

A run starts as `running`. Exit-code-only scripts end as `success`, `failure`, `timeout`, or `missing_script`. Policy
rejections are `skipped`; structured healthy no-work and degraded probes are `no_op` and `check_error`. A result with
accepted proposals moves to `launched`, then the housekeeping pass finalizes it as `action_succeeded` or `action_failed`
from linked agent completion artifacts. `running` and `launched` are active states, so `finished_at` is `null` for both.

If a linked agent's process has stopped and its live `done.json` is absent, finalization looks for the top-level
dismissed-agent archive entry with the same artifact timestamp. Workflow-child archive rows do not stand in for that
top-level run. Only a `DONE` archive status counts as success; `FAILED`, `KILLED`, any other status, or a missing entry
fails the action.

History is pruned after every run write, retaining the newest `MAX_CHOP_RUN_HISTORY` (10) terminal runs per chop. Active
`running` and `launched` entries are always kept regardless of position, so slow scripts and pending actions are never
deleted out from under their lifecycle owners.

### AXE Tab Views

The Axe tab sidebar renders each lumberjack as a top-level row with its configured chops as indented children, followed
by any background commands (`!!`). Each chop row shows a status marker derived from its newest cached run: active
`running` / `launched`, successful `success` / `action_succeeded`, healthy `no_op`, policy `skipped`, degraded
`check_error`, failed `failure` / `timeout` / `action_failed`, or `missing_script`. Chops with no history remain marked
as never run. Selection drives three distinct dashboard views:

- **Lumberjack overview** — selecting a lumberjack row shows its status, interval, cycle count, error count, and a
  per-chop table with each chop's last-run status, relative timestamp, and duration. For a chop whose newest run is
  still active, the duration column shows live elapsed runtime rather than the stale `0ms` you would otherwise see
  before the run finalizes.
- **Chop detail** — selecting a chop row renders the latest run's metadata (`● running` status with live elapsed
  runtime, PID, and a `Source:` chip for non-scheduled runs — i.e. `manual` or `oneshot`) and tails the run's `.log`
  file. Until the log has accumulated any bytes, the panel shows a `Waiting for output…` placeholder; the exit code is
  suppressed until the run finalizes.
- **Background command output** — the existing live output stream for the focused `!!` row.

`Ctrl+N` / `Ctrl+P` on the Axe tab page through the focused chop's run history (newer / older). The viewer pins to the
run you selected so that a fresh tick prepending a new run does not bump you forward; the pin is cleared automatically
if the pinned run is pruned or itself becomes the newest run.

### Chop-Agent Registry

The durable `agent_chops.json` linkage and `SASE_CHOP_*` metadata associate launched proposals with chop lifecycle
state. Configuration is always script-based. Each launched agent receives `SASE_CHOP_LUMBERJACK`, `SASE_CHOP_NAME`,
`SASE_CHOP_RUN_ID`, and a prompt hash; the housekeeping pass uses the registry plus normal agent completion artifacts to
finalize `launched` runs.

## Concurrency Management

Axe uses a cross-process runner pool to enforce global concurrency limits. The `SharedRunnerPool` uses `fcntl.flock` on
a shared file (`~/.sase/axe/shared/runner_count`) to coordinate runner slots across all lumberjack processes atomically.

Hook runners and agent runners have separate limits (`max_hook_runners` and `max_agent_runners`), allowing fine-grained
control over background resource usage.

## Agent Completion Artifacts

When an agent run finalizes, axe writes the normal completion metadata and sends the workflow-complete notification.
Successful runs also scan the agent workspace for generated image files (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`),
video files (`.mp4`, `.m4v`, `.mov`, `.webm`), and Markdown files (`.md`, `.markdown`). When 10 or fewer Markdown
sources are discovered after filtering, they are rendered to PDFs under the agent artifact directory, then the generated
PDF paths are appended after the standard chat/diff notification attachments and before image/video attachments. The PDF
list is persisted as `done.json.markdown_pdf_paths`; the image and video lists are persisted as `done.json.image_paths`
and `done.json.video_paths`. Explicit artifacts created during the run with
`sase artifact create -p <path> [-n <label>] [-k <kind>]` are appended after generated media attachments when their
stored files still exist.

The scan uses git name-status output, untracked files, saved diff metadata, and the latest commit when the agent
committed or opened a PR. Deleted, missing, unsupported, and duplicate paths are ignored. If more than 10 Markdown
sources remain, Axe skips Markdown PDF rendering for that completion and adds a note to the notification. PDF rendering
is otherwise best-effort: missing conversion tools or render failures omit that source without failing the agent run.
Generated Markdown PDFs are optimized for narrow viewers with a small portrait page, small margins, and larger type. As
PDFs are prepared, axe updates `workflow_state.json.pdf_status` and a compact `activity` label so ACE can show live
finalization progress such as `PDF 2/4 <path>` or `PDFs done 3/4 (1 skipped)`. Successful runs also copy discovered
media artifacts, plus prompt-referenced images and videos, into persistent SASE artifact storage for ACE.
Prompt-referenced media are not appended to completion notifications unless they were also generated/modified files or
explicit artifacts. See [`agent_images.md`](agent_images.md) for the full contract.

The Agents tab exposes completion artifacts through the `a` action. When artifacts exist, ACE opens the artifact panel
for selection. Chat transcripts, plan files, generated PDFs/images/videos, prompt-referenced media from saved prompt
artifacts, and explicit artifacts created with `sase artifact create -p <path> [-n <label>] [-k <kind>]` all participate
in the same list. Explicit artifacts are stored under `~/.sase/artifacts/` with a persistent association so they remain
available after dismissing and later reviving the agent. ACE shows the picker even for a single artifact. Inside that
picker, `m` marks rows, `Enter` opens the marked set or highlighted row, and `A` opens the full list. Only one plan
artifact is listed for an agent, preferring the committed SDD plan path when one exists. Inside tmux, artifact viewing
opens in a right-side tmux pane, collapses the Agents list while live, uses `l` to focus the pane, and uses lowercase
`a` to close it; outside tmux, ACE suspends and uses the current pane. The viewer supports images, videos, Markdown,
PDFs, and text fallbacks, wraps `j`/`k` page navigation at the ends, uses `n`/`p` for artifact-sequence navigation, and
warns when required terminal/rendering tools are missing. The direct agent run-log binding is `V`.

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
│       ├── chops/                  # Per-chop run history (newest 10 terminal runs per chop)
│       │   └── {chop}/
│       │       ├── index.json      # Ordered run IDs (newest first)
│       │       └── runs/
│       │           ├── {run_id}.json   # ChopRunEntry metadata
│       │           └── {run_id}.log    # Streamed stdout+stderr
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
- Footer shows a segmented `AXE` badge followed by daemon status: RUNNING, STOPPED, STARTING, STOPPING, or RESTARTING

The RESTARTING indicator appears when `sase ace --restart-axe` (`-R`) is used — the daemon restarts in the background
while the TUI starts up normally.

See [`docs/ace.md`](ace.md) for the full Axe tab keybinding reference.

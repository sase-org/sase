---
title: "sase tool"
description: "List, run, and inspect project-owned named tools and the machine-local ToolRun ledger."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase tool

List, run, and inspect project-owned named tools

Reference for `sase tool`. Run `sase tool --help` for the exact output on this checkout.

```text
usage: sase tool [-h]
                 {failures,list,receipt,receipts,run,runs,show,stats,stop,wait}
                 ...
```

List, run, and inspect project-owned named tools and the machine-local ToolRun ledger. Bare `sase tool` defaults to `sase tool list`. Named tools are complete entries in the project's sase/sase.yml. User, machine, plugin, and builtin config cannot change argv. Ad-hoc commands require `sase tool run -- ARGV...`.

Bare `sase tool` defaults to `sase tool list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                                                   |
| -------------------- | --------------------------------------------------------- |
| `sase tool failures` | List grouped failure signatures                           |
| `sase tool list`     | List named tools with LAST and TYPICAL                    |
| `sase tool receipt`  | Show the covering verdict receipt for one named tool      |
| `sase tool receipts` | List receipts and content-equivalent repeat opportunities |
| `sase tool run`      | Run a named tool or an ad-hoc argv                        |
| `sase tool runs`     | List recorded tool runs                                   |
| `sase tool show`     | Show one tool run by exact id                             |
| `sase tool stats`    | Report ToolRun durations, waste, repeats, and pressure    |
| `sase tool stop`     | Stop one tool run by exact id                             |
| `sase tool wait`     | Wait for one tool run to settle                           |

## `sase tool failures`

```text
usage: sase tool failures [-h] [-a] [-c CLASS] [-d N] [-j] [-n N] [-t TOOL]
```

List machine-local failure signature groups from stored triage, newest-agent groups first. Defaults to the current catalog repo's project over the last 7 days. Linked-repo groups never appear under another project's tool. An empty result prints `no recorded failures` and exits 0.

Options:

| Option                      | Description                                                            | Default |
| --------------------------- | ---------------------------------------------------------------------- | ------- |
| `-a`, `--all`               | Include signature groups from every project                            | `false` |
| `-c CLASS`, `--class CLASS` | Filter to one item class (choices: `flaky`, `known`, `new`, `unknown`) | —       |
| `-d N`, `--days N`          | Look back N days (default: 7)                                          | `7`     |
| `-h`, `--help`              | show this help message and exit                                        | —       |
| `-j`, `--json`              | Emit a versioned machine-readable JSON object                          | `false` |
| `-n N`, `--limit N`         | Show at most N groups (default: 50, max: 1000)                         | `50`    |
| `-t TOOL`, `--tool TOOL`    | Filter to one named tool                                               | —       |

## `sase tool list`

```text
usage: sase tool list [-h] [-j]
```

Show each project-owned named tool with its newest native result (LAST) and observed median duration (TYPICAL). Missing samples render as an em dash, never as zero or an ETA.

Options:

| Option         | Description                                   | Default |
| -------------- | --------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit               | —       |
| `-j`, `--json` | Emit a versioned machine-readable JSON object | `false` |

## `sase tool receipt`

```text
usage: sase tool receipt [-h] [-a VERDICT] [-j] TOOL
```

Report the covering verdict receipt for one named tool at the current fingerprint, or a typed refusal. The query states what the ledger holds and never claims any completion policy is met. Exit codes: 0 covered, 1 typed refusal or store failure, 2 unknown tool or usage.

Options:

| Option                           | Description                                                                | Default |
| -------------------------------- | -------------------------------------------------------------------------- | ------- |
| `-a VERDICT`, `--accept VERDICT` | Accept this verdict as covered (default: pass) (choices: `no-new`, `pass`) | `pass`  |
| `-h`, `--help`                   | show this help message and exit                                            | —       |
| `-j`, `--json`                   | Emit a versioned machine-readable JSON object                              | `false` |

Arguments:

| Argument            | Description         |
| ------------------- | ------------------- |
| `tool_receipt_tool` | Named tool to query |

## `sase tool receipts`

```text
usage: sase tool receipts [-h] [-d N] [-j]
```

List retained verdict receipts and report content-equivalent verification repeats: counts, summed duration, top tools, and the observation window. The comparison is content-addressed, so a verified dirty tree later committed at a new HEAD counts as a repeat opportunity. The report never changes what `run` executes and never claims the current tree is covered.

Options:

| Option             | Description                                   | Default |
| ------------------ | --------------------------------------------- | ------- |
| `-d N`, `--days N` | Look back N days (default: 7)                 | `7`     |
| `-h`, `--help`     | show this help message and exit               | —       |
| `-j`, `--json`     | Emit a versioned machine-readable JSON object | `false` |

## `sase tool run`

```text
usage: sase tool run [-h] [-q] [-T N] [-v] [-H | -d] [-k | -x] ...
```

Execute a project-owned named tool, or an ad-hoc command after `--`, and record a ToolRun. Named tools run at the project root; ad-hoc commands use the invocation cwd. Extra arguments append only when the definition allows them. Tokens after `--` are preserved verbatim, including leading dashes. Options must precede TOOL or `--`. Humans default to exact stdout/stderr passthrough. Direct agent execution (SASE_AGENT_NAME) defaults to compact output. `-q` forces compact; `-v` forces streaming. Wrapper metadata goes to stderr. The child has no output TTY; stdin is inherited on the inline path, including the fail-open fallback below. The automatic detached path does not inherit stdin. `-H` hands the run off to a durable proc and returns at once with the run id. With `-H`, `-q` prints only the run id, while `-v` and `-T` are usage errors. `-d` starts a starter-scoped detached run for the calling agent instead (agents only); it stops when the agent's turn ends unless a monitor joins it. An agent's inline run of a catalog tool declared `long` or `unbounded` is refused before starting (exit `2`) when its class floor meets the provider's synchronous ceiling, with the monitor command to use instead. Exit codes: 0 accepted, 1 not started, 2 usage or refusal. An agent call with a sync budget and no live owner or parent run starts a plain `sase tool run` detached and follows it: the run's exit is returned when it lands inside the budget; at the budget the escalation block is printed and the follower exits `124` without stopping the run; SIGTERM, SIGINT, and SIGHUP do the same and exit `143`, `130`, and `129`. If detach cannot start, one warning is printed and the run falls back to inline. Automatic-path exits (`0` settled, `124` budget, `143`/`130`/ `129` signal, `1` follow error) stay distinct from the `-H`/`-d` codes (`0` accepted, `1` not started, `2` usage or refusal).

Options:

| Option                   | Description                                                                        | Default |
| ------------------------ | ---------------------------------------------------------------------------------- | ------- |
| `-d`, `--detach`         | Start a starter-scoped detached run as this agent and return at once (agents only) | `false` |
| `-x`, `--fail-fast`      | Stop at the first failed stage (named run_silent tools only)                       | `false` |
| `-H`, `--hand-off`       | Hand the run off to a durable proc and return at once                              | `false` |
| `-h`, `--help`           | show this help message and exit                                                    | —       |
| `-k`, `--keep-going`     | Continue past failed stages (named run_silent tools only)                          | `false` |
| `-q`, `--quiet`          | Force compact output (identity, result, failure tail)                              | `false` |
| `-T N`, `--tail-lines N` | Retained failure lines shown in compact mode (default: 200)                        | —       |
| `-v`, `--verbose`        | Force streaming passthrough of child stdout and stderr                             | `false` |

Arguments:

| Argument         | Description                                                 |
| ---------------- | ----------------------------------------------------------- |
| `tool_run_words` | Named tool with optional extra args, or -- followed by argv |

## `sase tool runs`

```text
usage: sase tool runs [-h] [-a] [-A AGENT] [-c CURSOR] [-j] [-n N] [-s STATE]
                      [-t TOOL]
```

List native ToolRuns, newest first. Defaults to the current project. Unsettled wrappers whose process is gone are marked lost before the list is rendered.

Options:

| Option                         | Description                                                                                                             | Default |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-A AGENT`, `--agent AGENT`    | Filter to runs attributed to this agent                                                                                 | —       |
| `-a`, `--all`                  | Include runs from every project                                                                                         | `false` |
| `-c CURSOR`, `--cursor CURSOR` | Continue from a previous next_cursor value                                                                              | —       |
| `-h`, `--help`                 | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                 | Emit a versioned machine-readable JSON object                                                                           | `false` |
| `-n N`, `--limit N`            | Show at most N runs (default: 50, max: 1000)                                                                            | `50`    |
| `-s STATE`, `--state STATE`    | Filter to one lifecycle state (choices: `created`, `failed`, `interrupted`, `lost`, `running`, `signaled`, `succeeded`) | —       |
| `-t TOOL`, `--tool TOOL`       | Filter to one named tool                                                                                                | —       |

## `sase tool show`

```text
usage: sase tool show [-h] [-F] [-j | -l] RUN
```

Show one ToolRun by exact run id. `-j` emits the versioned query envelope. `-l` replays retained stdout to stdout and retained stderr to stderr without claiming a total order between streams. `-F` streams the output of record until the run settles, then prints the terminal summary. `-j` and `-l` cannot be combined; `-F` and `-l` cannot be combined; `-F -j` waits, then prints the final JSON envelope. Ctrl-C detaches the viewer (exit 130); the run continues. In an agent with a sync wait budget, `-F` stops at the budget with the escalation block (exit 124); the run continues. Exit codes: 0 shown or followed, 1 store failure, 2 unknown run or usage, 124 budget reached.

Options:

| Option           | Description                                       | Default |
| ---------------- | ------------------------------------------------- | ------- |
| `-F`, `--follow` | Stream the output of record until the run settles | `false` |
| `-h`, `--help`   | show this help message and exit                   | —       |
| `-j`, `--json`   | Emit a versioned machine-readable JSON object     | `false` |
| `-l`, `--logs`   | Replay retained stdout and stderr                 | `false` |

Arguments:

| Argument           | Description       |
| ------------------ | ----------------- |
| `tool_show_run_id` | Exact tool run id |

## `sase tool stats`

```text
usage: sase tool stats [-h] [-a] [-d N] [-j] [-t TOOL]
```

Report read-only ToolRun stats over the machine-local ledger: per tool, stage, route, and provider p50/p90, outcome and censoring mix, ceiling kills and wasted hours, repeats and duplicates, a daily trend, a chronological backtest, and host pressure. The backtest measures the simplest empirical-quantile baseline, not a forecaster. An empty report prints `no recorded runs` and exits 0.

Options:

| Option                   | Description                                   | Default |
| ------------------------ | --------------------------------------------- | ------- |
| `-a`, `--all`            | Include runs from every project               | `false` |
| `-d N`, `--days N`       | Look back N days (default: 7, max: 180)       | `7`     |
| `-h`, `--help`           | show this help message and exit               | —       |
| `-j`, `--json`           | Emit a versioned machine-readable JSON object | `false` |
| `-t TOOL`, `--tool TOOL` | Filter to one named tool                      | —       |

## `sase tool stop`

```text
usage: sase tool stop [-h] [-j] RUN
```

Record a durable stop request for one ToolRun, then stop it through its execution owner: a proc-owned hand-off through the proc stop path, a monitor-owned hand-off through the monitor stop path (the follow-up is suppressed), an inline run by signaling its identity-matched wrapper. A nested foreground run is refused with the owner command that stops it. Reports `stop requested` separately from `stopped`. Exit codes: 0 stop requested, stopped, or already settled; 2 unknown run or refused nested run; 1 owner control failed.

Options:

| Option         | Description                                   | Default |
| -------------- | --------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit               | —       |
| `-j`, `--json` | Emit a versioned machine-readable JSON object | `false` |

Arguments:

| Argument           | Description       |
| ------------------ | ----------------- |
| `tool_stop_run_id` | Exact tool run id |

## `sase tool wait`

```text
usage: sase tool wait [-h] [-j] [-T N] [-t DURATION] RUN
```

Block until one ToolRun settles or the deadline passes. The run is never affected. A settled run with an exit code returns that code; a settled run without one returns 1. A passed deadline returns 124. Ctrl-C returns 130; the run continues. In an agent with a sync wait budget, the deadline is the smaller of `-t` and the budget, and a reached budget prints the escalation block. Exit codes: exit code of the run, 1 settled without an exit code, 124 still running, 2 unknown run or usage, 130 interrupted.

Options:

| Option                              | Description                                              | Default |
| ----------------------------------- | -------------------------------------------------------- | ------- |
| `-h`, `--help`                      | show this help message and exit                          | —       |
| `-j`, `--json`                      | Emit a versioned machine-readable JSON object            | `false` |
| `-T N`, `--tail-lines N`            | Append the last N lines of the output of record          | —       |
| `-t DURATION`, `--timeout DURATION` | Deadline: bare seconds or a duration like 90s / 45m / 2h | —       |

Arguments:

| Argument           | Description       |
| ------------------ | ----------------- |
| `tool_wait_run_id` | Exact tool run id |

Related: [CLI command groups](index.md).

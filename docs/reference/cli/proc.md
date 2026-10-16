---
title: "sase proc"
description: "Inspect and run SASE procs."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase proc

List, inspect, run, and kill durable procs

Aliases: `sase task`.

Reference for `sase proc`. Run `sase proc --help` for the exact output on this checkout.

```text
usage: sase proc [-h] {kill,list,run,show} ...
```

Inspect and run SASE procs. Procs are durable: they survive TUI restarts and are readable from any surface. Session scope is attribution only: unattributed procs are visible from every session. Running `sase proc` defaults to `sase proc list`. `sase task` remains accepted as a legacy alias.

Bare `sase proc` defaults to `sase proc list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand       | Summary                                          |
| ---------------- | ------------------------------------------------ |
| `sase proc kill` | Kill one running proc                            |
| `sase proc list` | List procs (rich table by default, JSON with -j) |
| `sase proc run`  | Run a command as a durable proc                  |
| `sase proc show` | Show one proc and its captured output            |

## `sase proc kill`

```text
usage: sase proc kill [-h] [-j] REF
```

Kill one proc by exact fully qualified named proc, exact id, or unique id prefix (at least three characters). A bare name is derived beneath the calling sase agent. A proc that is already finished is reported as an unchanged no-op.

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON result | `false` |

Arguments:

| Argument  | Description                              |
| --------- | ---------------------------------------- |
| `proc_id` | Named proc, proc id, or unique id prefix |

## `sase proc list`

```text
usage: sase proc list [-h] [-a] [-j] [-n N] [-N NAME] [-p NAME] [-q TEXT] [-r]
                      [-s REF] [-S STATUS] [-t TAG]
```

List durable procs, newest first. By default this shows procs for the current session — the TUI session of this process, else the newest live one — plus procs that belong to no session; pass --all to see every session's work. Filter by named proc with -N/--name; a bare name is derived beneath the calling sase agent, and historical names stay visible. Procs whose supervisor died without reporting are reconciled to `error` before the list is rendered.

Options:

| Option                         | Description                                                                                                                                                                    | Default |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| `-a`, `--all`                  | Include procs from every session (default: this session plus unattributed)                                                                                                     | `false` |
| `-h`, `--help`                 | show this help message and exit                                                                                                                                                | —       |
| `-j`, `--json`                 | Emit a machine-readable JSON envelope (stable schema)                                                                                                                          | `false` |
| `-n N`, `--limit N`            | Show at most N procs (default: the configured procs.history_limit)                                                                                                             | —       |
| `-N NAME`, `--name NAME`       | Only the named proc; a bare name is derived beneath the calling sase agent                                                                                                     | —       |
| `-p NAME`, `--project NAME`    | Only procs attributed to this project                                                                                                                                          | —       |
| `-q TEXT`, `--query TEXT`      | Case-insensitive substring filter over label, command, Patch name, and named proc                                                                                              | —       |
| `-r`, `--running`              | Only procs that are pending, running, or settling                                                                                                                              | `false` |
| `-s REF`, `--session REF`      | Only procs from this session (id, prefix, handle, current, latest, none)                                                                                                       | —       |
| `-S STATUS`, `--status STATUS` | Only procs with this status; repeat to add more (pending, running, settling, success, error, killed) (choices: `error`, `killed`, `pending`, `running`, `settling`, `success`) | —       |
| `-t TAG`, `--tag TAG`          | Only procs carrying this tag                                                                                                                                                   | —       |

## `sase proc run`

```text
usage: sase proc run [-h] [-c DIR] [-j] [-l TEXT] [-N NAME] [-p NAME] [-q]
                     [-s REF] [-t TAG] [-w]
                     ...
```

Record a proc, start it under a supervisor, and return. The supervisor owns the command's process group and captures its combined output, so the proc survives this process and any TUI. Everything after `--` is the command to run. Targeting a session is attribution, not delegation: the proc runs the same way regardless, but the chosen session's Procs tab shows it and counts it.

Options:

| Option                      | Description                                                                                                            | Default |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ------- |
| `-c DIR`, `--cwd DIR`       | Working directory for the command (default: the current directory)                                                     | —       |
| `-h`, `--help`              | show this help message and exit                                                                                        | —       |
| `-j`, `--json`              | Emit the created proc as a JSON envelope                                                                               | `false` |
| `-l TEXT`, `--label TEXT`   | Human-facing proc label (default: derived from the command)                                                            | —       |
| `-N NAME`, `--name NAME`    | named proc; a bare name is derived beneath the calling sase agent, and the name may be reused only after settlement    | —       |
| `-p NAME`, `--project NAME` | Project to attribute the proc to (default: inferred from the cwd)                                                      | —       |
| `-q`, `--quiet`             | Print only the new proc id                                                                                             | `false` |
| `-s REF`, `--session REF`   | Session to attribute the proc to (id, prefix, handle, current, latest, none; default: current, then latest, then none) | —       |
| `-t TAG`, `--tag TAG`       | Tag the proc; repeat to add more tags                                                                                  | —       |
| `-w`, `--wait`              | Stream the proc's output and exit with its exit code                                                                   | `false` |

Arguments:

| Argument       | Description                      |
| -------------- | -------------------------------- |
| `proc_command` | Command to run, introduced by -- |

## `sase proc show`

```text
usage: sase proc show [-h] [-A] [-f {markdown,json}] [-F] [-l N] [-o] REF
```

Show one proc by exact fully qualified named proc, exact id, or unique id prefix (at least three characters), followed by the tail of its captured output. A bare name is derived beneath the calling sase agent. `--follow` streams new output until the proc finishes and returns immediately for a proc that already has; with `--format json` it waits and then emits the finished proc.

Options:

| Option                         | Description                                                                 | Default    |
| ------------------------------ | --------------------------------------------------------------------------- | ---------- |
| `-A`, `--all-lines`            | Print the whole retained log instead of a tail                              | `false`    |
| `-F`, `--follow`               | Stream new output until the proc reaches a terminal state                   | `false`    |
| `-f FORMAT`, `--format FORMAT` | Output format: 'markdown' (default) or 'json' (choices: `json`, `markdown`) | `markdown` |
| `-h`, `--help`                 | show this help message and exit                                             | —          |
| `-l N`, `--log-lines N`        | Log lines to show (default: 200)                                            | `200`      |
| `-o`, `--output-only`          | Print only the captured log, with no surrounding detail                     | `false`    |

Arguments:

| Argument  | Description                              |
| --------- | ---------------------------------------- |
| `proc_id` | Named proc, proc id, or unique id prefix |

Related: [CLI command groups](index.md).

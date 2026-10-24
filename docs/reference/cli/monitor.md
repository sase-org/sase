---
title: "sase monitor"
description: "Hand a slow command off to a detached supervisor that runs as a real agent session member, with streaming output, a timeout, and an optional follow-up agent."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase monitor

Start, stop, list, and inspect monitored long-running commands

Reference for `sase monitor`. Run `sase monitor --help` for the exact output on this checkout.

```text
usage: sase monitor [-h] {list,resume,show,start,stop} ...
```

Hand a slow command off to a detached supervisor that runs as a real agent session member, with streaming output, a timeout, and an optional follow-up agent. Running `sase monitor` defaults to `sase monitor list`.

Bare `sase monitor` defaults to `sase monitor list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand            | Summary                                                              |
| --------------------- | -------------------------------------------------------------------- |
| `sase monitor list`   | List monitors (rich table by default, -j/--json for JSON)            |
| `sase monitor resume` | Resume a terminal monitor's requested follow-up without rerunning it |
| `sase monitor show`   | Show one monitor and its captured output                             |
| `sase monitor start`  | Start a command as a monitor agent session member                    |
| `sase monitor stop`   | Stop a running monitor                                               |

## `sase monitor list`

```text
usage: sase monitor list [-h] [-a] [-f {table,markdown,json}] [-j] [-l NAME]
                         [-n N] [-p NAME] [-s STATE]
```

List monitor agent session members, newest first. By default this shows only active (running) monitors; pass --all to include finished ones too. Note: here -a is --all; unlike `monitor start`, use -l/--agent to filter by agent.

Options:

| Option                         | Description                                                                                                                                                                    | Default |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| `-l NAME`, `--agent NAME`      | Only monitors belonging to this agent                                                                                                                                          | —       |
| `-a`, `--all`                  | Include finished monitors, not just running ones                                                                                                                               | `false` |
| `-f FORMAT`, `--format FORMAT` | Output format: 'table' (default), 'markdown', or 'json' (choices: `json`, `markdown`, `table`)                                                                                 | `table` |
| `-h`, `--help`                 | show this help message and exit                                                                                                                                                | —       |
| `-j`, `--json`                 | Emit a machine-readable JSON envelope (shorthand for --format json)                                                                                                            | `false` |
| `-n N`, `--limit N`            | Show at most N monitors                                                                                                                                                        | —       |
| `-p NAME`, `--project NAME`    | Only monitors from this project (default: every project)                                                                                                                       | —       |
| `-s STATE`, `--status STATE`   | Only monitors in this state; repeat to add more (running, completed, failed, timeout, stopped, lost) (choices: `completed`, `failed`, `lost`, `running`, `stopped`, `timeout`) | —       |

## `sase monitor resume`

```text
usage: sase monitor resume [-h] ID [-j] [-k FILE] [-m MODEL]
```

Resume the ordinary follow-up requested by a terminal monitor. This reconciles existing continuation delivery state first, then launches only from the frozen monitor result; it never reruns the monitored command.

Options:

| Option                         | Description                                                                                            | Default |
| ------------------------------ | ------------------------------------------------------------------------------------------------------ | ------- |
| `-k FILE`, `--checkpoint FILE` | Optional authored checkpoint YAML/JSON for a manual recovery branch. Bound by content digest, not path | —       |
| `-h`, `--help`                 | show this help message and exit                                                                        | —       |
| `-j`, `--json`                 | Emit a machine-readable JSON result                                                                    | `false` |
| `-m MODEL`, `--model MODEL`    | Model or alias for the resumed follow-up branch                                                        | —       |

Arguments:

| Argument     | Description                                                            |
| ------------ | ---------------------------------------------------------------------- |
| `monitor_id` | Monitor id (or unique prefix), member agent name, or owning agent name |

## `sase monitor show`

```text
usage: sase monitor show [-h] ID [-A] [-b N] [-d] [-f {markdown,json}] [-F]
                         [-l N] [-o] [-R START:END]
```

Show one monitor by id (or unique id prefix), member agent name, or owning agent name, followed by the tail of its captured output. `--follow` streams new output until the monitor reaches a terminal state, exactly like `sase proc show --follow`.

Options:

| Option                              | Description                                                                 | Default    |
| ----------------------------------- | --------------------------------------------------------------------------- | ---------- |
| `-A`, `--all-lines`                 | Print the whole retained output instead of a tail                           | `false`    |
| `-d`, `--diagnostics`               | Print bounded failed-stage diagnostics instead of raw output                | `false`    |
| `-F`, `--follow`                    | Stream new output until the monitor reaches a terminal state                | `false`    |
| `-f FORMAT`, `--format FORMAT`      | Output format: 'markdown' (default) or 'json' (choices: `json`, `markdown`) | `markdown` |
| `-h`, `--help`                      | show this help message and exit                                             | —          |
| `-l N`, `--log-lines N`             | Output lines to show (default: 200)                                         | `200`      |
| `-b N`, `--max-bytes N`             | Maximum bytes for --diagnostics or --range output (default: 65536)          | `65536`    |
| `-o`, `--output-only`               | Print only the captured output, with no surrounding detail                  | `false`    |
| `-R START:END`, `--range START:END` | Print a bounded retained raw-output byte range                              | —          |

Arguments:

| Argument     | Description                                                            |
| ------------ | ---------------------------------------------------------------------- |
| `monitor_id` | Monitor id (or unique prefix), member agent name, or owning agent name |

## `sase monitor start`

```text
usage: sase monitor start [-h] [-a NAME] [-f REF] [-C DIR] [-i DURATION]
                          [-J RUN] [-j] [-k FILE] [-L TEXT] [-m MODEL]
                          [-n TEXT] [-o MODE] [-P FILE] [-p NAME] [-r TEXT]
                          [-s TEXT] [-S TEXT] [-T N] [-t DURATION] [-w W] ...
```

Start a command under a detached supervisor and return. The supervisor owns the command's process group and streams its combined output, so the command outlives this process. When run inside an agent, this is the last output the agent produces before it is killed — the runner adopts the handoff and the monitor keeps running in the same agent and workspace.

Options:

| Option                                   | Description                                                                                                                                                                                                                                                                                                                                              | Default |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a NAME`, `--agent NAME`                | Target agent (default: the calling agent). Note: unlike `monitor list`, here -a is --agent, not --all                                                                                                                                                                                                                                                    | —       |
| `-k FILE`, `--checkpoint FILE`           | Optional authored checkpoint YAML/JSON with objective, constraints, findings, unresolved decisions, remaining work, source refs, and coverage. Bound by content digest, not path                                                                                                                                                                         | —       |
| `-f REF`, `--completion REF`             | Prepared host-completion intent reference from `sase final prepare`. Binding is atomic and single-use                                                                                                                                                                                                                                                    | —       |
| `-C DIR`, `--cwd DIR`                    | Working directory (default: the current directory when it is inside a repo opened with `sase repo open`, else the agent's workspace, else $PWD)                                                                                                                                                                                                          | —       |
| `-h`, `--help`                           | show this help message and exit                                                                                                                                                                                                                                                                                                                          | —       |
| `-i DURATION`, `--idle-timeout DURATION` | Optional no-output timeout; kills commands that stop producing bytes for this long, while quiet commands remain supported when omitted                                                                                                                                                                                                                   | —       |
| `-J RUN`, `--join RUN`                   | Join a starter-scoped detached ToolRun instead of starting a command; cannot be used with a command, -c, -f, or -a                                                                                                                                                                                                                                       | —       |
| `-j`, `--json`                           | Emit the started monitor as a JSON envelope                                                                                                                                                                                                                                                                                                              | `false` |
| `-L TEXT`, `--label TEXT`                | Short row label (default: derived from the command)                                                                                                                                                                                                                                                                                                      | —       |
| `-m MODEL`, `--model MODEL`              | Model or alias for the follow-up agent (opus, opus@high, sonnet, codex/gpt-5). Requires -n/--next. Default: inherit the starter's model                                                                                                                                                                                                                  | —       |
| `-n TEXT`, `--next TEXT`                 | Next action for the follow-up agent; omit for no follow-up                                                                                                                                                                                                                                                                                               | —       |
| `-o MODE`, `--next-output MODE`          | How much retained output to hand the follow-up agent: 'auto' (default) selects outcome-aware evidence, 'tail' embeds the last --tail-lines lines fenced as untrusted data, 'file' points at refs and log locators instead, 'none' gives only the outcome summary and a `sase monitor show --all-lines` pointer (choices: `auto`, `file`, `none`, `tail`) | —       |
| `-P FILE`, `--policy FILE`               | Outcome-policy file. Mutually exclusive with -p/--profile                                                                                                                                                                                                                                                                                                | —       |
| `-p NAME`, `--profile NAME`              | Named outcome profile (verify). Profile selection alone never authorizes host completion (choices: `verify`)                                                                                                                                                                                                                                             | —       |
| `-r TEXT`, `--reason TEXT`               | Why this command is being monitored (default: 'run command')                                                                                                                                                                                                                                                                                             | —       |
| `-s TEXT`, `--start-status TEXT`         | Label shown while the command runs (present tense, e.g. TESTING). Required unless -p/--profile supplies it. Pair with -S/--stop-status. Max 20 characters                                                                                                                                                                                                | —       |
| `-S TEXT`, `--stop-status TEXT`          | Label shown when the command finishes (past tense, e.g. TESTED). Required unless -p/--profile supplies it. Pair with -s/--start-status. Max 20 characters                                                                                                                                                                                                | —       |
| `-T N`, `--tail-lines N`                 | Output tail handed to the follow-up (default: 200)                                                                                                                                                                                                                                                                                                       | —       |
| `-t DURATION`, `--timeout DURATION`      | Timeout: bare seconds or a duration like 90s / 45m / 2h (default: 1h)                                                                                                                                                                                                                                                                                    | —       |
| `-w W`, `--weight W`                     | Queue weight for this monitor while it runs. Only 0 is accepted: a pure wait (sleep, CI watch, external poll) then holds no runner capacity, and the -n/--next follow-up queues again at your normal weight. Cannot be combined with -p verify, -f/--completion, -J/--join, or a `sase tool run` command                                                 | —       |

Arguments:

| Argument                | Description                                      |
| ----------------------- | ------------------------------------------------ |
| `monitor_command_words` | The command to run and monitor, introduced by -- |

## `sase monitor stop`

```text
usage: sase monitor stop [-h] [ID] [-j] [-Q PATH] [-R PATH]
```

Stop a running monitor by id (or unique id prefix), member agent name, or owning agent name; omitted, targets the calling agent's active monitor. No follow-up agent is launched, even when a next action was recorded.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                   | Emit a machine-readable JSON result                                                                                     | `false` |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument     | Description                                                            |
| ------------ | ---------------------------------------------------------------------- |
| `monitor_id` | Monitor id (or unique prefix), member agent name, or owning agent name |

Related: [CLI command groups](index.md).

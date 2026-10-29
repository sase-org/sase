---
title: "sase gate"
description: "Create durable command-backed gates from versioned JSON specifications, inspect what they ask for, run their repeatable actions, answer them headlessly, and…"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase gate

Create or wait for durable command-backed gates

Reference for `sase gate`. Run `sase gate --help` for the exact output on this checkout.

```text
usage: sase gate [-h] {act,answer,cancel,create,list,show,wait} ...
```

Create durable command-backed gates from versioned JSON specifications, inspect what they ask for, run their repeatable actions, answer them headlessly, and wait mechanically for their terminal results.

Bare `sase gate` defaults to `sase gate list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand         | Summary                                                        |
| ------------------ | -------------------------------------------------------------- |
| `sase gate act`    | Run one repeatable gate action without answering the gate      |
| `sase gate answer` | Answer a durable gate headlessly with typed input              |
| `sase gate cancel` | Cancel one pending gate or gate turn                           |
| `sase gate create` | Create a durable gate from a JSON specification on stdin       |
| `sase gate list`   | List gate turns (rich table by default, -j/--json for JSON)    |
| `sase gate show`   | Print the branches, declared inputs, and actions of a gate     |
| `sase gate wait`   | Wait mechanically for a durable gate to reach a terminal state |

## `sase gate act`

```text
usage: sase gate act [-h] -i REQUEST_ID [-I JSON] [-j] -k KIND -o ACTION_ID
                     [-Q PATH] [-R PATH]
```

Run one action a gate declares. An action never answers the gate and may be run as many times as needed: a `run_command` action prints its output, and an `edit_file` action opens its edit target in $VISUAL/$EDITOR and reports whether the edit was accepted. This is the supported alternative to running a bundle's command by hand.

Options:

| Option                                  | Description                                                                                                             | Default |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                          | show this help message and exit                                                                                         | —       |
| `-i REQUEST_ID`, `--id REQUEST_ID`      | Gate request id from the creation descriptor (required)                                                                 | —       |
| `-I JSON`, `--input JSON`               | JSON input for a run_command action, as a literal, @FILE, or - for stdin                                                | —       |
| `-j`, `--json`                          | Emit the action result as stable machine-readable JSON                                                                  | `false` |
| `-k KIND`, `--kind KIND`                | Gate kind from the creation descriptor (required)                                                                       | —       |
| `-o ACTION_ID`, `--operation ACTION_ID` | Id of the declared action to run; see `sase gate show` (required)                                                       | —       |
| `-Q PATH`, `--request-path PATH`        | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`         | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

## `sase gate answer`

```text
usage: sase gate answer [-h] [-d | -D] [-f FEEDBACK] -i REQUEST_ID [-I JSON]
                        [-j] -k KIND [-o OPTION_ID] [-O OPTION_ID=JSON]
                        [-Q PATH] [-R | -r] [-s FIELD=VALUE]
```

Answer a gate by selecting one branch's options and supplying each selected option's declared input. Input is delivered to commands as JSON on stdin and never as command arguments. Per-option values (--set, --option-input) and one shared value (--input) are mutually exclusive submission contracts.

Options:

| Option                                               | Description                                                                                                                                         | Default |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-d`, `--detach`                                     | Submit to a supervised background proc instead of answering inline, so an approved command survives this client exiting; gate turns default to this | `false` |
| `-f FEEDBACK`, `--feedback FEEDBACK`                 | Reviewer note; delivered as input.feedback to every selected option whose schema declares it                                                        | —       |
| `-h`, `--help`                                       | show this help message and exit                                                                                                                     | —       |
| `-i REQUEST_ID`, `--id REQUEST_ID`                   | Gate request id from the creation descriptor (required)                                                                                             | —       |
| `-I JSON`, `--input JSON`                            | One shared JSON value for every selected option, as a literal, @FILE, or - for stdin (legacy contract)                                              | —       |
| `-j`, `--json`                                       | Emit the stable machine-readable answered result                                                                                                    | `false` |
| `-k KIND`, `--kind KIND`                             | Gate kind from the creation descriptor (required)                                                                                                   | —       |
| `-D`, `--no-detach`                                  | Answer inline even for a gate turn, overriding its detached default                                                                                 | `false` |
| `-o OPTION_ID`, `--option OPTION_ID`                 | Select one option of a single branch; repeat for an AND branch                                                                                      | —       |
| `-O OPTION_ID=JSON`, `--option-input OPTION_ID=JSON` | Whole JSON input value for one selected option, as a literal, @FILE, or - for stdin; repeat per option                                              | —       |
| `-Q PATH`, `--request-path PATH`                     | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set.                             | —       |
| `-R`, `--restart`                                    | Run the whole branch again after a partially executed attempt                                                                                       | `false` |
| `-r`, `--resume`                                     | Continue a partially executed option branch, or resume an already-answered turn whose requested follow-up never launched                            | `false` |
| `-s FIELD=VALUE`, `--set FIELD=VALUE`                | Set one declared input field, typed by its declaration, on every selected option that accepts it; repeat for more fields                            | —       |

## `sase gate cancel`

```text
usage: sase gate cancel [-h] [ID] [-i REQUEST_ID] [-j] [-k KIND] [-r TEXT]
```

Cancel a pending gate by kind/request id, or cancel a pending gate turn by id (or unique id prefix), member agent name, or owning agent name. No follow-up agent is launched, even when one was recorded, unless the gate had already been answered concurrently -- that settles as answered instead.

Options:

| Option                             | Description                                                         | Default |
| ---------------------------------- | ------------------------------------------------------------------- | ------- |
| `-h`, `--help`                     | show this help message and exit                                     | —       |
| `-i REQUEST_ID`, `--id REQUEST_ID` | Gate request id from the creation descriptor                        | —       |
| `-j`, `--json`                     | Emit a machine-readable JSON result                                 | `false` |
| `-k KIND`, `--kind KIND`           | Gate kind from the creation descriptor                              | —       |
| `-r TEXT`, `--reason TEXT`         | Reason recorded on the cancellation (default: a generic CLI reason) | —       |

Arguments:

| Argument   | Description                                                              |
| ---------- | ------------------------------------------------------------------------ |
| `gate_ref` | Gate-turn id (or unique prefix), member agent name, or owning agent name |

## `sase gate create`

```text
usage: sase gate create [-h] [-n NEXT] [-f {session,turn,none}]
                        [-m NEXT_MODEL] [-N {none,results,tail,file}]
                        [-o ORIGIN_AGENT] [-p PANEL] [-P PANEL_ICON]
                        [-s SENDER] [-t TAG] [-G] [-g TURN_STATUS]
                        [-E TURN_STOP_STATUS]
```

Read a schema-versioned gate specification from stdin, create its verified action bundle and notification, then emit a stable JSON descriptor containing the gate kind and request id.

Options:

| Option                                                       | Description                                                                                                   | Default |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                               | show this help message and exit                                                                               | —       |
| `-n NEXT`, `--next NEXT`                                     | Follow-up prompt for a created gate turn                                                                      | —       |
| `-f {session,turn,none}`, `--next-fork {session,turn,none}`  | Gate-turn follow-up fork policy (choices: `none`, `session`, `turn`)                                          | —       |
| `-m NEXT_MODEL`, `--next-model NEXT_MODEL`                   | Model selector inherited by the gate-turn follow-up                                                           | —       |
| `-N NEXT_OUTPUT`, `--next-output NEXT_OUTPUT`                | Gate-turn follow-up output channel; repeat for multiple channels (choices: `file`, `none`, `results`, `tail`) | —       |
| `-o ORIGIN_AGENT`, `--origin-agent ORIGIN_AGENT`             | Attribute the gate to the agent it was filed on behalf of                                                     | —       |
| `-p PANEL`, `--panel PANEL`                                  | Place the gate's notification in a named notification panel tab                                               | —       |
| `-P PANEL_ICON`, `--panel-icon PANEL_ICON`                   | Emoji or glyph identifying that panel tab; required whenever a panel is declared                              | —       |
| `-s SENDER`, `--sender SENDER`                               | Override the notification sender in the gate presentation                                                     | —       |
| `-t TAG`, `--tag TAG`                                        | Add a notification tag to the gate presentation; repeat to add more                                           | —       |
| `-G`, `--turn`                                               | Create a gate turn that owns the decision and hands off this agent                                            | `false` |
| `-g TURN_STATUS`, `--turn-status TURN_STATUS`                | Pending status label for the created gate turn                                                                | —       |
| `-E TURN_STOP_STATUS`, `--turn-stop-status TURN_STOP_STATUS` | Settled status label for the created gate turn                                                                | —       |

## `sase gate list`

```text
usage: sase gate list [-h] [-a] [-f {table,markdown,json}] [-j] [-l NAME]
                      [-n N] [-p NAME] [-s STATE]
```

List gate-turn agent session members, newest first, mirroring `sase monitor list`. By default this shows only pending gate turns, including any still holding a workspace claim; pass --all to include settled ones too.

Options:

| Option                         | Description                                                                                                                                                                                                                  | Default |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-l NAME`, `--agent NAME`      | Only gate turns belonging to this agent                                                                                                                                                                                      | —       |
| `-a`, `--all`                  | Include settled gate turns, not just pending ones                                                                                                                                                                            | `false` |
| `-f FORMAT`, `--format FORMAT` | Output format: 'table' (default), 'markdown', or 'json' (choices: `json`, `markdown`, `table`)                                                                                                                               | `table` |
| `-h`, `--help`                 | show this help message and exit                                                                                                                                                                                              | —       |
| `-j`, `--json`                 | Emit a machine-readable JSON envelope (shorthand for --format json)                                                                                                                                                          | `false` |
| `-n N`, `--limit N`            | Show at most N gate turns                                                                                                                                                                                                    | —       |
| `-p NAME`, `--project NAME`    | Only gate turns from this project (default: every project)                                                                                                                                                                   | —       |
| `-s STATE`, `--state STATE`    | Only gate turns in this state; repeat to add more (pending, settling, answered, completed, failed, timeout, stopped, lost) (choices: `answered`, `completed`, `failed`, `lost`, `pending`, `settling`, `stopped`, `timeout`) | —       |

## `sase gate show`

```text
usage: sase gate show [-h] [ID] [-i REQUEST_ID] [-j] [-k KIND]
```

Print what a gate asks for: its branches, each option's declared input fields with their types, defaults, and choices, and every repeatable action it declares. A gate turn also prints its runtime state, workspace claim, and follow-up disposition. Use it to check that a gate you authored asks for what you intended.

Options:

| Option                             | Description                                      | Default |
| ---------------------------------- | ------------------------------------------------ | ------- |
| `-h`, `--help`                     | show this help message and exit                  | —       |
| `-i REQUEST_ID`, `--id REQUEST_ID` | Gate request id from the creation descriptor     | —       |
| `-j`, `--json`                     | Emit the stable machine-readable gate projection | `false` |
| `-k KIND`, `--kind KIND`           | Gate kind from the creation descriptor           | —       |

Arguments:

| Argument   | Description                                                                                                                                       |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gate_ref` | Gate-turn id (or unique prefix), member agent name, or owning agent name; an alternative to -i/--id plus -k/--kind for a gate created with --turn |

## `sase gate wait`

```text
usage: sase gate wait [-h] -i REQUEST_ID [-j] -k KIND [-t SECONDS]
```

Wait for a durable gate identified by the kind and request id emitted by `sase gate create`. The gate's configured timeout always applies; --timeout may impose an earlier caller deadline.

Options:

| Option                             | Description                                                              | Default |
| ---------------------------------- | ------------------------------------------------------------------------ | ------- |
| `-h`, `--help`                     | show this help message and exit                                          | —       |
| `-i REQUEST_ID`, `--id REQUEST_ID` | Gate request id from the creation descriptor (required)                  | —       |
| `-j`, `--json`                     | Emit the stable machine-readable terminal result                         | `false` |
| `-k KIND`, `--kind KIND`           | Gate kind from the creation descriptor (required)                        | —       |
| `-t SECONDS`, `--timeout SECONDS`  | Stop waiting after this many seconds, without extending the gate timeout | —       |

Related: [CLI command groups](index.md).

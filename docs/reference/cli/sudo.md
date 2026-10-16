---
title: "sase sudo"
description: "Create typed sudo request gates and answer them from a controlling terminal through the dedicated sudo runner."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase sudo

Request, inspect, and answer typed sudo gates

Reference for `sase sudo`. Run `sase sudo --help` for the exact output on this checkout.

```text
usage: sase sudo [-h] {answer,exec,finalize,list,request,show} ...
```

Create typed sudo request gates and answer them from a controlling terminal through the dedicated sudo runner.

Bare `sase sudo` defaults to `sase sudo list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand          | Summary                                          |
| ------------------- | ------------------------------------------------ |
| `sase sudo answer`  | Approve or deny one sudo gate                    |
| `sase sudo list`    | List sudo gate turns                             |
| `sase sudo request` | Create a sudo gate from one JSON object on stdin |
| `sase sudo show`    | Show a sudo gate                                 |

## `sase sudo answer`

```text
usage: sase sudo answer [-h] [-a] [-c ID] [-d] [-D] [-f FEEDBACK] [-j] [-N]
                        [-R | -r] [-u]
                        ID
```

Options:

| Option                               | Description                                                                                                                                                           | Default |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a`, `--approve`                    | Approve and run                                                                                                                                                       | `false` |
| `-c ID`, `--command ID`              | Reviewed command id to run; repeat to select a subset                                                                                                                 | —       |
| `-d`, `--deny`                       | Deny                                                                                                                                                                  | `false` |
| `-D`, `--detach`                     | Authenticate on this TTY, then run the reviewed commands in a supervised background proc; the gate stays pending until that proc finishes (the default for approvals) | `false` |
| `-f FEEDBACK`, `--feedback FEEDBACK` | Reviewer note                                                                                                                                                         | —       |
| `-h`, `--help`                       | show this help message and exit                                                                                                                                       | —       |
| `-j`, `--json`                       | Emit JSON                                                                                                                                                             | `false` |
| `-N`, `--no-detach`                  | Authenticate and run in the foreground                                                                                                                                | `false` |
| `-R`, `--restart`                    | Restart a partial attempt                                                                                                                                             | `false` |
| `-r`, `--resume`                     | Resume a partial attempt                                                                                                                                              | `false` |
| `-u`, `--run`                        | Authenticate and run                                                                                                                                                  | `false` |

Arguments:

| Argument   | Description               |
| ---------- | ------------------------- |
| `gate_ref` | Sudo gate id or shell ref |

## `sase sudo list`

```text
usage: sase sudo list [-h] [-a] [-j] [-l LIMIT] [-p PROJECT]
```

Options:

| Option                            | Description                     | Default |
| --------------------------------- | ------------------------------- | ------- |
| `-a`, `--all`                     | Include settled gates           | `false` |
| `-h`, `--help`                    | show this help message and exit | —       |
| `-j`, `--json`                    | Emit JSON                       | `false` |
| `-l LIMIT`, `--limit LIMIT`       | Limit rows                      | —       |
| `-p PROJECT`, `--project PROJECT` | Filter by project               | —       |

## `sase sudo request`

```text
usage: sase sudo request [-h] [-j] [-o ORIGIN_AGENT]
```

Options:

| Option                                           | Description                     | Default |
| ------------------------------------------------ | ------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit | —       |
| `-j`, `--json`                                   | Emit JSON                       | `false` |
| `-o ORIGIN_AGENT`, `--origin-agent ORIGIN_AGENT` | Attribute the request           | —       |

## `sase sudo show`

```text
usage: sase sudo show [-h] [-j] ID
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit JSON                       | `false` |

Arguments:

| Argument   | Description               |
| ---------- | ------------------------- |
| `gate_ref` | Sudo gate id or shell ref |

Related: [CLI command groups](index.md).

---
title: "sase launch"
description: "Resolve pending launch approval requests created before detached agents are spawned."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase launch

Resolve pending LaunchApproval requests

Reference for `sase launch`. Run `sase launch --help` for the exact output on this checkout.

```text
usage: sase launch [-h] {approve,reject,request} ...
```

Resolve pending launch approval requests created before detached agents are spawned.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand            | Summary                                  |
| --------------------- | ---------------------------------------- |
| `sase launch approve` | Approve a pending launch request         |
| `sase launch reject`  | Reject a pending launch request          |
| `sase launch request` | Create a pending launch approval request |

## `sase launch approve`

```text
usage: sase launch approve [-h] selector [-Q PATH] [-R PATH]
```

Approve a pending launch request by request id or notification prefix.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument   | Description                                                       |
| ---------- | ----------------------------------------------------------------- |
| `selector` | Launch request id, notification id, or unique notification prefix |

## `sase launch reject`

```text
usage: sase launch reject [-h] selector [-f FEEDBACK] [-Q PATH] [-R PATH]
```

Reject a pending launch request by request id or notification prefix.

Options:

| Option                               | Description                                                                                                             | Default |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-f FEEDBACK`, `--feedback FEEDBACK` | Optional feedback to return with the launch rejection                                                                   | —       |
| `-h`, `--help`                       | show this help message and exit                                                                                         | —       |
| `-Q PATH`, `--request-path PATH`     | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`      | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument   | Description                                                       |
| ---------- | ----------------------------------------------------------------- |
| `selector` | Launch request id, notification id, or unique notification prefix |

## `sase launch request`

```text
usage: sase launch request [-h] [payload] [-a APPROVAL] [-f PAYLOAD_FILE]
                           [-m MAX_SLOTS] [-o {text,json}] [-p PROMPT]
                           [-r REASON] [-s SOURCE]
```

Create a LaunchApproval request from a structured JSON payload or prompt flags. Agent-side callers wait for the response; no agent is spawned unless host dispatch is approved and succeeds.

Options:

| Option                                   | Description                                                | Default    |
| ---------------------------------------- | ---------------------------------------------------------- | ---------- |
| `-a APPROVAL`, `--approval APPROVAL`     | Approval policy to request (currently: required).          | `required` |
| `-f PAYLOAD_FILE`, `--file PAYLOAD_FILE` | Read the structured launch request JSON from PATH.         | —          |
| `-h`, `--help`                           | show this help message and exit                            | —          |
| `-m MAX_SLOTS`, `--max-slots MAX_SLOTS`  | Maximum number of launch slots this request may expand to. | `1`        |
| `-o OUTPUT`, `--output OUTPUT`           | Output format. (choices: `json`, `text`)                   | `text`     |
| `-p PROMPT`, `--prompt PROMPT`           | Prompt to request when not passing a JSON payload.         | —          |
| `-r REASON`, `--reason REASON`           | Short reason shown to the approver.                        | —          |
| `-s SOURCE`, `--source SOURCE`           | Source surface label for the launch preview.               | —          |

Arguments:

| Argument  | Description                                             |
| --------- | ------------------------------------------------------- |
| `payload` | Inline JSON payload, or @PATH to read JSON from a file. |

Related: [CLI command groups](index.md).

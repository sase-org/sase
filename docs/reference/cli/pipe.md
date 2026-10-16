---
title: "sase pipe"
description: "End this agent's turn and continue the run as the next agent session member in the same workspace, with the prompt you write."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase pipe

Hand this agent's turn to the next agent session member and end this turn

Reference for `sase pipe`. Run `sase pipe --help` for the exact output on this checkout.

```text
usage: sase pipe [-h] [-f] [-j] [-m MODEL] [-n TOKEN] [-r TEXT] PROMPT
```

End this agent's turn and continue the run as the next agent session member in the same workspace, with the prompt you write. This is not a launch, a monitor, or fan-out: one successor, serially, in the same process. This command kills the calling agent; say everything the successor needs inside PROMPT.

Options:

| Option                      | Description                                                                                                  | Default |
| --------------------------- | ------------------------------------------------------------------------------------------------------------ | ------- |
| `-f`, `--fresh`             | Successor starts with a clean context window (default: prefix #fork:<this agent> so it inherits this chat)   | `false` |
| `-h`, `--help`              | show this help message and exit                                                                              | —       |
| `-j`, `--json`              | Print a machine-readable hand-off summary instead of the rich one                                            | `false` |
| `-m MODEL`, `--model MODEL` | Model or alias for the successor (opus, opus@high, sonnet, codex/gpt-5). Default: inherit this agent's model | —       |
| `-n TOKEN`, `--name TOKEN`  | Successor role token: review yields <session>--review. Default: the next free numbered member (--@)          | —       |
| `-r TEXT`, `--reason TEXT`  | One-line reason, recorded on the successor and shown in agent lists                                          | —       |

Arguments:

| Argument | Description                                                    |
| -------- | -------------------------------------------------------------- |
| `prompt` | Full successor prompt; % directives and # references stay live |

Related: [CLI command groups](index.md).

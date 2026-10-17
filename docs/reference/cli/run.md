---
title: "sase run"
description: "Launch a detached background coding-agent run from a prompt, macro, or workflow."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase run

Launch a detached background agent from a prompt or workflow

Reference for `sase run`. Run `sase run --help` for the exact output on this checkout.

```text
usage: sase run [-h] [PROMPT] [-Q PATH] [-R PATH]
```

Launch a detached background coding-agent run from a prompt, macro, or workflow. Runs use the same launch machinery as sase's TUI and appear in the Agents tab there.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description                                                             |
| -------- | ----------------------------------------------------------------------- |
| `prompt` | Prompt, macro reference, workflow reference, or '.' for prompt history. |

Related: [CLI command groups](index.md).

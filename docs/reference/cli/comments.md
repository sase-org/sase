---
title: "sase comments"
description: "Preview mentor comments from JSON (reads from stdin or file)"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase comments

Preview mentor comments from JSON (reads from stdin or file)

Reference for `sase comments`. Run `sase comments --help` for the exact output on this checkout.

```text
usage: sase comments [-h] [file] [-c CONTEXT]
```

Options:

| Option                            | Description                                                    | Default |
| --------------------------------- | -------------------------------------------------------------- | ------- |
| `-c CONTEXT`, `--context CONTEXT` | Lines of code context above/below the target line (default: 5) | `5`     |
| `-h`, `--help`                    | show this help message and exit                                | —       |

Arguments:

| Argument | Description                                                      |
| -------- | ---------------------------------------------------------------- |
| `file`   | Path to JSON file containing comments (default: read from stdin) |

Related: [CLI command groups](index.md).

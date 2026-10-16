---
title: "sase revive-log"
description: "Show recent agent revive attempts from the audit log"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase revive-log

Show recent agent revive attempts from the audit log

Reference for `sase revive-log`. Run `sase revive-log --help` for the exact output on this checkout.

```text
usage: sase revive-log [-h] [--all] [--limit LIMIT] [--since SINCE]
                       [--outcome {success,failure}] [--json | --jsonl]
```

Options:

| Option              | Description                                                        | Default |
| ------------------- | ------------------------------------------------------------------ | ------- |
| `--all`             | Show every record in events.jsonl (default: most recent 20)        | `false` |
| `-h`, `--help`      | show this help message and exit                                    | —       |
| `--json`            | Emit one JSON object per line for machine consumption              | `false` |
| `--jsonl`           | Alias for --json                                                   | `false` |
| `--limit LIMIT`     | Maximum number of records to show (default: 20)                    | `20`    |
| `--outcome OUTCOME` | Filter by outcome (choices: `failure`, `success`)                  | —       |
| `--since SINCE`     | Only show records on/after this date (same grammar as 'sase logs') | —       |

Related: [CLI command groups](index.md).

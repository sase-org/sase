---
title: "sase doctor"
description: "Run fast, read-only diagnostics for the active SASE runtime, configuration, and project checkout."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase doctor

Run read-only SASE diagnostics for support

Reference for `sase doctor`. Run `sase doctor --help` for the exact output on this checkout.

```text
usage: sase doctor [-h] [-C ID_OR_GROUP] [-D] [-F] [-R] [-j] [-L] [-p PROJECT]
                   [-s] [-v] [-y]
```

Run fast, read-only diagnostics for the active SASE runtime, configuration, and project checkout. Default mode is bounded and safe to run before asking for help.

Options:

| Option                                  | Description                                                                                             | Default |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------- | ------- |
| `-C ID_OR_GROUP`, `--check ID_OR_GROUP` | Run only a check id or group; repeatable                                                                | —       |
| `-D`, `--deep`                          | Include slower read-only deep checks                                                                    | `false` |
| `-F`, `--fix-duplicate-blocks`          | Preview and, after confirmation, keep one block per Patch name in every ProjectSpec                     | `false` |
| `-R`, `--fix-primary-sidecar-links`     | Preview and, after confirmation, restore stranded link-index deletions in primary-nested sidecar clones | `false` |
| `-h`, `--help`                          | show this help message and exit                                                                         | —       |
| `-j`, `--json`                          | Emit a machine-readable JSON support report                                                             | `false` |
| `-L`, `--list-checks`                   | List registered diagnostic checks without running them                                                  | `false` |
| `-p PROJECT`, `--project PROJECT`       | Project name to inspect when it cannot be inferred                                                      | —       |
| `-s`, `--strict`                        | Exit non-zero when warnings are present                                                                 | `false` |
| `-v`, `--verbose`                       | Show every check and bounded detail                                                                     | `false` |
| `-y`, `--yes`                           | Apply requested repairs without an interactive confirmation                                             | `false` |

Related: [CLI command groups](index.md).

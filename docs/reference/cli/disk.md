---
title: "sase disk"
description: "Inspect SASE-owned disk usage and delegate cleanup to each owner."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase disk

Inspect and reclaim SASE-owned disk usage

Reference for `sase disk`. Run `sase disk --help` for the exact output on this checkout.

```text
usage: sase disk [-h] {list,reap} ...
```

Inspect SASE-owned disk usage and delegate cleanup to each owner. Bare `sase disk` defaults to `sase disk list`.

Bare `sase disk` defaults to `sase disk list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand       | Summary                             |
| ---------------- | ----------------------------------- |
| `sase disk list` | List SASE disk usage by owner       |
| `sase disk reap` | Preview or run owner cleanup passes |

## `sase disk list`

```text
usage: sase disk list [-h] [-j]
```

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

## `sase disk reap`

```text
usage: sase disk reap [-h] [-a] [-j] [-p PROJECT]
```

Delegate cleanup to the owner for each disk class. This command is a dry run unless --apply is passed; unowned Cargo-shaped strays are reported by `sase disk list` and are never deleted here.

Options:

| Option                            | Description                                                        | Default |
| --------------------------------- | ------------------------------------------------------------------ | ------- |
| `-a`, `--apply`                   | Run owner cleanup passes instead of previewing them                | `false` |
| `-h`, `--help`                    | show this help message and exit                                    | —       |
| `-j`, `--json`                    | Emit a machine-readable JSON object                                | `false` |
| `-p PROJECT`, `--project PROJECT` | Limit project-scoped artifact and workspace cleanup to one project | —       |

Related: [CLI command groups](index.md).

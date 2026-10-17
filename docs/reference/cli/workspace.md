---
title: "sase workspace"
description: "Inspect and manage managed workspace checkouts"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase workspace

Inspect and manage managed workspace checkouts

Reference for `sase workspace`. Run `sase workspace --help` for the exact output on this checkout.

```text
usage: sase workspace [-h] {cleanup,compact,list,migrate,open,path,repair} ...
```

Bare `sase workspace` defaults to `sase workspace list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand               | Summary                                                  |
| ------------------------ | -------------------------------------------------------- |
| `sase workspace cleanup` | Remove stale managed checkouts no longer claimed         |
| `sase workspace compact` | Share and compact Git objects for safe managed checkouts |
| `sase workspace list`    | List managed workspace checkouts (including primary #0)  |
| `sase workspace migrate` | Migrate adjacent workspaces to a managed root            |
| `sase workspace open`    | —                                                        |
| `sase workspace path`    | Print the checkout path for a workspace number           |
| `sase workspace repair`  | Reconcile the workspace registry with the filesystem     |

## `sase workspace cleanup`

```text
usage: sase workspace cleanup [-h] [-p PROJECT] [-s] [-i] [-n]
```

Options:

| Option                            | Description                                                      | Default |
| --------------------------------- | ---------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`                 | Report planned removals without touching the filesystem          | `false` |
| `-h`, `--help`                    | show this help message and exit                                  | —       |
| `-i`, `--include-shares`          | Also consider workflow-share managed checkouts for removal       | `false` |
| `-p PROJECT`, `--project PROJECT` | Project to clean (default: infer from current directory)         | —       |
| `-s`, `--stale`                   | Remove unclaimed managed checkouts older than the configured TTL | `false` |

## `sase workspace compact`

```text
usage: sase workspace compact [-h] [NUM ...] [-p PROJECT] [-n] [-j]
```

Options:

| Option                            | Description                                                       | Default |
| --------------------------------- | ----------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`                 | Report planned compactions without touching Git config or objects | `false` |
| `-h`, `--help`                    | show this help message and exit                                   | —       |
| `-j`, `--json`                    | Emit a machine-readable JSON object                               | `false` |
| `-p PROJECT`, `--project PROJECT` | Project to compact (default: infer from current directory)        | —       |

Arguments:

| Argument         | Description                                                                   |
| ---------------- | ----------------------------------------------------------------------------- |
| `workspace_nums` | Optional workspace number(s) to compact; default scans all numbered checkouts |

## `sase workspace list`

```text
usage: sase workspace list [-h] [-a] [-j] [-p PROJECT]
```

Options:

| Option                            | Description                                                         | Default |
| --------------------------------- | ------------------------------------------------------------------- | ------- |
| `-a`, `--all`                     | List registered workspaces across all enabled and disabled projects | `false` |
| `-h`, `--help`                    | show this help message and exit                                     | —       |
| `-j`, `--json`                    | Emit a machine-readable JSON object                                 | `false` |
| `-p PROJECT`, `--project PROJECT` | Project to query (default: infer from current directory)            | —       |

## `sase workspace migrate`

```text
usage: sase workspace migrate [-h] [-p PROJECT] [-t {xdg-state}] [-s] [-f]
                              [-n]
```

Options:

| Option                            | Description                                                                         | Default |
| --------------------------------- | ----------------------------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`                 | Report planned actions without touching the filesystem or registry                  | `false` |
| `-f`, `--finalize`                | Remove transition symlinks left behind by a prior migration                         | `false` |
| `-h`, `--help`                    | show this help message and exit                                                     | —       |
| `-p PROJECT`, `--project PROJECT` | Project to migrate (default: infer from current directory)                          | —       |
| `-s`, `--symlink-transition`      | Leave a '<primary>_<num>' symlink pointing to each migrated checkout                | `false` |
| `-t TO`, `--to TO`                | Target root policy (currently only 'xdg-state' is supported) (choices: `xdg-state`) | —       |

## `sase workspace open`

```text
usage: sase workspace open [-h] workspace_num [-p PROJECT] -r REASON [-P] [-c]
```

Options:

| Option                            | Description                                                                  | Default |
| --------------------------------- | ---------------------------------------------------------------------------- | ------- |
| `-c`, `--clean`                   | Prepare, clean, and update before printing (default; kept for compatibility) | `false` |
| `-h`, `--help`                    | show this help message and exit                                              | —       |
| `-P`, `--print`                   | Print the prepared path (default; kept for compatibility)                    | `false` |
| `-p PROJECT`, `--project PROJECT` | Project to query (default: infer from current directory)                     | —       |
| `-r REASON`, `--reason REASON`    | Non-empty reason for opening and preparing the workspace (required)          | —       |

Arguments:

| Argument        | Description                                          |
| --------------- | ---------------------------------------------------- |
| `workspace_num` | Workspace number (0 = primary, 10+ = managed claims) |

## `sase workspace path`

```text
usage: sase workspace path [-h] workspace_num [-p PROJECT]
```

Options:

| Option                            | Description                                              | Default |
| --------------------------------- | -------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                          | —       |
| `-p PROJECT`, `--project PROJECT` | Project to query (default: infer from current directory) | —       |

Arguments:

| Argument        | Description                                          |
| --------------- | ---------------------------------------------------- |
| `workspace_num` | Workspace number (0 = primary, 10+ = managed claims) |

## `sase workspace repair`

```text
usage: sase workspace repair [-h] [-p PROJECT] [-n]
```

Options:

| Option                            | Description                                                        | Default |
| --------------------------------- | ------------------------------------------------------------------ | ------- |
| `-n`, `--dry-run`                 | Report planned changes without touching the filesystem or registry | `false` |
| `-h`, `--help`                    | show this help message and exit                                    | —       |
| `-p PROJECT`, `--project PROJECT` | Project to repair (default: infer from current directory)          | —       |

Related: [CLI command groups](index.md).

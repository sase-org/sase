---
title: "sase file-hook"
description: "Inspect non-gating commands configured under `file_hooks` and the producer audit history for matching, dispatch, and pre-run failures."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase file-hook

Inspect configured per-file repository hooks

Reference for `sase file-hook`. Run `sase file-hook --help` for the exact output on this checkout.

```text
usage: sase file-hook [-h] {exec-batch,history,list,show} ...
```

Inspect non-gating commands configured under `file_hooks` and the producer audit history for matching, dispatch, and pre-run failures. With no subcommand, `sase file-hook` defaults to `sase file-hook list`.

Bare `sase file-hook` defaults to `sase file-hook list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                  | Summary                                            |
| --------------------------- | -------------------------------------------------- |
| `sase file-hook exec-batch` | —                                                  |
| `sase file-hook history`    | Show recent producer dispatch audits               |
| `sase file-hook list`       | List effective file hooks and their config sources |
| `sase file-hook show`       | Show one producer dispatch audit                   |

## `sase file-hook exec-batch`

```text
usage: sase file-hook exec-batch [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase file-hook history`

```text
usage: sase file-hook history [-h] [-j] [-n N]
```

List producer-side file-hook outcomes newest first: dispatched batches, filter misses, no configured hooks, and producer failures. Command-run failures still live on batch run logs; this surface is the pre-run evidence. This is not the default for bare `sase file-hook`.

Options:

| Option              | Description                                                 | Default |
| ------------------- | ----------------------------------------------------------- | ------- |
| `-h`, `--help`      | show this help message and exit                             | —       |
| `-j`, `--json`      | Emit deterministic machine-readable JSON                    | `false` |
| `-n N`, `--limit N` | Maximum number of audits to show (default: 20; 0 means all) | `20`    |

## `sase file-hook list`

```text
usage: sase file-hook list [-h] [-j]
```

List every valid effective file hook with its command, filters, timeout, description, and contributing config layer. Invalid entries are warned about and skipped. This is also the default for bare `sase file-hook`.

Options:

| Option         | Description                              | Default |
| -------------- | ---------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit          | —       |
| `-j`, `--json` | Emit deterministic machine-readable JSON | `false` |

## `sase file-hook show`

```text
usage: sase file-hook show [-h] audit_id [-j]
```

Print one producer audit by exact id or unique prefix so an operator can tell whether an event was unmatched, dispatched, or failed before a hook command ran.

Options:

| Option         | Description                              | Default |
| -------------- | ---------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit          | —       |
| `-j`, `--json` | Emit deterministic machine-readable JSON | `false` |

Arguments:

| Argument   | Description                                      |
| ---------- | ------------------------------------------------ |
| `audit_id` | Producer audit id, or a unique prefix of that id |

Related: [CLI command groups](index.md).

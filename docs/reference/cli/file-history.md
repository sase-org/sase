---
title: "sase file-history"
description: "Inspect and modify the file-reference history"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase file-history

Inspect and modify the file-reference history

Reference for `sase file-history`. Run `sase file-history --help` for the exact output on this checkout.

```text
usage: sase file-history [-h] {delete,list} ...
```

Bare `sase file-history` defaults to `sase file-history list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                 | Summary                                                          |
| -------------------------- | ---------------------------------------------------------------- |
| `sase file-history delete` | Remove one entry from the file-reference history                 |
| `sase file-history list`   | Print the recency-ordered file-reference history as a JSON array |

## `sase file-history delete`

```text
usage: sase file-history delete [-h] -p PATH
```

Options:

| Option                   | Description                                                           | Default |
| ------------------------ | --------------------------------------------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit                                       | —       |
| `-p PATH`, `--path PATH` | Path entry to remove (must exactly match the stored value) (required) | —       |

## `sase file-history list`

```text
usage: sase file-history list [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Related: [CLI command groups](index.md).

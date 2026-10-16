---
title: "sase file"
description: "Filesystem completion helpers (consumed by editor integrations)"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase file

Filesystem completion helpers (consumed by editor integrations)

Reference for `sase file`. Run `sase file --help` for the exact output on this checkout.

```text
usage: sase file [-h] {list} ...
```

Bare `sase file` defaults to `sase file list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand       | Summary                                       |
| ---------------- | --------------------------------------------- |
| `sase file list` | List filesystem completion candidates as JSON |

## `sase file list`

```text
usage: sase file list [-h] [-p PATH] [-t TOKEN]
```

Options:

| Option                      | Description                                                      | Default |
| --------------------------- | ---------------------------------------------------------------- | ------- |
| `-h`, `--help`              | show this help message and exit                                  | —       |
| `-p PATH`, `--path PATH`    | Directory to anchor relative paths from (default: current dir)   | `.`     |
| `-t TOKEN`, `--token TOKEN` | Partial token under cursor (e.g., 'src/foo'); empty lists --path | ``      |

Related: [CLI command groups](index.md).

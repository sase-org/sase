---
title: "sase core"
description: "Inspect the required sase_core_rs Rust extension"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase core

Inspect the required sase_core_rs Rust extension

Reference for `sase core`. Run `sase core --help` for the exact output on this checkout.

```text
usage: sase core [-h] {health} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand         | Summary                                                             |
| ------------------ | ------------------------------------------------------------------- |
| `sase core health` | Check that the sase_core_rs Rust extension is installed and working |

## `sase core health`

```text
usage: sase core health [-h] [-j]
```

Options:

| Option         | Description                                       | Default |
| -------------- | ------------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                   | —       |
| `-j`, `--json` | Emit the health report as JSON (machine-readable) | `false` |

Related: [CLI command groups](index.md).

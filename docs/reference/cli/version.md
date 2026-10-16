---
title: "sase version"
description: "Show the exact SASE host, Rust core, and plugin packages used by this process."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase version

Show the active SASE runtime package inventory

Reference for `sase version`. Run `sase version --help` for the exact output on this checkout.

```text
usage: sase version [-h] [-j] [-v]
```

Show the exact SASE host, Rust core, and plugin packages used by this process.

Options:

| Option            | Description                                                     | Default |
| ----------------- | --------------------------------------------------------------- | ------- |
| `-h`, `--help`    | show this help message and exit                                 | —       |
| `-j`, `--json`    | Emit a machine-readable JSON object                             | `false` |
| `-v`, `--verbose` | Show additional install, source, git, and plugin signal details | `false` |

Related: [CLI command groups](index.md).

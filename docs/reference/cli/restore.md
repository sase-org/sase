---
title: "sase restore"
description: "Restore a reverted Patch by re-applying its diff and creating a new PR"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase restore

Restore a reverted Patch by re-applying its diff and creating a new PR

Reference for `sase restore`. Run `sase restore --help` for the exact output on this checkout.

```text
usage: sase restore [-h] [name] [-l]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-l`, `--list` | List all reverted Patches       | `false` |

Arguments:

| Argument | Description                                                       |
| -------- | ----------------------------------------------------------------- |
| `name`   | NAME of the reverted Patch to restore (e.g., 'foobar_feature__2') |

Related: [CLI command groups](index.md).

---
title: "sase logs"
description: "Collect logs and runtime data for a date range into a pack directory"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase logs

Collect logs and runtime data for a date range into a pack directory

Reference for `sase logs`. Run `sase logs --help` for the exact output on this checkout.

```text
usage: sase logs [-h] daterange
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument    | Description                                                                                                    |
| ----------- | -------------------------------------------------------------------------------------------------------------- |
| `daterange` | Date range to collect. Formats: YYmmdd, YYmmddHHMMSS, -Nd, 0d, START..END (e.g., -7d..0d, 260315..260318, -7d) |

Related: [CLI command groups](index.md).

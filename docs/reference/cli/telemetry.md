---
title: "sase telemetry"
description: "Inspect locally persisted telemetry."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase telemetry

Inspect locally persisted telemetry (defaults to list)

Reference for `sase telemetry`. Run `sase telemetry --help` for the exact output on this checkout.

```text
usage: sase telemetry [-h] {cleanup-test-data,health,list,snapshot,status} ...
```

Inspect locally persisted telemetry. Running 'sase telemetry' without a subcommand delegates to 'sase telemetry list'.

Bare `sase telemetry` defaults to `sase telemetry list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                         | Summary                                            |
| ---------------------------------- | -------------------------------------------------- |
| `sase telemetry cleanup-test-data` | Preview or remove telemetry with known test labels |
| `sase telemetry health`            | Traffic-light health assessment                    |
| `sase telemetry list`              | Show the metric catalog from internal definitions  |
| `sase telemetry snapshot`          | Display current values from the local store        |
| `sase telemetry status`            | Quick health check and config display              |

## `sase telemetry cleanup-test-data`

```text
usage: sase telemetry cleanup-test-data [-h] [-n] [-y]
```

Preview or remove telemetry rows whose exact labels identify test data. Deletion requires the explicit -y/--yes flag.

Options:

| Option            | Description                                 | Default |
| ----------------- | ------------------------------------------- | ------- |
| `-n`, `--dry-run` | Preview exact matches without deleting rows | `false` |
| `-h`, `--help`    | show this help message and exit             | —       |
| `-y`, `--yes`     | Confirm deletion after the preview          | `false` |

## `sase telemetry health`

```text
usage: sase telemetry health [-h] [-j]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Machine-readable JSON output    | `false` |

## `sase telemetry list`

```text
usage: sase telemetry list [-h] [-s SUBSYSTEM] [-t {counter,gauge,histogram}]
```

Options:

| Option                                  | Description                                                      | Default |
| --------------------------------------- | ---------------------------------------------------------------- | ------- |
| `-h`, `--help`                          | show this help message and exit                                  | —       |
| `-s SUBSYSTEM`, `--subsystem SUBSYSTEM` | Filter to a specific subsystem (e.g., 'Agent Lifecycle')         | —       |
| `-t TYPE`, `--type TYPE`                | Filter by metric type (choices: `counter`, `gauge`, `histogram`) | —       |

## `sase telemetry snapshot`

```text
usage: sase telemetry snapshot [-h] [-f {json,rich}] [-s SUBSYSTEM]
```

Options:

| Option                                  | Description                                             | Default |
| --------------------------------------- | ------------------------------------------------------- | ------- |
| `-f FORMAT`, `--format FORMAT`          | Output format (default: rich) (choices: `json`, `rich`) | `rich`  |
| `-h`, `--help`                          | show this help message and exit                         | —       |
| `-s SUBSYSTEM`, `--subsystem SUBSYSTEM` | Filter by subsystem                                     | —       |

## `sase telemetry status`

```text
usage: sase telemetry status [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Related: [CLI command groups](index.md).

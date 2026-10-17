---
title: "sase repro"
description: "Capture and replay reproduction bundles"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase repro

Capture and replay reproduction bundles

Reference for `sase repro`. Run `sase repro --help` for the exact output on this checkout.

```text
usage: sase repro [-h] {capture,replay} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                                                       |
| -------------------- | ------------------------------------------------------------- |
| `sase repro capture` | Capture a reproduction bundle                                 |
| `sase repro replay`  | Replay a reproduction bundle through the headless TUI harness |

## `sase repro capture`

```text
usage: sase repro capture [-h] {agents-tab} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                      | Summary                                                         |
| ------------------------------- | --------------------------------------------------------------- |
| `sase repro capture agents-tab` | Capture an Agents-tab reproduction bundle from filesystem state |

### `sase repro capture agents-tab`

```text
usage: sase repro capture agents-tab [-h] --output OUTPUT [--commit-safe]
                                     [--no-commit-safe] [--size SIZE] [--json]
```

Options:

| Option             | Description                                                                | Default  |
| ------------------ | -------------------------------------------------------------------------- | -------- |
| `--commit-safe`    | Redact local names and paths for a shareable bundle (default)              | `true`   |
| `-h`, `--help`     | show this help message and exit                                            | —        |
| `--json`           | Emit a machine-readable JSON result                                        | `false`  |
| `--no-commit-safe` | Keep unredacted local identifiers in the capture                           | `true`   |
| `--output OUTPUT`  | Directory where agents_tab_repro.json and artifacts are written (required) | —        |
| `--size SIZE`      | Terminal size label to store with the bundle, WIDTHxHEIGHT                 | `120x40` |

## `sase repro replay`

```text
usage: sase repro replay [-h] path [--assert-stable] [--json]
                         [--write-artifacts WRITE_ARTIFACTS] [--size SIZE]
```

Options:

| Option                              | Description                                                      | Default  |
| ----------------------------------- | ---------------------------------------------------------------- | -------- |
| `--assert-stable`                   | Exit non-zero if replay invariants fail                          | `false`  |
| `-h`, `--help`                      | show this help message and exit                                  | —        |
| `--json`                            | Emit a machine-readable JSON verdict                             | `false`  |
| `--size SIZE`                       | Headless terminal size for replay, WIDTHxHEIGHT                  | `120x40` |
| `--write-artifacts WRITE_ARTIFACTS` | Directory where replay screen text and SVG artifacts are written | —        |

Arguments:

| Argument | Description                          |
| -------- | ------------------------------------ |
| `path`   | Bundle JSON file or bundle directory |

Related: [CLI command groups](index.md).

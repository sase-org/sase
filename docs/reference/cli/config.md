---
title: "sase config"
description: "Inspect merged configuration, layers, and mentor profile matching"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase config

Inspect merged configuration, layers, and mentor profile matching

Reference for `sase config`. Run `sase config --help` for the exact output on this checkout.

```text
usage: sase config [-h]
                   {init,layers,mentor-match,migrate-keymap-actions,show} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                           | Summary                                                                                                         |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| `sase config init`                   | Initialize the explicit SASE owner identity                                                                     |
| `sase config layers`                 | Show per-layer breakdown of the config merge chain                                                              |
| `sase config mentor-match`           | Trace mentor profile matching for a Patch                                                                       |
| `sase config migrate-keymap-actions` | Rewrite ace.keymaps.app overrides that name a keymap action retired by sase-m6.9 to their canonical replacement |
| `sase config show`                   | Print the final merged config as YAML                                                                           |

## `sase config init`

```text
usage: sase config init [-h] [-c]
```

Interactively create or migrate id.username and id.machine_name in the selected machine overlay, then record the local selector.

Options:

| Option          | Description                                                         | Default |
| --------------- | ------------------------------------------------------------------- | ------- |
| `-c`, `--check` | Report whether owner identity initialization or migration is needed | `false` |
| `-h`, `--help`  | show this help message and exit                                     | —       |

## `sase config layers`

```text
usage: sase config layers [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase config mentor-match`

```text
usage: sase config mentor-match [-h] patch_name
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument     | Description                             |
| ------------ | --------------------------------------- |
| `patch_name` | NAME of the Patch to trace matching for |

## `sase config migrate-keymap-actions`

```text
usage: sase config migrate-keymap-actions [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase config show`

```text
usage: sase config show [-h] [-k KEY]
```

Options:

| Option                | Description                                              | Default |
| --------------------- | -------------------------------------------------------- | ------- |
| `-h`, `--help`        | show this help message and exit                          | —       |
| `-k KEY`, `--key KEY` | Extract a specific top-level key (e.g., mentor_profiles) | —       |

Related: [CLI command groups](index.md).

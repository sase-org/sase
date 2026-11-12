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
                   {init,layers,mentor-match,migrate-keymap-actions,show,trust} ...
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
| `sase config trust`                  | Review and manage trust for project-local commands                                                              |

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

## `sase config trust`

```text
usage: sase config trust [-h] {allow,revoke,status} ...
```

Acknowledge the current digest of project-local executable config, inspect its status, or revoke the acknowledgment.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                 | Summary                                                        |
| -------------------------- | -------------------------------------------------------------- |
| `sase config trust allow`  | Review and acknowledge the selected project's current commands |
| `sase config trust revoke` | Remove the selected project's current acknowledgment           |
| `sase config trust status` | Show the selected project's current trust status               |

### `sase config trust allow`

```text
usage: sase config trust allow [-h] [PATH]
```

Show the exact command-bearing config projection and require a human confirmation in a foreground terminal.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                                                   |
| -------- | ------------------------------------------------------------- |
| `path`   | Checkout or its selected sase.yml (default: current checkout) |

### `sase config trust revoke`

```text
usage: sase config trust revoke [-h] [PATH]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                                                   |
| -------- | ------------------------------------------------------------- |
| `path`   | Checkout or its selected sase.yml (default: current checkout) |

### `sase config trust status`

```text
usage: sase config trust status [-h] [PATH] [-j]
```

Options:

| Option         | Description                        | Default |
| -------------- | ---------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit    | —       |
| `-j`, `--json` | Print machine-readable status JSON | `false` |

Arguments:

| Argument | Description                                                   |
| -------- | ------------------------------------------------------------- |
| `path`   | Checkout or its selected sase.yml (default: current checkout) |

Related: [CLI command groups](index.md).

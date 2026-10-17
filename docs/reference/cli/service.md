---
title: "sase service"
description: "Manage the per-machine SASE service host."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase service

Manage the per-machine SASE service host

Reference for `sase service`. Run `sase service --help` for the exact output on this checkout.

```text
usage: sase service [-h]
                    {init,logs,proc,restart,run,start,status,stop,uninstall} ...
```

Manage the per-machine SASE service host. Bare `sase service` is harmless and shows `sase service status`; use `sase service run` only when you intentionally want the host in the foreground.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand               | Summary                                                               |
| ------------------------ | --------------------------------------------------------------------- |
| `sase service init`      | Install or check the native service-host unit                         |
| `sase service logs`      | Show the detached service-host log                                    |
| `sase service proc`      | Control configured service procs; bare `proc` defaults to `proc list` |
| `sase service restart`   | Restart the detached service host                                     |
| `sase service run`       | Run the service host in the foreground                                |
| `sase service start`     | Start the service host detached                                       |
| `sase service status`    | Show service host and proc status                                     |
| `sase service stop`      | Stop the running service host                                         |
| `sase service uninstall` | Unload and remove the native service-host unit                        |

## `sase service init`

```text
usage: sase service init [-h] [-a] [-c] [-d] [-f] [-y]
```

Options:

| Option                    | Description                                                                            | Default |
| ------------------------- | -------------------------------------------------------------------------------------- | ------- |
| `-a`, `--allow-agent-env` | Capture this shell's environment even from a SASE agent process or ephemeral workspace | `false` |
| `-c`, `--check`           | Report platform-unit drift without writing files or changing the native manager        | `false` |
| `-d`, `--diff`            | Show desired native-unit and redacted environment diffs without writing                | `false` |
| `-f`, `--force`           | Allow installation for a non-default SASE_HOME using a home-scoped unit identity       | `false` |
| `-h`, `--help`            | show this help message and exit                                                        | —       |
| `-y`, `--yes`             | Apply the planned native-manager changes                                               | `false` |

## `sase service logs`

```text
usage: sase service logs [-h] [-n N]
```

Options:

| Option              | Description                      | Default |
| ------------------- | -------------------------------- | ------- |
| `-h`, `--help`      | show this help message and exit  | —       |
| `-n N`, `--lines N` | Log lines to show (default: 200) | `200`   |

## `sase service proc`

```text
usage: sase service proc [-h]
                         {disable,enable,list,logs,restart,run,show,start,stop} ...
```

Control configured daemon service procs and launch transient oneshot service procs. Running `sase service proc` defaults to `sase service proc list`.

Bare `sase service proc` defaults to `sase service proc list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                  | Summary                                                |
| --------------------------- | ------------------------------------------------------ |
| `sase service proc disable` | Disable a configured service proc on this machine      |
| `sase service proc enable`  | Enable a configured service proc on this machine       |
| `sase service proc list`    | List configured service procs                          |
| `sase service proc logs`    | Show one service proc's bounded output log             |
| `sase service proc restart` | Ask the service host to restart a service proc         |
| `sase service proc run`     | Run a transient oneshot under the durable proc service |
| `sase service proc show`    | Show one configured service proc                       |
| `sase service proc start`   | Ask the service host to start a service proc           |
| `sase service proc stop`    | Stop a service proc until the next boot                |

### `sase service proc disable`

```text
usage: sase service proc disable [-h] NAME
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | —           |

### `sase service proc enable`

```text
usage: sase service proc enable [-h] NAME
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | —           |

### `sase service proc list`

```text
usage: sase service proc list [-h] [-j]
```

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

### `sase service proc logs`

```text
usage: sase service proc logs [-h] NAME [-n N]
```

Options:

| Option              | Description                      | Default |
| ------------------- | -------------------------------- | ------- |
| `-h`, `--help`      | show this help message and exit  | —       |
| `-n N`, `--lines N` | Log lines to show (default: 200) | `200`   |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | —           |

### `sase service proc restart`

```text
usage: sase service proc restart [-h] NAME [-n] [-t SECONDS]
```

Options:

| Option                            | Description                                                                              | Default |
| --------------------------------- | ---------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                                          | —       |
| `-n`, `--no-wait`                 | Return as soon as the request is recorded                                                | `false` |
| `-t SECONDS`, `--timeout SECONDS` | How long to wait for the host to confirm (default: derived from the proc's stop timeout) | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | —           |

### `sase service proc run`

```text
usage: sase service proc run [-h] [-c DIR] [-j] [-l TEXT] [-p NAME] [-w N] ...
```

Submit a transient oneshot service proc through the durable proc service. It is not named, is not added to daemon desired state, and the service host never replays it after restart. It runs outside the service host's process tree, records its exit code, and shows in the Services tab's oneshots section under a #1-#9 index (at most nine can be running at once; finished ones never count). The TUI's `!!` background commands use this same path. Everything after `--` is the command to run.

Options:

| Option                      | Description                                                    | Default |
| --------------------------- | -------------------------------------------------------------- | ------- |
| `-c DIR`, `--cwd DIR`       | Working directory for the command (default: current directory) | —       |
| `-h`, `--help`              | show this help message and exit                                | —       |
| `-j`, `--json`              | Emit a machine-readable JSON object                            | `false` |
| `-l TEXT`, `--label TEXT`   | Human-facing proc label (default: derived from command)        | —       |
| `-p NAME`, `--project NAME` | Project to attribute the proc to                               | —       |
| `-w N`, `--workspace N`     | Workspace number to attribute the proc to                      | —       |

Arguments:

| Argument       | Description                      |
| -------------- | -------------------------------- |
| `proc_command` | Command to run, introduced by -- |

### `sase service proc show`

```text
usage: sase service proc show [-h] NAME [-j]
```

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | —           |

### `sase service proc start`

```text
usage: sase service proc start [-h] NAME [-n] [-t SECONDS]
```

Options:

| Option                            | Description                                                                              | Default |
| --------------------------------- | ---------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                                          | —       |
| `-n`, `--no-wait`                 | Return as soon as the request is recorded                                                | `false` |
| `-t SECONDS`, `--timeout SECONDS` | How long to wait for the host to confirm (default: derived from the proc's stop timeout) | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | —           |

### `sase service proc stop`

```text
usage: sase service proc stop [-h] NAME
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | —           |

## `sase service restart`

```text
usage: sase service restart [-h] [-j]
```

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

## `sase service run`

```text
usage: sase service run [-h]
```

Run the service host in the foreground. This command owns the host lock for its entire lifetime, supervises configured daemon service procs as direct children, and exits on SIGTERM, SIGINT, or Ctrl-C.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase service start`

```text
usage: sase service start [-h] [-j]
```

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

## `sase service status`

```text
usage: sase service status [-h] [-j]
```

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

## `sase service stop`

```text
usage: sase service stop [-h] [-j]
```

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

## `sase service uninstall`

```text
usage: sase service uninstall [-h] [-c] [-d] [-f] [-y]
```

Options:

| Option          | Description                                                                        | Default |
| --------------- | ---------------------------------------------------------------------------------- | ------- |
| `-c`, `--check` | Report platform-unit drift without writing files or changing the native manager    | `false` |
| `-d`, `--diff`  | Show desired native-unit and redacted environment diffs without writing            | `false` |
| `-f`, `--force` | Allow uninstallation for a non-default SASE_HOME using a home-scoped unit identity | `false` |
| `-h`, `--help`  | show this help message and exit                                                    | —       |
| `-y`, `--yes`   | Apply the planned native-manager changes                                           | `false` |

Related: [CLI command groups](index.md).

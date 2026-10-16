---
title: "sase scheduler"
description: "Control the SASE scheduler."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase scheduler

Control the SASE scheduler

Reference for `sase scheduler`. Run `sase scheduler --help` for the exact output on this checkout.

```text
usage: sase scheduler [-h] {restart,run,start,status,stop} ...
```

Control the SASE scheduler. start, stop, restart, and status route through the `scheduler` service proc on the SASE service host; run execs the foreground orchestrator that the service host itself runs. `sase axe start|stop|restart|status` is an alias of this command.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand               | Summary                                            |
| ------------------------ | -------------------------------------------------- |
| `sase scheduler restart` | Ask the service host to restart the scheduler proc |
| `sase scheduler run`     | Run the foreground scheduler orchestrator          |
| `sase scheduler start`   | Ask the service host to start the scheduler proc   |
| `sase scheduler status`  | Show scheduler status                              |
| `sase scheduler stop`    | Ask the service host to stop the scheduler proc    |

## `sase scheduler restart`

```text
usage: sase scheduler restart [-h] [-n] [-t SECONDS]
```

Ask the service host to stop and start the `scheduler` service proc. Waits for the host to confirm the new pid.

Options:

| Option                            | Description                                                                              | Default |
| --------------------------------- | ---------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                                          | —       |
| `-n`, `--no-wait`                 | Return as soon as the request is recorded                                                | `false` |
| `-t SECONDS`, `--timeout SECONDS` | How long to wait for the host to confirm (default: derived from the proc's stop timeout) | —       |

## `sase scheduler run`

```text
usage: sase scheduler run [-h] [-A MAX_AGENT_RUNNERS] [-H MAX_HOOK_RUNNERS]
                          [-q QUERY] [-z ZOMBIE_TIMEOUT]
```

Options:

| Option                                                          | Description                                                 | Default |
| --------------------------------------------------------------- | ----------------------------------------------------------- | ------- |
| `-h`, `--help`                                                  | show this help message and exit                             | —       |
| `-A MAX_AGENT_RUNNERS`, `--max-agent-runners MAX_AGENT_RUNNERS` | Maximum concurrent agent runners (default: config value)    | —       |
| `-H MAX_HOOK_RUNNERS`, `--max-hook-runners MAX_HOOK_RUNNERS`    | Maximum concurrent hook runners (default: config value)     | —       |
| `-q QUERY`, `--query QUERY`                                     | Query string for filtering Patches (empty = config value)   | ``      |
| `-z ZOMBIE_TIMEOUT`, `--zombie-timeout ZOMBIE_TIMEOUT`          | Zombie detection timeout in seconds (default: config value) | —       |

## `sase scheduler start`

```text
usage: sase scheduler start [-h] [-n] [-t SECONDS]
```

Ask the service host to start the `scheduler` service proc. Waits for the host to confirm.

Options:

| Option                            | Description                                                                              | Default |
| --------------------------------- | ---------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                                          | —       |
| `-n`, `--no-wait`                 | Return as soon as the request is recorded                                                | `false` |
| `-t SECONDS`, `--timeout SECONDS` | How long to wait for the host to confirm (default: derived from the proc's stop timeout) | —       |

## `sase scheduler status`

```text
usage: sase scheduler status [-h] [-j]
```

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

## `sase scheduler stop`

```text
usage: sase scheduler stop [-h]
```

Ask the service host to stop the `scheduler` service proc. Returns once the request is recorded.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Related: [CLI command groups](index.md).

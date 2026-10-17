---
title: "sase axe"
description: "Alias of `sase scheduler`, plus the routine and job tree"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase axe

Alias of `sase scheduler`, plus the routine and job tree

Reference for `sase axe`. Run `sase axe --help` for the exact output on this checkout.

```text
usage: sase axe [-h] [-v {git,hg,auto}]
                {job,maintenance,restart,routine,start,status,stop} ...
```

Options:

| Option                                           | Description                                                                                      | Default |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------ | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                  | —       |
| `-v VCS_PROVIDER`, `--vcs-provider VCS_PROVIDER` | Override VCS provider ('git', 'hg', or 'auto' for auto-detection) (choices: `auto`, `git`, `hg`) | —       |

Subcommands:

| Subcommand             | Summary                                                                                |
| ---------------------- | -------------------------------------------------------------------------------------- |
| `sase axe job`         | Inspect and run jobs (bare `job` defaults to `job list`)                               |
| `sase axe maintenance` | Manage axe maintenance mode                                                            |
| `sase axe restart`     | Ask the service host to restart the scheduler proc (alias of `sase scheduler restart`) |
| `sase axe routine`     | Routine management commands                                                            |
| `sase axe start`       | Ask the service host to start the scheduler proc (alias of `sase scheduler start`)     |
| `sase axe status`      | Show scheduler status (alias of `sase scheduler status`)                               |
| `sase axe stop`        | Ask the service host to stop the scheduler proc (alias of `sase scheduler stop`)       |

## `sase axe job`

```text
usage: sase axe job [-h] {doctor,list,run} ...
```

Bare `sase axe job` defaults to `sase axe job list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand            | Summary                                     |
| --------------------- | ------------------------------------------- |
| `sase axe job doctor` | Diagnose configured and available job setup |
| `sase axe job list`   | List configured jobs and their status       |
| `sase axe job run`    | Run a single job once in the foreground     |

### `sase axe job doctor`

```text
usage: sase axe job doctor [-h] [-j] [-v]
```

Options:

| Option            | Description                                                | Default |
| ----------------- | ---------------------------------------------------------- | ------- |
| `-h`, `--help`    | show this help message and exit                            | —       |
| `-j`, `--json`    | Emit a machine-readable JSON object                        | `false` |
| `-v`, `--verbose` | Show descriptions, resolution paths, and search-dir detail | `false` |

### `sase axe job list`

```text
usage: sase axe job list [-h] [-a] [-j] [-v]
```

Options:

| Option              | Description                                                                | Default |
| ------------------- | -------------------------------------------------------------------------- | ------- |
| `-a`, `--available` | Also show discoverable executable job scripts, including unconfigured ones | `false` |
| `-h`, `--help`      | show this help message and exit                                            | —       |
| `-j`, `--json`      | Emit a machine-readable JSON object                                        | `false` |
| `-v`, `--verbose`   | Show descriptions, resolution paths, and search-dir detail                 | `false` |

### `sase axe job run`

```text
usage: sase axe job run [-h] JOB [-V] [-n] [-f] [-L ROUTINE]
```

Options:

| Option                            | Description                                                                                          | Default |
| --------------------------------- | ---------------------------------------------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`                 | Run the script and preview validated agent proposals without launching                               | `false` |
| `-f`, `--force`                   | Bypass declarative guards for this manual run (triggers are already bypassed)                        | `false` |
| `-h`, `--help`                    | show this help message and exit                                                                      | —       |
| `-V`, `--job-verbose`             | Enable verbose script diagnostics and show the full structured result                                | `false` |
| `-L ROUTINE`, `--routine ROUTINE` | Configured routine to attribute the run to (required when the job name appears in multiple routines) | —       |

Arguments:

| Argument    | Description            |
| ----------- | ---------------------- |
| `chop_name` | Name of the job to run |

## `sase axe maintenance`

```text
usage: sase axe maintenance [-h] {enter,exit,status} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                    | Summary                 |
| ----------------------------- | ----------------------- |
| `sase axe maintenance enter`  | Enter maintenance mode  |
| `sase axe maintenance exit`   | Exit maintenance mode   |
| `sase axe maintenance status` | Show maintenance status |

### `sase axe maintenance enter`

```text
usage: sase axe maintenance enter [-h] -r REASON
```

Options:

| Option                         | Description                                     | Default |
| ------------------------------ | ----------------------------------------------- | ------- |
| `-h`, `--help`                 | show this help message and exit                 | —       |
| `-r REASON`, `--reason REASON` | Reason for entering maintenance mode (required) | —       |

### `sase axe maintenance exit`

```text
usage: sase axe maintenance exit [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

### `sase axe maintenance status`

```text
usage: sase axe maintenance status [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase axe restart`

```text
usage: sase axe restart [-h]
```

Ask the service host to stop and start the `scheduler` service proc. Returns once the request is recorded.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase axe routine`

```text
usage: sase axe routine [-h] {list,run,status} ...
```

Bare `sase axe routine` defaults to `sase axe routine list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                | Summary                                |
| ------------------------- | -------------------------------------- |
| `sase axe routine list`   | List configured routines               |
| `sase axe routine run`    | Run a single routine in the foreground |
| `sase axe routine status` | Show status of all routines            |

### `sase axe routine list`

```text
usage: sase axe routine list [-h] [-v]
```

Options:

| Option            | Description                     | Default |
| ----------------- | ------------------------------- | ------- |
| `-h`, `--help`    | show this help message and exit | —       |
| `-v`, `--verbose` | Show full routine descriptions  | `false` |

### `sase axe routine run`

```text
usage: sase axe routine run [-h] ROUTINE [-q QUERY] [-H MAX_HOOK_RUNNERS]
                            [-A MAX_AGENT_RUNNERS] [-z ZOMBIE_TIMEOUT]
```

Options:

| Option                                                          | Description                         | Default |
| --------------------------------------------------------------- | ----------------------------------- | ------- |
| `-h`, `--help`                                                  | show this help message and exit     | —       |
| `-A MAX_AGENT_RUNNERS`, `--max-agent-runners MAX_AGENT_RUNNERS` | Maximum concurrent agent runners    | —       |
| `-H MAX_HOOK_RUNNERS`, `--max-hook-runners MAX_HOOK_RUNNERS`    | Maximum concurrent hook runners     | —       |
| `-q QUERY`, `--query QUERY`                                     | Query string for filtering Patches  | ``      |
| `-z ZOMBIE_TIMEOUT`, `--zombie-timeout ZOMBIE_TIMEOUT`          | Zombie detection timeout in seconds | —       |

Arguments:

| Argument          | Description                |
| ----------------- | -------------------------- |
| `lumberjack_name` | Name of the routine to run |

### `sase axe routine status`

```text
usage: sase axe routine status [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase axe start`

```text
usage: sase axe start [-h]
```

Ask the service host to start the `scheduler` service proc. Returns once the request is recorded.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase axe status`

```text
usage: sase axe status [-h] [-j]
```

Show the `scheduler` service proc's status. Alias of `sase scheduler status`.

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

## `sase axe stop`

```text
usage: sase axe stop [-h]
```

Ask the service host to stop the `scheduler` service proc. Returns once the request is recorded.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Related: [CLI command groups](index.md).

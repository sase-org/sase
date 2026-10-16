---
title: "sase patch"
description: "Inspect and maintain Patch lifecycle records."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase patch

Inspect and maintain Patches

Aliases: `sase changespec`.

Reference for `sase patch`. Run `sase patch --help` for the exact output on this checkout.

```text
usage: sase patch [-h]
                  {accept,archive,current,mail,migrate-extension,rebase,ref,restore,revert,rewind,reword,search,set-origin,status,submit,sync,sync-deltas,sync-external,tag} ...
```

Inspect and maintain Patch lifecycle records.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                     | Summary                                                                                      |
| ------------------------------ | -------------------------------------------------------------------------------------------- |
| `sase patch accept`            | Accept proposal commits onto a Patch                                                         |
| `sase patch archive`           | Archive a Patch                                                                              |
| `sase patch current`           | Show the Patch associated with the current VCS checkout                                      |
| `sase patch mail`              | Mail a Ready Patch                                                                           |
| `sase patch migrate-extension` | Rename legacy .gp project spec files under ~/.sase/projects to the canonical .sase extension |
| `sase patch rebase`            | Rebase a Patch onto a new parent                                                             |
| `sase patch ref`               | Inspect and manage artifact references                                                       |
| `sase patch restore`           | Restore a Reverted Patch                                                                     |
| `sase patch revert`            | Revert a Patch                                                                               |
| `sase patch rewind`            | Rewind a Patch to a history entry                                                            |
| `sase patch reword`            | Reword a Patch description from the request sidecar                                          |
| `sase patch search`            | Search for Patches matching a query and display them                                         |
| `sase patch set-origin`        | Mark a Patch's PR_ORIGIN (sase, external, or unknown)                                        |
| `sase patch status`            | Transition a Patch STATUS through the domain state machine                                   |
| `sase patch submit`            | Submit a Patch                                                                               |
| `sase patch sync`              | Sync a Patch workspace from its VCS remote                                                   |
| `sase patch sync-deltas`       | Recompute the DELTAS field for a Patch from the live VCS state                               |
| `sase patch sync-external`     | Mirror remote pull requests into local Patch records                                         |
| `sase patch tag`               | Add a tag to a Patch description                                                             |

## `sase patch accept`

```text
usage: sase patch accept [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH] name
```

Accept proposal commits onto a Patch

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |

## `sase patch archive`

```text
usage: sase patch archive [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH] name
```

Archive a Patch

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |

## `sase patch current`

```text
usage: sase patch current [-h] [-f {markdown,plain,json}] [-p PROJECT_FILE]
```

Options:

| Option                                           | Description                                                               | Default    |
| ------------------------------------------------ | ------------------------------------------------------------------------- | ---------- |
| `-f FORMAT`, `--format FORMAT`                   | Output format (default: markdown) (choices: `json`, `markdown`, `plain`)  | `markdown` |
| `-h`, `--help`                                   | show this help message and exit                                           | —          |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from current workspace) | —          |

## `sase patch mail`

```text
usage: sase patch mail [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH] name
```

Mail a Ready Patch

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |

## `sase patch migrate-extension`

```text
usage: sase patch migrate-extension [-h] [--force]
                                    [--projects-dir PROJECTS_DIR]
```

Options:

| Option                        | Description                                                                                                                                             | Default |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `--force`                     | Replace an existing canonical .sase sibling whose contents differ from the legacy .gp file. Default policy is to report the conflict and skip the file. | `false` |
| `-h`, `--help`                | show this help message and exit                                                                                                                         | —       |
| `--projects-dir PROJECTS_DIR` | Override the ~/.sase/projects/ root that is scanned for legacy spec files. Primarily useful for testing.                                                | —       |

## `sase patch rebase`

```text
usage: sase patch rebase [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH]
                         name parent
```

Rebase a Patch onto a new parent

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |
| `parent` | parent      |

## `sase patch ref`

```text
usage: sase patch ref [-h] {add,list,rm} ...
```

Inspect and manage Patch artifact references. Invoking 'sase patch ref' without a subcommand delegates to 'sase patch ref list'.

Bare `sase patch ref` defaults to `sase patch ref list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand            | Summary                    |
| --------------------- | -------------------------- |
| `sase patch ref add`  | Attach artifact references |
| `sase patch ref list` | List artifact references   |
| `sase patch ref rm`   | Detach artifact references |

### `sase patch ref add`

```text
usage: sase patch ref add [-h] [-p PATCH] refs [refs ...]
```

Options:

| Option                                                        | Description                              | Default |
| ------------------------------------------------------------- | ---------------------------------------- | ------- |
| `-p PATCH`, `--patch PATCH`, `-c PATCH`, `--changespec PATCH` | Target Patch (default: current checkout) | —       |
| `-h`, `--help`                                                | show this help message and exit          | —       |

Arguments:

| Argument | Description                   |
| -------- | ----------------------------- |
| `refs`   | Artifact references to attach |

### `sase patch ref list`

```text
usage: sase patch ref list [-h] [-p PATCH] [-j] [-r]
```

Options:

| Option                                                        | Description                                      | Default |
| ------------------------------------------------------------- | ------------------------------------------------ | ------- |
| `-p PATCH`, `--patch PATCH`, `-c PATCH`, `--changespec PATCH` | Target Patch (default: current checkout)         | —       |
| `-h`, `--help`                                                | show this help message and exit                  | —       |
| `-j`, `--json`                                                | Emit machine-readable reference data             | `false` |
| `-r`, `--resolve`                                             | Resolve references against the current workspace | `false` |

### `sase patch ref rm`

```text
usage: sase patch ref rm [-h] [-p PATCH] refs [refs ...]
```

Options:

| Option                                                        | Description                              | Default |
| ------------------------------------------------------------- | ---------------------------------------- | ------- |
| `-p PATCH`, `--patch PATCH`, `-c PATCH`, `--changespec PATCH` | Target Patch (default: current checkout) | —       |
| `-h`, `--help`                                                | show this help message and exit          | —       |

Arguments:

| Argument | Description                   |
| -------- | ----------------------------- |
| `refs`   | Artifact references to detach |

## `sase patch restore`

```text
usage: sase patch restore [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH]
                          name [status]
```

Restore a Reverted Patch

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |
| `status` | status      |

## `sase patch revert`

```text
usage: sase patch revert [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH] name
```

Revert a Patch

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |

## `sase patch rewind`

```text
usage: sase patch rewind [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH] name entry
```

Rewind a Patch to a history entry

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |
| `entry`  | entry       |

## `sase patch reword`

```text
usage: sase patch reword [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH] name
```

Reword a Patch description from the request sidecar

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |

## `sase patch search`

```text
usage: sase patch search [-h] [-f {plain,rich,markdown}] query
```

Options:

| Option                         | Description                                                                                                                                                     | Default |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-f FORMAT`, `--format FORMAT` | Output format: 'plain' for simple text, 'rich' for styled panels, 'markdown' for agent-friendly markdown (default: rich) (choices: `markdown`, `plain`, `rich`) | `rich`  |
| `-h`, `--help`                 | show this help message and exit                                                                                                                                 | —       |

Arguments:

| Argument | Description                                                                                       |
| -------- | ------------------------------------------------------------------------------------------------- |
| `query`  | Query string for filtering Patches. Examples: '"feature" AND "Ready"', '+myproject', '!!! OR @@@' |

## `sase patch set-origin`

```text
usage: sase patch set-origin [-h] [-p PROJECT_FILE]
                             name {sase,external,unknown}
```

Deliberately set a Patch's PR_ORIGIN field. This is the manual half of the tri-state PR_ORIGIN decision: it resolves an 'unknown' record (or corrects a wrong mark) without waiting for the external_pr_mirror job.

Options:

| Option                                           | Description                                                               | Default |
| ------------------------------------------------ | ------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                           | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from current workspace) | —       |

Arguments:

| Argument | Description                 |
| -------- | --------------------------- |
| `name`   | NAME of the Patch to update |
| `origin` | New PR_ORIGIN value         |

## `sase patch status`

```text
usage: sase patch status [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH]
                         name status
```

Apply a Patch STATUS transition by name. Required identifiers are positional; optional project and operation sidecars use flags.

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description                            |
| -------- | -------------------------------------- |
| `name`   | Patch NAME to transition               |
| `status` | Target STATUS (WIP, Draft, Ready, ...) |

## `sase patch submit`

```text
usage: sase patch submit [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH] name
```

Submit a Patch

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |

## `sase patch sync`

```text
usage: sase patch sync [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH] name
```

Sync a Patch workspace from its VCS remote

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |

## `sase patch sync-deltas`

```text
usage: sase patch sync-deltas [-h] -P CL_NAME [-p PROJECT_FILE]
                              [-w WORKSPACE_DIR]
```

Options:

| Option                                                                                | Description                                                               | Default |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------- |
| `-P CL_NAME`, `--patch CL_NAME`, `-c CL_NAME`, `--cl CL_NAME`, `--changespec CL_NAME` | NAME of the Patch whose DELTAS should be recomputed (required)            | —       |
| `-h`, `--help`                                                                        | show this help message and exit                                           | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE`                                      | Path to the project .sase file (default: inferred from current workspace) | —       |
| `-w WORKSPACE_DIR`, `--workspace-dir WORKSPACE_DIR`                                   | VCS workspace directory to query (default: current directory)             | —       |

## `sase patch sync-external`

```text
usage: sase patch sync-external [-h] [-d] [-f] [-p PROJECT]
```

List pull requests on enabled project remotes and adopt PRs that were not created by SASE's tracked PR workflow. Merged and closed PRs are written directly into the archive ProjectSpec.

Options:

| Option                            | Description                                                                    | Default |
| --------------------------------- | ------------------------------------------------------------------------------ | ------- |
| `-d`, `--dry-run`                 | Show creations and repairs without writing Patches or advancing cursors        | `false` |
| `-f`, `--full`                    | Run an unbounded repair scan instead of the incremental fetch limit            | `false` |
| `-h`, `--help`                    | show this help message and exit                                                | —       |
| `-p PROJECT`, `--project PROJECT` | Project key, configured name, or alias to sync (default: all enabled projects) | —       |

## `sase patch tag`

```text
usage: sase patch tag [-h] [-p PROJECT_FILE] [-Q PATH] [-R PATH]
                      name tag [value]
```

Add a tag to a Patch description

Options:

| Option                                           | Description                                                                                                             | Default |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                                   | show this help message and exit                                                                                         | —       |
| `-p PROJECT_FILE`, `--project-file PROJECT_FILE` | Path to the project .sase file (default: inferred from the workspace)                                                   | —       |
| `-Q PATH`, `--request-path PATH`                 | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`                  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description |
| -------- | ----------- |
| `name`   | Patch NAME  |
| `tag`    | tag         |
| `value`  | value       |

Related: [CLI command groups](index.md).

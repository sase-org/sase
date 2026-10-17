---
title: "sase project"
description: "Inspect project lifecycle state and the current project."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase project

Inspect and mutate project lifecycle state

Reference for `sase project`. Run `sase project --help` for the exact output on this checkout.

```text
usage: sase project [-h]
                    {add,alias,create,current,disable,enable,list,set-current,set-state,show,suggest} ...
```

Inspect project lifecycle state and the current project. Running `sase project` defaults to `sase project list`.

Bare `sase project` defaults to `sase project list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                 | Summary                                                      |
| -------------------------- | ------------------------------------------------------------ |
| `sase project add`         | Register an existing repository as a SASE project            |
| `sase project alias`       | Inspect and mutate project aliases                           |
| `sase project create`      | Create a repository and register it as a SASE project        |
| `sase project current`     | Show the current project derived from the VCS macro MRU      |
| `sase project disable`     | Disable a project                                            |
| `sase project enable`      | Enable a project                                             |
| `sase project list`        | List SASE projects by lifecycle state                        |
| `sase project set-current` | Set the current project by promoting it in the VCS macro MRU |
| `sase project set-state`   | Set a project's lifecycle state                              |
| `sase project show`        | Show one project's lifecycle record                          |
| `sase project suggest`     | Rank repositories worth adding as projects                   |

## `sase project add`

```text
usage: sase project add [-h] REF [-a ALIAS] [-c] [-j] [-m] [-n NAME] [-S]
                        [-Q PATH] [-R PATH] [-s] [-y]
```

Register an existing repository as an enabled SASE project. New projects are enabled by default. Use --check to preview without writes. Setup can write the repository's sase/sase.yml, commit it, and push the default branch; agents may preview freely, while explicit setup is human-only. Interrupted operations can be resumed by repeating the same command. Successful setup may hand off to `sase init`.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a ALIAS`, `--alias ALIAS`      | Add a project alias (repeatable)                                                                                        | —       |
| `-c`, `--check`                  | Show the read-only plan without applying it                                                                             | `false` |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                   | Emit a plan document or NDJSON apply events                                                                             | `false` |
| `-m`, `--make-current`           | Make the registered project current                                                                                     | `false` |
| `-n NAME`, `--name NAME`         | Set the project display name                                                                                            | —       |
| `-S`, `--no-setup`               | Register without the remote management commit and push                                                                  | `false` |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |
| `-s`, `--setup`                  | Request SASE management setup (human-only commit and push)                                                              | `false` |
| `-y`, `--yes`                    | Apply without a confirmation prompt                                                                                     | `false` |

Arguments:

| Argument | Description                   |
| -------- | ----------------------------- |
| `ref`    | Existing repository reference |

## `sase project alias`

```text
usage: sase project alias [-h] {add,clear,list,remove} ...
```

Bare `sase project alias` defaults to `sase project alias list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                  | Summary                           |
| --------------------------- | --------------------------------- |
| `sase project alias add`    | Add an alias to a project         |
| `sase project alias clear`  | Remove all aliases from a project |
| `sase project alias list`   | List project aliases              |
| `sase project alias remove` | Remove an alias from a project    |

### `sase project alias add`

```text
usage: sase project alias add [-h] project alias
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument  | Description  |
| --------- | ------------ |
| `project` | Project name |
| `alias`   | Alias name   |

### `sase project alias clear`

```text
usage: sase project alias clear [-h] project
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument  | Description  |
| --------- | ------------ |
| `project` | Project name |

### `sase project alias list`

```text
usage: sase project alias list [-h] [project] [-j]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

Arguments:

| Argument  | Description                      |
| --------- | -------------------------------- |
| `project` | Optional project name to inspect |

### `sase project alias remove`

```text
usage: sase project alias remove [-h] project alias
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument  | Description  |
| --------- | ------------ |
| `project` | Project name |
| `alias`   | Alias name   |

## `sase project create`

```text
usage: sase project create [-h] REF [-a ALIAS] [-c] [-d TEXT] [-j] [-m]
                           [-n NAME] [-S] [-O KEY=VALUE] [-Q PATH] [-R PATH]
                           [-s] [-v VISIBILITY] [-y]
```

Create a remote or bare repository and register it as an enabled SASE project. REF is gh:OWNER/NAME, OWNER/NAME, or git:NAME. Provider options are validated before any create subprocess. --check is read-only and available to agents; apply is human-only unless it runs as an approved /sase_gate option or SASE_PROJECT_CREATE_BYPASS holds a reason. Interrupted operations resume by repeating the same command. Successful setup may hand off to `sase init`.

Options:

| Option                                     | Description                                                                                                             | Default |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a ALIAS`, `--alias ALIAS`                | Add a project alias (repeatable)                                                                                        | —       |
| `-c`, `--check`                            | Show the read-only plan without applying it                                                                             | `false` |
| `-d TEXT`, `--description TEXT`            | Repository description (sugar for --option description=TEXT)                                                            | —       |
| `-h`, `--help`                             | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                             | Emit a plan document or NDJSON apply events                                                                             | `false` |
| `-m`, `--make-current`                     | Make the registered project current                                                                                     | `false` |
| `-n NAME`, `--name NAME`                   | Set the project display name                                                                                            | —       |
| `-S`, `--no-setup`                         | Register without the remote management commit and push                                                                  | `false` |
| `-O KEY=VALUE`, `--option KEY=VALUE`       | Provider creation option (repeatable; validated strictly)                                                               | —       |
| `-Q PATH`, `--request-path PATH`           | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`            | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |
| `-s`, `--setup`                            | Request SASE management setup (human-only commit and push)                                                              | `false` |
| `-v VISIBILITY`, `--visibility VISIBILITY` | Repository visibility (sugar for --option visibility=VISIBILITY)                                                        | —       |
| `-y`, `--yes`                              | Apply without a confirmation prompt                                                                                     | `false` |

Arguments:

| Argument | Description                                                   |
| -------- | ------------------------------------------------------------- |
| `ref`    | Repository to create (gh:OWNER/NAME, OWNER/NAME, or git:NAME) |

## `sase project current`

```text
usage: sase project current [-h] [-j]
```

Print the current project: the first VCS macro MRU entry that resolves to an enabled SASE project. The current project is a pure read of the VCS macro MRU store (~/.sase/vcs_macro_mru.json). Launch an agent on a project, or on a Patch owned by that project, to make it current. `sase project set-current` performs the same MRU promotion without a launch, and the Projects tab in sase's TUI binds that operation. Human output colors the project name with that project's accent and reports the canonical directory key, the origin (project or patch, naming the Patch when applicable), and the MRU ref that produced it. When nothing resolves, the command explains how to set a current project and exits 0.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

## `sase project disable`

```text
usage: sase project disable [-h] project [-f]
```

Options:

| Option          | Description                                        | Default |
| --------------- | -------------------------------------------------- | ------- |
| `-f`, `--force` | Allow disabling a project that still has live work | `false` |
| `-h`, `--help`  | show this help message and exit                    | —       |

Arguments:

| Argument  | Description  |
| --------- | ------------ |
| `project` | Project name |

## `sase project enable`

```text
usage: sase project enable [-h] project [-f]
```

Options:

| Option          | Description                                        | Default |
| --------------- | -------------------------------------------------- | ------- |
| `-f`, `--force` | Allow disabling a project that still has live work | `false` |
| `-h`, `--help`  | show this help message and exit                    | —       |

Arguments:

| Argument  | Description  |
| --------- | ------------ |
| `project` | Project name |

## `sase project list`

```text
usage: sase project list [-h] [-s {enabled,disabled,sibling,all}] [-j]
```

Options:

| Option                                                                        | Description                                   | Default   |
| ----------------------------------------------------------------------------- | --------------------------------------------- | --------- |
| `-h`, `--help`                                                                | show this help message and exit               | —         |
| `-j`, `--json`                                                                | Emit machine-readable JSON                    | `false`   |
| `-s {enabled,disabled,sibling,all}`, `--state {enabled,disabled,sibling,all}` | Lifecycle state to include (default: enabled) | `enabled` |

## `sase project set-current`

```text
usage: sase project set-current [-h] project [-j]
```

Make PROJECT the current project by promoting it to the head of the VCS macro MRU store (~/.sase/vcs_macro_mru.json). This is the same write a launch on that project performs. The project must be enabled and launchable. The Projects tab in sase's TUI binds the same operation. Human output prints a one-line result, then the same project detail as `sase project current`. --json emits status, message, and the project payload (or null). Exits 0 when the project is current (set or already current) and 1 when it is not.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

Arguments:

| Argument  | Description                           |
| --------- | ------------------------------------- |
| `project` | Project name, alias, or directory key |

## `sase project set-state`

```text
usage: sase project set-state [-h] project {enabled,disabled,sibling} [-f]
```

Options:

| Option          | Description                                        | Default |
| --------------- | -------------------------------------------------- | ------- |
| `-f`, `--force` | Allow disabling a project that still has live work | `false` |
| `-h`, `--help`  | show this help message and exit                    | —       |

Arguments:

| Argument  | Description            |
| --------- | ---------------------- |
| `project` | Project name           |
| `state`   | Target lifecycle state |

## `sase project show`

```text
usage: sase project show [-h] project [-j]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

Arguments:

| Argument  | Description  |
| --------- | ------------ |
| `project` | Project name |

## `sase project suggest`

```text
usage: sase project suggest [-h] [provider] [-a] [-j] [-o OWNER] [-r]
```

Rank repositories worth adding as SASE projects, grouped as RESUME, ON THIS MACHINE, SUGGESTED, LINKED TO YOUR PROJECTS, and DISABLED PROJECTS. Discovery is cache-first per owner and read-only: nothing is cloned, created, or registered. Human output prints one grouped section per workspace provider with a health line, owner errors with their remedy, a hidden row footer, and a closing `sase project add REF` hint. --json emits the machine-readable candidate document.

Options:

| Option                      | Description                                               | Default |
| --------------------------- | --------------------------------------------------------- | ------- |
| `-a`, `--all`               | Include hidden rows (sidecars, forks, archived, projects) | `false` |
| `-h`, `--help`              | show this help message and exit                           | —       |
| `-j`, `--json`              | Emit machine-readable JSON                                | `false` |
| `-o OWNER`, `--owner OWNER` | Restrict discovery to the named owner (repeatable)        | —       |
| `-r`, `--refresh`           | Bypass the cached repository lists                        | `false` |

Arguments:

| Argument   | Description                                                |
| ---------- | ---------------------------------------------------------- |
| `provider` | Workspace provider workflow type (default: every provider) |

Related: [CLI command groups](index.md).

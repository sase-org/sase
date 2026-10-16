---
title: "sase repo"
description: "Initialize, inspect, and resolve repositories known by SASE."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase repo

Initialize, inspect, resolve, and open repositories

Reference for `sase repo`. Run `sase repo --help` for the exact output on this checkout.

```text
usage: sase repo [-h] {init,list,log,open,path} ...
```

Initialize, inspect, and resolve repositories known by SASE. Running `sase repo` defaults to `sase repo list`.

Bare `sase repo` defaults to `sase repo list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand       | Summary                                                      |
| ---------------- | ------------------------------------------------------------ |
| `sase repo init` | Initialize configured sidecars and project repository wiring |
| `sase repo list` | List repositories and their per-workspace clone status       |
| `sase repo log`  | Inspect the repository-open audit log                        |
| `sase repo open` | Open a repo checkout without cleaning it; print its path     |
| `sase repo path` | Print a primary or sidecar repository path                   |

## `sase repo init`

```text
usage: sase repo init [-h] [-c] [-d] [-C]
```

Declare the managed plans sidecar, initialize every enabled configured sidecar, and add the tracked /sase/repos/ ignore rule. Creating a missing provider repository always requires an interactive, default-no y/yes confirmation.

Options:

| Option              | Description                                                         | Default |
| ------------------- | ------------------------------------------------------------------- | ------- |
| `-c`, `--check`     | Report sidecar, config, and ignore-rule work without writing files  | `false` |
| `-d`, `--diff`      | Show full file diffs for planned repository changes                 | `false` |
| `-h`, `--help`      | show this help message and exit                                     | —       |
| `-C`, `--no-commit` | Write project config and ignore rules without committing or pushing | `false` |

## `sase repo list`

```text
usage: sase repo list [-h] [-a] [-j] [-p PROJECT] [-w N]
```

List primary, sidecar, linked, and opened external repositories for the current project and show where they are cloned. The project and workspace default to the checkout that contains the current directory.

Options:

| Option                            | Description                                               | Default |
| --------------------------------- | --------------------------------------------------------- | ------- |
| `-a`, `--all`                     | List repos across all enabled and disabled projects       | `false` |
| `-h`, `--help`                    | show this help message and exit                           | —       |
| `-j`, `--json`                    | Emit a machine-readable JSON object                       | `false` |
| `-p PROJECT`, `--project PROJECT` | Project to query (default: infer from current directory)  | —       |
| `-w N`, `--workspace N`           | Workspace context (default: infer from current directory) | —       |

## `sase repo log`

```text
usage: sase repo log [-h] [-a AGENT_NAME] [-i OPEN_ID] [-j] [-p PROJECT]
                     [-r REPO] [-w N]
```

Summarize successful repository opens for one project. Add a repository, agent, or workspace filter to show matching agents and individual events; use an event ID prefix for full detail. The project defaults to the checkout that contains the current directory.

Options:

| Option                                | Description                                              | Default |
| ------------------------------------- | -------------------------------------------------------- | ------- |
| `-a AGENT_NAME`, `--agent AGENT_NAME` | Show opens attributed to this agent or interactive user  | —       |
| `-h`, `--help`                        | show this help message and exit                          | —       |
| `-i OPEN_ID`, `--id OPEN_ID`          | Show one event by exact ID or unambiguous ID prefix      | —       |
| `-j`, `--json`                        | Emit a deterministic machine-readable JSON object        | `false` |
| `-p PROJECT`, `--project PROJECT`     | Project to query (default: infer from current directory) | —       |
| `-r REPO`, `--repo REPO`              | Show opens for this repository name                      | —       |
| `-w N`, `--workspace N`               | Show opens in this workspace number                      | —       |

## `sase repo open`

```text
usage: sase repo open [-h] [-p PROJECT] -r REASON [-w N] REPO
```

Resolve a repository in three tiers: a primary, sidecar, or linked repository in the host project; another registered SASE project; or an external provider ref such as gh:owner/repo (owner/repo is GitHub shorthand). Provider refs and registered projects that match a configured linked repo open that linked checkout and explain the redirect on stderr. Materialize the selected checkout in one workspace context without cleaning, resetting, or synchronizing an existing checkout, then print only the opened path. The workspace defaults to the checkout that contains the current directory.

Options:

| Option                            | Description                                                   | Default |
| --------------------------------- | ------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                               | —       |
| `-p PROJECT`, `--project PROJECT` | Host project (default: infer from current directory)          | —       |
| `-r REASON`, `--reason REASON`    | Non-empty reason for the audited repository open (required)   | —       |
| `-w N`, `--workspace N`           | Host workspace number (default: infer from current directory) | —       |

Arguments:

| Argument | Description                                                                     |
| -------- | ------------------------------------------------------------------------------- |
| `repo`   | Inventory name, registered project name, gh:owner/repo, or owner/repo shorthand |

## `sase repo path`

```text
usage: sase repo path [-h] [-e] [-p PROJECT] [-w N] REPO
```

Resolve a primary or sidecar repository by role name or repository slug and print exactly one absolute path. Resolution is read-only unless --ensure is passed. Linked and external repositories must be prepared with `sase repo open` instead.

Options:

| Option                            | Description                                               | Default |
| --------------------------------- | --------------------------------------------------------- | ------- |
| `-e`, `--ensure`                  | Materialize and synchronize the backing sidecar clone     | `false` |
| `-h`, `--help`                    | show this help message and exit                           | —       |
| `-p PROJECT`, `--project PROJECT` | Project to query (default: infer from current directory)  | —       |
| `-w N`, `--workspace N`           | Workspace context (default: infer from current directory) | —       |

Arguments:

| Argument | Description                                                 |
| -------- | ----------------------------------------------------------- |
| `repo`   | Primary name, sidecar role name, or sidecar repository slug |

Related: [CLI command groups](index.md).

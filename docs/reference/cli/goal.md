---
title: "sase goal"
description: "Create, list, show, edit, drop, reopen, merge, and check durable goal records."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase goal

Create, list, and reshape durable goal records

Reference for `sase goal`. Run `sase goal --help` for the exact output on this checkout.

```text
usage: sase goal [-h] {doctor,drop,edit,list,merge,new,reopen,show} ...
```

Create, list, show, edit, drop, reopen, merge, and check durable goal records. With no subcommand, `sase goal` defaults to `sase goal list`. `new`, `edit`, `drop`, `reopen`, `merge`, and `doctor --repair` are human verbs: they refuse inside agent runs. Agents may run `sase goal list` and `sase goal show`.

Bare `sase goal` defaults to `sase goal list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand         | Summary                                             |
| ------------------ | --------------------------------------------------- |
| `sase goal doctor` | Check the goal ledger, optionally repairing markers |
| `sase goal drop`   | Settle a goal as canceled                           |
| `sase goal edit`   | Edit a goal's content                               |
| `sase goal list`   | List goals (defaults to unsettled)                  |
| `sase goal merge`  | Merge one goal into another                         |
| `sase goal new`    | Create a goal                                       |
| `sase goal reopen` | Reopen a settled goal                               |
| `sase goal show`   | Show one goal card                                  |

## `sase goal doctor`

```text
usage: sase goal doctor [-h] [-j] [-r]
```

Options:

| Option           | Description                                            | Default |
| ---------------- | ------------------------------------------------------ | ------- |
| `-h`, `--help`   | show this help message and exit                        | —       |
| `-j`, `--json`   | Print the doctor report                                | `false` |
| `-r`, `--repair` | Repair markers and rebuild the projection (human only) | `false` |

## `sase goal drop`

```text
usage: sase goal drop [-h] ID -w WHY
```

Options:

| Option                | Description                        | Default |
| --------------------- | ---------------------------------- | ------- |
| `-h`, `--help`        | show this help message and exit    | —       |
| `-w WHY`, `--why WHY` | Why the goal is dropped (required) | —       |

Arguments:

| Argument  | Description    |
| --------- | -------------- |
| `goal_id` | Goal id or ref |

## `sase goal edit`

```text
usage: sase goal edit [-h] ID [-c CRITERION] [-o OUTCOME] [-t TITLE]
                      [-x REMOVE_CRITERION]
```

Options:

| Option                                                       | Description                                                            | Default |
| ------------------------------------------------------------ | ---------------------------------------------------------------------- | ------- |
| `-c CRITERION`, `--criterion CRITERION`                      | Add an acceptance criterion (repeatable)                               | —       |
| `-h`, `--help`                                               | show this help message and exit                                        | —       |
| `-o OUTCOME`, `--outcome OUTCOME`                            | Replacement outcome                                                    | —       |
| `-x REMOVE_CRITERION`, `--remove-criterion REMOVE_CRITERION` | Remove a criterion by number as shown by `sase goal show` (repeatable) | —       |
| `-t TITLE`, `--title TITLE`                                  | Replacement title                                                      | —       |

Arguments:

| Argument  | Description    |
| --------- | -------------- |
| `goal_id` | Goal id or ref |

## `sase goal list`

```text
usage: sase goal list [-h] [-a] [-f] [-j] [-n LIMIT]
                      [-s {active,all,done,dropped,review,settled,unsettled}]
```

Options:

| Option                         | Description                                                                                                                                                                    | Default     |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------- |
| `-a`, `--all-projects`         | Render one section per enabled project                                                                                                                                         | `false`     |
| `-f`, `--fresh`                | Integrate synchronously before reading                                                                                                                                         | `false`     |
| `-h`, `--help`                 | show this help message and exit                                                                                                                                                | —           |
| `-j`, `--json`                 | Print GoalListWire JSON                                                                                                                                                        | `false`     |
| `-n LIMIT`, `--limit LIMIT`    | Maximum goals shown                                                                                                                                                            | —           |
| `-s STATUS`, `--status STATUS` | Status filter (default: unsettled). done, dropped, settled, and all scan history, newest first (choices: `active`, `all`, `done`, `dropped`, `review`, `settled`, `unsettled`) | `unsettled` |

## `sase goal merge`

```text
usage: sase goal merge [-h] ID -i INTO [-w WHY]
```

Options:

| Option                   | Description                      | Default |
| ------------------------ | -------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit  | —       |
| `-i INTO`, `--into INTO` | Target goal id or ref (required) | —       |
| `-w WHY`, `--why WHY`    | Why the goals merge              | —       |

Arguments:

| Argument  | Description           |
| --------- | --------------------- |
| `goal_id` | Source goal id or ref |

## `sase goal new`

```text
usage: sase goal new [-h] -o OUTCOME -t TITLE [-c CRITERION]
```

Options:

| Option                                  | Description                       | Default |
| --------------------------------------- | --------------------------------- | ------- |
| `-c CRITERION`, `--criterion CRITERION` | Acceptance criterion (repeatable) | —       |
| `-h`, `--help`                          | show this help message and exit   | —       |
| `-o OUTCOME`, `--outcome OUTCOME`       | Goal outcome (required)           | —       |
| `-t TITLE`, `--title TITLE`             | Goal title (required)             | —       |

## `sase goal reopen`

```text
usage: sase goal reopen [-h] ID -m MESSAGE
```

Options:

| Option                            | Description                     | Default |
| --------------------------------- | ------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit | —       |
| `-m MESSAGE`, `--message MESSAGE` | Why the goal reopens (required) | —       |

Arguments:

| Argument  | Description    |
| --------- | -------------- |
| `goal_id` | Goal id or ref |

## `sase goal show`

```text
usage: sase goal show [-h] ID [-j]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Print GoalStateWire JSON        | `false` |

Arguments:

| Argument  | Description    |
| --------- | -------------- |
| `goal_id` | Goal id or ref |

Related: [CLI command groups](index.md).

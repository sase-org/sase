---
title: "sase autonomy"
description: "Inspect the core-owned %auto autonomy record: predict each gate decision exactly (`explain`), list the built-in profiles (`list`), read the host decision log…"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase autonomy

Predict and inspect %auto gate decisions

Reference for `sase autonomy`. Run `sase autonomy --help` for the exact output on this checkout.

```text
usage: sase autonomy [-h] {explain,list,log,show} ...
```

Inspect the core-owned %auto autonomy record: predict each gate decision exactly (`explain`), list the built-in profiles (`list`), read the host decision log (`log`), and show one profile's matrix (`show`). With no subcommand, `sase autonomy` defaults to `sase autonomy list`.

Bare `sase autonomy` defaults to `sase autonomy list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand              | Summary                                                   |
| ----------------------- | --------------------------------------------------------- |
| `sase autonomy explain` | Predict each %auto decision for an agent, prompt, or gate |
| `sase autonomy list`    | List the built-in autonomy profiles                       |
| `sase autonomy log`     | Read the host %auto decision log, newest first            |
| `sase autonomy show`    | Show one autonomy profile's matrix                        |

## `sase autonomy explain`

```text
usage: sase autonomy explain [-h] [-g ID] [-j] [-p TEXT] [AGENT]
```

Predict each %auto decision exactly. With an agent name, show its live record's summary, the per-kind cells with rule and source, the decisions so far from the host log, and the coverage line. With --prompt, dry-run a prompt's %auto through the side-effect-free scan: $(...) is never executed and is labeled as unexpanded. With --gate, show the settled gate's deciding policy block, which is the revision that decided it.

Options:

| Option                     | Description                                                                                     | Default |
| -------------------------- | ----------------------------------------------------------------------------------------------- | ------- |
| `-g ID`, `--gate ID`       | Gate as KIND/REQUEST_ID, or a gate-turn reference (short id, member name, or owning agent name) | —       |
| `-h`, `--help`             | show this help message and exit                                                                 | —       |
| `-j`, `--json`             | Emit machine-readable JSON                                                                      | `false` |
| `-p TEXT`, `--prompt TEXT` | Dry-run this prompt's %auto without executing anything                                          | —       |

Arguments:

| Argument | Description                                                   |
| -------- | ------------------------------------------------------------- |
| `agent`  | Agent name, resolved the way `sase agent show` resolves names |

## `sase autonomy list`

```text
usage: sase autonomy list [-h] [-j]
```

List the built-in autonomy profiles with their one-liners. `standard` is the default profile.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

## `sase autonomy log`

```text
usage: sase autonomy log [-h] [-j] [-k KIND] [-o OUTCOME] [-s DATE] [AGENT]
```

Read the host %auto decision log, newest first, rendered with the core decision sentence. Only non-manual evaluations are logged: manual agents leave no rows.

Options:

| Option                            | Description                                                                                | Default |
| --------------------------------- | ------------------------------------------------------------------------------------------ | ------- |
| `-h`, `--help`                    | show this help message and exit                                                            | —       |
| `-j`, `--json`                    | Emit machine-readable JSON                                                                 | `false` |
| `-k KIND`, `--kind KIND`          | Only this gate kind (plan, epic_plan, question) (choices: `epic_plan`, `plan`, `question`) | —       |
| `-o OUTCOME`, `--outcome OUTCOME` | Only this outcome (auto, ask) (choices: `ask`, `auto`)                                     | —       |
| `-s DATE`, `--since DATE`         | Only decisions at/after DATE                                                               | —       |

Arguments:

| Argument | Description                          |
| -------- | ------------------------------------ |
| `agent`  | Only decisions created by this agent |

## `sase autonomy show`

```text
usage: sase autonomy show [-h] [-j] PROFILE
```

Show one built-in profile's matrix: its layer, the selections that pick it, the per-kind cells, and the coverage line.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

Arguments:

| Argument  | Description                                       |
| --------- | ------------------------------------------------- |
| `profile` | Profile to inspect (epic, manual, standard, tale) |

Related: [CLI command groups](index.md).

---
title: "sase var"
description: "Inspect historical output variables, retrieve a snapshot or selector values, or set variables on the current SASE agent run."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase var

Inspect and set SASE agent output variables

Reference for `sase var`. Run `sase var --help` for the exact output on this checkout.

```text
usage: sase var [-h] <subcommand> ...
```

Inspect historical output variables, retrieve a snapshot or selector values, or set variables on the current SASE agent run. With no subcommand, `sase var` defaults to `sase var list`.

Bare `sase var` defaults to `sase var list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand      | Summary                                               |
| --------------- | ----------------------------------------------------- |
| `sase var get`  | Get a snapshot or selector values                     |
| `sase var list` | List unique output-variable keys across agent history |
| `sase var set`  | Set output variables for the current SASE agent       |

## `sase var get`

```text
usage: sase var get [-h] [-c {auto,always,never}] [-f {pretty,raw,json,jsonl}]
                    [-H] [-n N] [-p PROJECT]
                    [TARGET ...]
```

Read one output-variable snapshot or retrieve precise values by selector. With no target, read the current agent's artifact directory directly so the newest writes are visible. This form requires SASE_ARTIFACTS_DIR. With exactly one quoted <agent_name>, show the newest exact-name historical snapshot. Quote the wrapper so the shell keeps it intact, for example `sase var get '<build>' --format json`. Project filters narrow the candidate history; --hidden includes hidden agents. Exact names are preserved, including dotted, hyphenated, and digit-leading names. With one or more ordinary selectors, use the compact selector language. Unscoped keys choose the newest matching occurrence. Exact-agent selectors choose that name's newest artifact. Global (`*.KEY`) and hood (`HOOD.*.KEY`) selectors collapse repeated runs to the newest value per agent name. JSON paths use [INDEX] or ["KEY"] after the selected value; dotted map traversal is not accepted. Snapshot mode supports --format pretty|json. Selector mode also supports raw and jsonl. --limit applies only to selector wildcard expansion.

Options:

| Option                            | Description                                                                                                                                          | Default  |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `-c COLOR`, `--color COLOR`       | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                                            | `auto`   |
| `-f FORMAT`, `--format FORMAT`    | Output format: pretty or json for snapshots; pretty, raw, json, or jsonl for selectors (default: pretty) (choices: `json`, `jsonl`, `pretty`, `raw`) | `pretty` |
| `-h`, `--help`                    | show this help message and exit                                                                                                                      | —        |
| `-H`, `--hidden`                  | Include hidden indexed agents for named snapshots and selectors (visible history is the default)                                                     | `false`  |
| `-n N`, `--limit N`               | Maximum matches from selector wildcard expansion; 0 means unlimited (default: 20). Not valid with a snapshot                                         | `20`     |
| `-p PROJECT`, `--project PROJECT` | Filter named snapshots and selectors by project display name or alias (repeatable)                                                                   | —        |

Arguments:

| Argument  | Description                                                                                                                                        |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `targets` | Omit for the current snapshot, quote '<agent_name>' for a named snapshot, or pass a selector such as status, build.status, *.status, or results[0] |

## `sase var list`

```text
usage: sase var list [-h] [-a GLOB] [-c {auto,always,never}]
                     [-f {pretty,json,jsonl}] [-H] [-k GLOB]
                     [-n KEYS[:VALUES]] [-p PROJECT] [-r] [-s DATE] [-u DATE]
                     [-v TEXT | -V JSON]
```

List unique variable keys from indexed agent history, most recently seen first. Under each key, list distinct typed values and the agent names that contributed them. Repeated filters in one dimension are ORed; different dimensions are ANDed. Bare `sase var` defaults to this command.

Options:

| Option                                      | Description                                                                                  | Default  |
| ------------------------------------------- | -------------------------------------------------------------------------------------------- | -------- |
| `-a GLOB`, `--agent GLOB`                   | Filter by agent-name glob; hood.* includes the hood root (repeatable)                        | —        |
| `-c COLOR`, `--color COLOR`                 | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)    | `auto`   |
| `-f FORMAT`, `--format FORMAT`              | Output format: pretty, json, or jsonl (default: pretty) (choices: `json`, `jsonl`, `pretty`) | `pretty` |
| `-h`, `--help`                              | show this help message and exit                                                              | —        |
| `-H`, `--hidden`                            | Include hidden indexed agents (visible history is the default)                               | `false`  |
| `-k GLOB`, `--key GLOB`                     | Filter by case-sensitive variable-key glob (repeatable)                                      | —        |
| `-n KEYS[:VALUES]`, `--limit KEYS[:VALUES]` | Maximum keys and distinct values per key; 0 means unlimited (default: 20:5)                  | `20, 5`  |
| `-p PROJECT`, `--project PROJECT`           | Filter by project display name or alias (repeatable)                                         | —        |
| `-r`, `--reverse`                           | Invert the normal recent-first key and value order                                           | `false`  |
| `-s DATE`, `--since DATE`                   | Only variables from agents launched at/after DATE                                            | —        |
| `-u DATE`, `--until DATE`                   | Only variables from agents launched at/before DATE                                           | —        |
| `-v TEXT`, `--value TEXT`                   | Case-insensitive substring match over scalar text and canonical JSON (repeatable)            | —        |
| `-V JSON`, `--value-json JSON`              | Exact typed JSON value match after output-variable normalization (repeatable)                | —        |

## `sase var set`

```text
usage: sase var set [-h] [-j] [-v TEXT | -f PATH]
                    KEY[=VALUE] [KEY[=VALUE] ...]
```

Set one or more output variables with KEY=VALUE assignments, or set one bare KEY from --value or --value-file.

Options:

| Option                         | Description                                                    | Default |
| ------------------------------ | -------------------------------------------------------------- | ------- |
| `-h`, `--help`                 | show this help message and exit                                | —       |
| `-j`, `--json`                 | Parse supplied values as JSON instead of text                  | `false` |
| `-v TEXT`, `--value TEXT`      | Use TEXT as the value verbatim without splitting on whitespace | —       |
| `-f PATH`, `--value-file PATH` | Read the value as UTF-8 text from PATH; use - for stdin        | —       |

Arguments:

| Argument      | Description                                                        |
| ------------- | ------------------------------------------------------------------ |
| `assignments` | KEY=VALUE assignment, or one bare KEY with --value or --value-file |

Related: [CLI command groups](index.md).

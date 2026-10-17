---
title: "sase snippet"
description: "Inspect or update the effective snippet catalog for a project."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase snippet

Add, delete, list, and show SASE snippets

Reference for `sase snippet`. Run `sase snippet --help` for the exact output on this checkout.

```text
usage: sase snippet [-h] [-p REF] {add,delete,list,show} ...
```

Inspect or update the effective snippet catalog for a project. Macro-derived entries are viewable; writable `ace.snippets` definitions can be added or deleted. Running `sase snippet` defaults to `sase snippet list`.

Bare `sase snippet` defaults to `sase snippet list`.

Options:

| Option                    | Description                                              | Default |
| ------------------------- | -------------------------------------------------------- | ------- |
| `-h`, `--help`            | show this help message and exit                          | —       |
| `-p REF`, `--project REF` | Project to query (default: infer from current directory) | —       |

Subcommands:

| Subcommand            | Summary                                     |
| --------------------- | ------------------------------------------- |
| `sase snippet add`    | Add a writable config snippet               |
| `sase snippet delete` | Delete a writable config snippet            |
| `sase snippet list`   | List effective snippets for a project       |
| `sase snippet show`   | Show one snippet's definition and relations |

## `sase snippet add`

```text
usage: sase snippet add [-h] TRIGGER TEMPLATE [-n] [-F] [-f {json,rich}]
                        [-p REF] [-t PATH]
```

Insert TRIGGER with TEMPLATE into the resolved `ace.snippet_config_path` (or `-t/--target`). Refuses to overwrite or shadow an existing definition unless `-F/--force` is given, and names the source that currently wins. `-n/--dry-run` validates and plans the write without touching the destination.

Options:

| Option                         | Description                                              | Default |
| ------------------------------ | -------------------------------------------------------- | ------- |
| `-n`, `--dry-run`              | Print the outcome without writing                        | `false` |
| `-F`, `--force`                | Overwrite or shadow an existing snippet                  | `false` |
| `-f FORMAT`, `--format FORMAT` | Output format (default: rich) (choices: `json`, `rich`)  | `rich`  |
| `-h`, `--help`                 | show this help message and exit                          | —       |
| `-p REF`, `--project REF`      | Project to query (default: infer from current directory) | —       |
| `-t PATH`, `--target PATH`     | Writable YAML destination (default: configured path)     | —       |

Arguments:

| Argument   | Description                                     |
| ---------- | ----------------------------------------------- |
| `trigger`  | Nonblank alphanumeric/underscore trigger to add |
| `template` | Nonblank snippet template body                  |

## `sase snippet delete`

```text
usage: sase snippet delete [-h] TRIGGER [-a] [-n] [-f {json,rich}] [-p REF]
```

Remove the winning writable `ace.snippets` contribution for TRIGGER after exact, alias, then unique-prefix lookup. Refuses to pretend a read-only, plugin, or macro-derived entry was deleted and points at its source instead. Prints the restore command and any newly revealed definition. `-a/--all` removes every writable config-layer contribution.

Options:

| Option                         | Description                                              | Default |
| ------------------------------ | -------------------------------------------------------- | ------- |
| `-a`, `--all`                  | Remove every writable config-layer contribution          | `false` |
| `-n`, `--dry-run`              | Print the outcome without writing                        | `false` |
| `-f FORMAT`, `--format FORMAT` | Output format (default: rich) (choices: `json`, `rich`)  | `rich`  |
| `-h`, `--help`                 | show this help message and exit                          | —       |
| `-p REF`, `--project REF`      | Project to query (default: infer from current directory) | —       |

Arguments:

| Argument  | Description                                |
| --------- | ------------------------------------------ |
| `trigger` | Trigger, alias, or unique prefix to delete |

## `sase snippet list`

```text
usage: sase snippet list [-h] [PATTERN] [-d] [-f {json,names,table}] [-p REF]
```

List each effective explicit trigger once, optionally filtered by a case-insensitive substring match against triggers and generated aliases. `-d/--definitions` extends matching into raw and composed bodies. Generated aliases are metadata, not extra rows.

Options:

| Option                         | Description                                                        | Default |
| ------------------------------ | ------------------------------------------------------------------ | ------- |
| `-d`, `--definitions`          | Extend PATTERN matching into snippet bodies                        | `false` |
| `-f FORMAT`, `--format FORMAT` | Output format (default: table) (choices: `json`, `names`, `table`) | `table` |
| `-h`, `--help`                 | show this help message and exit                                    | —       |
| `-p REF`, `--project REF`      | Project to query (default: infer from current directory)           | —       |

Arguments:

| Argument  | Description                                     |
| --------- | ----------------------------------------------- |
| `pattern` | Case-insensitive substring filter over triggers |

## `sase snippet show`

```text
usage: sase snippet show [-h] TRIGGER [-f {json,markdown,rich}] [-p REF]
```

Resolve TRIGGER through exact, alias, then unique-prefix lookup and print the raw template, composed expansion, source stack, aliases, calls, backlinks, and diagnostics. Macro-derived entries are viewable and linkable but are source-edited.

Options:

| Option                         | Description                                                         | Default |
| ------------------------------ | ------------------------------------------------------------------- | ------- |
| `-f FORMAT`, `--format FORMAT` | Output format (default: rich) (choices: `json`, `markdown`, `rich`) | `rich`  |
| `-h`, `--help`                 | show this help message and exit                                     | —       |
| `-p REF`, `--project REF`      | Project to query (default: infer from current directory)            | —       |

Arguments:

| Argument  | Description                              |
| --------- | ---------------------------------------- |
| `trigger` | Trigger, alias, or unique prefix to show |

Related: [CLI command groups](index.md).

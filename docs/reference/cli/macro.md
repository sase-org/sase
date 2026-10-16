---
title: "sase macro"
description: "Expand and visualize macro workflows"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase macro

Expand and visualize macro workflows

Reference for `sase macro`. Run `sase macro --help` for the exact output on this checkout.

```text
usage: sase macro [-h] {catalog,expand,explain,graph,list,show,types} ...
```

Bare `sase macro` defaults to `sase macro list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                                                   |
| -------------------- | --------------------------------------------------------- |
| `sase macro catalog` | Render every visible macro to a beautifully-formatted PDF |
| `sase macro expand`  | Expand sase references (snippets, file refs) in a prompt  |
| `sase macro explain` | Dry-run: show execution plan without running anything     |
| `sase macro graph`   | Generate a DAG visualization of a workflow                |
| `sase macro list`    | List all available macros and workflows as JSON           |
| `sase macro show`    | Show one macro definition with syntax highlighting        |
| `sase macro types`   | List macro input types, including plugin-shared enums     |

## `sase macro catalog`

```text
usage: sase macro catalog [-h] [-o OUT_DIR]
```

Options:

| Option                        | Description                                         | Default |
| ----------------------------- | --------------------------------------------------- | ------- |
| `-h`, `--help`                | show this help message and exit                     | —       |
| `-o OUT_DIR`, `--out OUT_DIR` | Directory to write the PDF (defaults to a tempdir). | —       |

## `sase macro expand`

```text
usage: sase macro expand [-h] [-t] [prompt]
```

Options:

| Option          | Description                                                      | Default |
| --------------- | ---------------------------------------------------------------- | ------- |
| `-h`, `--help`  | show this help message and exit                                  | —       |
| `-t`, `--trace` | Print expansion trace to stderr showing each resolved reference. | `false` |

Arguments:

| Argument | Description                                               |
| -------- | --------------------------------------------------------- |
| `prompt` | Prompt text to expand. If not provided, reads from STDIN. |

## `sase macro explain`

```text
usage: sase macro explain [-h] [-a KEY=VALUE] workflow_name [args ...]
```

Options:

| Option                            | Description                       | Default |
| --------------------------------- | --------------------------------- | ------- |
| `-a KEY=VALUE`, `--arg KEY=VALUE` | Named argument (can be repeated). | —       |
| `-h`, `--help`                    | show this help message and exit   | —       |

Arguments:

| Argument        | Description                            |
| --------------- | -------------------------------------- |
| `workflow_name` | Workflow name to explain.              |
| `args`          | Positional arguments for the workflow. |

## `sase macro graph`

```text
usage: sase macro graph [-h] [-f {mermaid,text}] [workflow_name]
```

Options:

| Option                         | Description                                                   | Default   |
| ------------------------------ | ------------------------------------------------------------- | --------- |
| `-f FORMAT`, `--format FORMAT` | Output format (default: mermaid) (choices: `mermaid`, `text`) | `mermaid` |
| `-h`, `--help`                 | show this help message and exit                               | —         |

Arguments:

| Argument        | Description                                                   |
| --------------- | ------------------------------------------------------------- |
| `workflow_name` | Workflow name to graph. If not provided, lists all workflows. |

## `sase macro list`

```text
usage: sase macro list [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase macro show`

```text
usage: sase macro show [-h] [-c {auto,always,never}] [-f {full,json,raw}]
                       [-p PROJECT]
                       NAME
```

Show one macro or workflow definition: its declared properties, typed inputs, local helper macros, highlighted body, provenance, and the references it makes. The NAME argument accepts a bare name or a copied reference (#name, #!name, /name); arguments such as #name(a, b) are ignored with a note. --format json emits a versioned record and --format raw emits the exact definition source bytes.

Options:

| Option                            | Description                                                                          | Default |
| --------------------------------- | ------------------------------------------------------------------------------------ | ------- |
| `-c COLOR`, `--color COLOR`       | Color mode for rendered output (default: auto). (choices: `always`, `auto`, `never`) | `auto`  |
| `-f FORMAT`, `--format FORMAT`    | Output format (default: full). (choices: `full`, `json`, `raw`)                      | `full`  |
| `-h`, `--help`                    | show this help message and exit                                                      | —       |
| `-p PROJECT`, `--project PROJECT` | Resolve within a specific project namespace.                                         | —       |

Arguments:

| Argument | Description                                                    |
| -------- | -------------------------------------------------------------- |
| `name`   | Macro or workflow name, with optional copied reference marker. |

## `sase macro types`

```text
usage: sase macro types [-h] [-j] [NAME]
```

List macro input types: scalar keywords, builtin domain types, and plugin-shared enums. With NAME, show one type's detail card.

Options:

| Option         | Description                                | Default |
| -------------- | ------------------------------------------ | ------- |
| `-h`, `--help` | show this help message and exit            | —       |
| `-j`, `--json` | Print the Rust catalog projection as JSON. | `false` |

Arguments:

| Argument    | Description                                                                                      |
| ----------- | ------------------------------------------------------------------------------------------------ |
| `type_name` | Type name, alias, or plugin-qualified name (e.g. effort, sase-research-artifacts@audio_edition). |

Related: [CLI command groups](index.md).

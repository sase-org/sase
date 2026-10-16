---
title: "sase prompt"
description: "Inspect, search, and reuse previously submitted agent prompts"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase prompt

Inspect, search, and reuse previously submitted agent prompts

Reference for `sase prompt`. Run `sase prompt --help` for the exact output on this checkout.

```text
usage: sase prompt [-h]
                   {copy,delete,doctor,edit,export,list,prune,run,save,search,select,show,stash-archive,stats} ...
```

Bare `sase prompt` defaults to `sase prompt list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                  | Summary                                                              |
| --------------------------- | -------------------------------------------------------------------- |
| `sase prompt copy`          | Copy a prompt's exact text to the system clipboard                   |
| `sase prompt delete`        | Delete one stored prompt by selector (confirms unless --yes)         |
| `sase prompt doctor`        | Diagnose the prompt-history store (read-only, JSON with -j)          |
| `sase prompt edit`          | Open a prompt in the editor, then launch the edited text             |
| `sase prompt export`        | Export a local-history prompt to stdout or a file                    |
| `sase prompt list`          | List recent prompts (pretty table by default, JSON with -j)          |
| `sase prompt prune`         | Remove prompts by objective criteria (confirms unless --yes)         |
| `sase prompt run`           | Launch a stored prompt by selector                                   |
| `sase prompt save`          | Save a prompt as a reusable macro markdown file                      |
| `sase prompt search`        | Search canonical archived prompts and local history                  |
| `sase prompt select`        | Pick a prompt with an fzf picker, then launch it                     |
| `sase prompt show`          | Print a prompt by ID, hash prefix, or sha256:<hash>                  |
| `sase prompt stash-archive` | List, show, and restore archived stashed drafts                      |
| `sase prompt stats`         | Summarize the prompt-history store (pretty by default, JSON with -j) |

## `sase prompt copy`

```text
usage: sase prompt copy [-h] id
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                                                        |
| -------- | ------------------------------------------------------------------ |
| `id`     | Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash> |

## `sase prompt delete`

```text
usage: sase prompt delete [-h] [-y] id
```

Options:

| Option         | Description                                         | Default |
| -------------- | --------------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                     | —       |
| `-y`, `--yes`  | Skip the confirmation prompt and delete immediately | `false` |

Arguments:

| Argument | Description                                                        |
| -------- | ------------------------------------------------------------------ |
| `id`     | Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash> |

## `sase prompt doctor`

```text
usage: sase prompt doctor [-h] [-j]
```

Options:

| Option         | Description                                         | Default |
| -------------- | --------------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object (stable schema) | `false` |

## `sase prompt edit`

```text
usage: sase prompt edit [-h] [-P VCS_PREFIX] id
```

Options:

| Option                                 | Description                                                                                                                                                                                                                             | Default |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                         | show this help message and exit                                                                                                                                                                                                         | —       |
| `-P VCS_PREFIX`, `--prefix VCS_PREFIX` | Replace embedded '#' VCS workflow tags with VCS_PREFIX before replay, e.g. reuse a '#gh:sase' prompt under '#gh:bob-cli'. Unexpanded '+<project>' tags are left alone (the prefix is prepended), so retag those prompts by hand instead | —       |

Arguments:

| Argument | Description                                                        |
| -------- | ------------------------------------------------------------------ |
| `id`     | Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash> |

## `sase prompt export`

```text
usage: sase prompt export [-h] [-F] [-m] [-o PATH] [-s] id
```

Options:

| Option                  | Description                                                                                              | Default |
| ----------------------- | -------------------------------------------------------------------------------------------------------- | ------- |
| `-F`, `--force`         | Overwrite the destination file if it already exists                                                      | `false` |
| `-h`, `--help`          | show this help message and exit                                                                          | —       |
| `-m`, `--metadata`      | Wrap output in frontmatter (id, hash, timestamps, status, source)                                        | `false` |
| `-o PATH`, `--out PATH` | Write to PATH instead of stdout (fails if it exists without --force)                                     | —       |
| `-s`, `--sdd`           | Retired compatibility option; use --out for files or `sase agent prompts` for canonical archived prompts | `false` |

Arguments:

| Argument | Description                                                        |
| -------- | ------------------------------------------------------------------ |
| `id`     | Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash> |

## `sase prompt list`

```text
usage: sase prompt list [-h] [-a] [-c] [-j] [-l LIMIT] [-q QUERY]
```

Options:

| Option                      | Description                                               | Default |
| --------------------------- | --------------------------------------------------------- | ------- |
| `-a`, `--all`               | Include cancelled prompts alongside launched prompts      | `false` |
| `-c`, `--cancelled`         | Show only cancelled prompts (takes precedence over --all) | `false` |
| `-h`, `--help`              | show this help message and exit                           | —       |
| `-j`, `--json`              | Emit a machine-readable JSON array (stable schema)        | `false` |
| `-l LIMIT`, `--limit LIMIT` | Maximum number of prompts to return (default: 20)         | `20`    |
| `-q QUERY`, `--query QUERY` | Case-insensitive substring filter over exact prompt text  | —       |

## `sase prompt prune`

```text
usage: sase prompt prune [-h] [-b DATE] [-c] [-d] [-g] [-k LIMIT] [-l] [-y]
```

Options:

| Option                     | Description                                                                                                           | Default |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------- |
| `-b DATE`, `--before DATE` | Remove prompts older than DATE (YYYY-MM-DD, YYmmdd, or YYmmdd_HHMMSS)                                                 | —       |
| `-c`, `--cancelled`        | Limit removal to cancelled prompts                                                                                    | `false` |
| `-d`, `--dry-run`          | Show what would be removed without mutating the store                                                                 | `false` |
| `-g`, `--generated`        | Limit removal to machine-originated prompts (merged origin generated; a typed copy anywhere protects every duplicate) | `false` |
| `-h`, `--help`             | show this help message and exit                                                                                       | —       |
| `-k LIMIT`, `--keep LIMIT` | Keep the newest LIMIT prompts; older ones become removable                                                            | —       |
| `-l`, `--legacy`           | Also remove origin-less prompts the generated-text heuristic flags (requires --generated)                             | `false` |
| `-y`, `--yes`              | Skip the confirmation prompt and prune immediately                                                                    | `false` |

## `sase prompt run`

```text
usage: sase prompt run [-h] [-e] [-P VCS_PREFIX] id
```

Options:

| Option                                 | Description                                                                                                                                                                                                                             | Default |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-e`, `--edit`                         | Open the prompt in the editor before launching                                                                                                                                                                                          | `false` |
| `-h`, `--help`                         | show this help message and exit                                                                                                                                                                                                         | —       |
| `-P VCS_PREFIX`, `--prefix VCS_PREFIX` | Replace embedded '#' VCS workflow tags with VCS_PREFIX before replay, e.g. reuse a '#gh:sase' prompt under '#gh:bob-cli'. Unexpanded '+<project>' tags are left alone (the prefix is prepended), so retag those prompts by hand instead | —       |

Arguments:

| Argument | Description                                                        |
| -------- | ------------------------------------------------------------------ |
| `id`     | Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash> |

## `sase prompt save`

```text
usage: sase prompt save [-h] [-D TEXT] [-F] [-g] [-n NAME] [-p PROJECT]
                        [-t TAG]
                        id
```

Options:

| Option                            | Description                                                | Default |
| --------------------------------- | ---------------------------------------------------------- | ------- |
| `-D TEXT`, `--description TEXT`   | Override the auto-generated macro description              | —       |
| `-F`, `--force`                   | Overwrite the macro file if it already exists              | `false` |
| `-g`, `--global`                  | Save to ~/sase/macros/ instead of the project sase/macros/ | `false` |
| `-h`, `--help`                    | show this help message and exit                            | —       |
| `-n NAME`, `--name NAME`          | Macro name (defaults to a slug derived from the prompt)    | —       |
| `-p PROJECT`, `--project PROJECT` | Save to ~/sase/macros/PROJECT/ for a project namespace     | —       |
| `-t TAG`, `--tag TAG`             | Tag recorded in macro frontmatter (repeatable)             | —       |

Arguments:

| Argument | Description                                                        |
| -------- | ------------------------------------------------------------------ |
| `id`     | Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash> |

## `sase prompt search`

```text
usage: sase prompt search [-h] [-a DATE] [-b DATE] [-c {auto,always,never}]
                          [-f {compact,json,full}] [-n LIMIT]
                          [-s {archive,local,all,sdd}] [-t TAG] [-x]
                          query
```

Find prompts whose text or metadata contains a literal query, across the canonical agents-sidecar archive and machine-wide local prompt history. Archived prompts rank first.

Options:

| Option                         | Description                                                                                                                                     | Default   |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| `-a DATE`, `--after DATE`      | Keep prompts dated on/after DATE: 2026-01-01, 202601 (YYYYMM), 260101 (YYmmdd), 260101_143000, or a relative 30d/2w/6m/1y                       | —         |
| `-b DATE`, `--before DATE`     | Keep prompts dated on/before DATE (same forms as --after)                                                                                       | —         |
| `-x`, `--cancelled`            | Restrict local results to cancelled prompts (no effect on archive)                                                                              | `false`   |
| `-c COLOR`, `--color COLOR`    | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                                       | `auto`    |
| `-f FORMAT`, `--format FORMAT` | Output format: compact, json, or full (default: compact) (choices: `compact`, `full`, `json`)                                                   | `compact` |
| `-h`, `--help`                 | show this help message and exit                                                                                                                 | —         |
| `-n LIMIT`, `--limit LIMIT`    | Maximum results to show after ranking; 0 means unlimited (default: 20)                                                                          | `20`      |
| `-s SOURCE`, `--source SOURCE` | Which store to search: archive, local, or all (default: all); sdd is a deprecated alias for archive (choices: `all`, `archive`, `local`, `sdd`) | `all`     |
| `-t TAG`, `--tag TAG`          | Keep prompts carrying TAG (repeatable; repeats OR together)                                                                                     | —         |

Arguments:

| Argument | Description                                              |
| -------- | -------------------------------------------------------- |
| `query`  | Literal, non-empty text to search for (case-insensitive) |

## `sase prompt select`

```text
usage: sase prompt select [-h] [-a] [-c] [-e] [-P VCS_PREFIX] [-q QUERY]
```

Options:

| Option                                 | Description                                                                                                                                                                                                                             | Default |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a`, `--all`                          | Include cancelled prompts alongside launched prompts                                                                                                                                                                                    | `false` |
| `-c`, `--cancelled`                    | Show only cancelled prompts (takes precedence over --all)                                                                                                                                                                               | `false` |
| `-e`, `--edit`                         | Open the selected prompt in the editor before launching                                                                                                                                                                                 | `false` |
| `-h`, `--help`                         | show this help message and exit                                                                                                                                                                                                         | —       |
| `-P VCS_PREFIX`, `--prefix VCS_PREFIX` | Replace embedded '#' VCS workflow tags with VCS_PREFIX before replay, e.g. reuse a '#gh:sase' prompt under '#gh:bob-cli'. Unexpanded '+<project>' tags are left alone (the prefix is prepended), so retag those prompts by hand instead | —       |
| `-q QUERY`, `--query QUERY`            | Case-insensitive substring filter over candidates before fzf                                                                                                                                                                            | —       |

## `sase prompt show`

```text
usage: sase prompt show [-h] [-f {raw,markdown,json}] id
```

Options:

| Option                         | Description                                                                                                                                                                            | Default |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-f FORMAT`, `--format FORMAT` | Output format: 'raw' (default) prints exact prompt text, 'markdown' prints a metadata header plus the body, 'json' prints metadata plus full text (choices: `json`, `markdown`, `raw`) | `raw`   |
| `-h`, `--help`                 | show this help message and exit                                                                                                                                                        | —       |

Arguments:

| Argument | Description                                                        |
| -------- | ------------------------------------------------------------------ |
| `id`     | Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash> |

## `sase prompt stash-archive`

```text
usage: sase prompt stash-archive [-h] {list,restore,show} ...
```

Recover drafts that permanently left the prompt stash. Every row that leaves the stash — restored, deleted, purged, evicted, or overwritten — is archived first to prompt_stash_archive.jsonl, newest first. Running 'sase prompt stash-archive' with no subcommand lists recent archive rows.

Bare `sase prompt stash-archive` defaults to `sase prompt stash-archive list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                          | Summary                                                      |
| ----------------------------------- | ------------------------------------------------------------ |
| `sase prompt stash-archive list`    | List archived drafts (pretty table by default, JSON with -j) |
| `sase prompt stash-archive restore` | Restore archived drafts back to Stash by id                  |
| `sase prompt stash-archive show`    | Print one archived draft with its full text                  |

### `sase prompt stash-archive list`

```text
usage: sase prompt stash-archive list [-h] [-j] [-n LIMIT] [-q QUERY]
                                      [-r {evicted,overwritten,popped,purged}]
```

Options:

| Option                         | Description                                                                                | Default |
| ------------------------------ | ------------------------------------------------------------------------------------------ | ------- |
| `-h`, `--help`                 | show this help message and exit                                                            | —       |
| `-j`, `--json`                 | Emit a machine-readable JSON array (stable schema)                                         | `false` |
| `-n LIMIT`, `--limit LIMIT`    | Maximum number of archive rows to return (default: 20)                                     | `20`    |
| `-q QUERY`, `--query QUERY`    | Case-insensitive substring filter over draft text and frontmatter                          | —       |
| `-r REASON`, `--reason REASON` | Keep only rows archived for REASON (choices: `evicted`, `overwritten`, `popped`, `purged`) | —       |

### `sase prompt stash-archive restore`

```text
usage: sase prompt stash-archive restore [-h] ID [ID ...]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                                                                               |
| -------- | ----------------------------------------------------------------------------------------- |
| `ids`    | Archived draft id or unique id prefix (repeatable); skipped ids are reported with reasons |

### `sase prompt stash-archive show`

```text
usage: sase prompt stash-archive show [-h] [-j] id
```

Options:

| Option         | Description                                         | Default |
| -------------- | --------------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object (stable schema) | `false` |

Arguments:

| Argument | Description                           |
| -------- | ------------------------------------- |
| `id`     | Archived draft id or unique id prefix |

## `sase prompt stats`

```text
usage: sase prompt stats [-h] [-j]
```

Options:

| Option         | Description                                         | Default |
| -------------- | --------------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object (stable schema) | `false` |

Related: [CLI command groups](index.md).

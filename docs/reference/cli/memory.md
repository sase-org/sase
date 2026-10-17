---
title: "sase memory"
description: "Inspect SASE memory context."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase memory

Inspect and initialize SASE memory context

Reference for `sase memory`. Run `sase memory --help` for the exact output on this checkout.

```text
usage: sase memory [-h] {history,init,list,log,read,show,web} ...
```

Inspect SASE memory context. With no subcommand, defaults to `sase memory list`.

Bare `sase memory` defaults to `sase memory list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand            | Summary                                                       |
| --------------------- | ------------------------------------------------------------- |
| `sase memory history` | Browse committed memory and instruction-file history          |
| `sase memory init`    | Create or refresh memory files, AGENTS.md, and provider shims |
| `sase memory list`    | Show loaded, referenced, available, and missing memory files  |
| `sase memory log`     | Summarize or inspect auditable reference memory reads         |
| `sase memory read`    | Read and audit one or more memory selectors                   |
| `sase memory show`    | Print one or more memory selectors without recording a read   |
| `sase memory web`     | List and inspect memory webs and their strands                |

## `sase memory history`

```text
usage: sase memory history [-h] [-a] [-A REV] [-d] [-f {json,pager,text}]
                           [-l N] [-m] [-p REF] [-s DATE]
                           [-S {all,home,project}]
                           [SELECTOR ...]
```

Browse the committed history of SASE memory notes, webs, strands, and agent instruction files (AGENTS.md plus its provider shims, project and home). With no selector, shows the cross-file changes feed; with selectors, shows each subject's timeline. Viewing history never records an audited read.

Options:

| Option                         | Description                                                                                                                                                                                                                                  | Default |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a`, `--all`                  | Show hidden versions (moves, reflows) and regen-only changesets                                                                                                                                                                              | `false` |
| `-A REV`, `--at REV`           | Show one version: an ordinal (7 or v7), ~N (~1 is newest), a commit SHA prefix, blob:OID (a full blob OID or a unique prefix of at least 7 hex characters), now for the worktree file, or a YYYY-MM-DD date (latest version at or before it) | —       |
| `-d`, `--diff`                 | Show the change instead of the body                                                                                                                                                                                                          | `false` |
| `-f FORMAT`, `--format FORMAT` | Output format (default: pager on a TTY, else text). json emits the Rust wire unchanged; text prints timelines and bodies. (choices: `json`, `pager`, `text`)                                                                                 | —       |
| `-h`, `--help`                 | show this help message and exit                                                                                                                                                                                                              | —       |
| `-l N`, `--limit N`            | Keep at most N feed changesets or timeline versions                                                                                                                                                                                          | —       |
| `-m`, `--mark-reviewed`        | Mark the shown scopes reviewed through their newest changesets (feed mode only; an error with selectors)                                                                                                                                     | `false` |
| `-p REF`, `--project REF`      | Project to resolve memory from (default: infer from current directory)                                                                                                                                                                       | —       |
| `-S SCOPE`, `--scope SCOPE`    | History scopes to query (default: all) (choices: `all`, `home`, `project`)                                                                                                                                                                   | `all`   |
| `-s DATE`, `--since DATE`      | Only include changes at or after YYYY-MM-DD                                                                                                                                                                                                  | —       |

Arguments:

| Argument    | Description                                                                                                                                                                                                                                                                                                                                        |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `selectors` | Memory or instruction selectors: a flat note name (tui.md), a repo-relative path (sase/memory/tui.md), a bare web name (glossary), a web:keyword strand reference (glossary:stitch), an instruction path (AGENTS.md, CLAUDE.md, subdir/AGENTS.md, ~/AGENTS.md), or a historical name (build_and_run.md). With no selector, shows the changes feed. |

## `sase memory init`

```text
usage: sase memory init [-h] [-c] [-d] [-M] [-m MESSAGE] [-C]
```

Create or refresh SASE memory files, managed AGENTS.md, and provider instruction shims. `sase init memory` is a compatibility alias for this command.

Options:

| Option                            | Description                                                                                                                  | Default |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-c`, `--check`                   | Report memory initialization drift without writing files                                                                     | `false` |
| `-d`, `--diff`                    | Show full file diffs for planned memory changes                                                                              | `false` |
| `-M`, `--enable-project-memory`   | Create or update sase/sase.yml with is_sase_managed: true, enabling managed project memory (cannot be combined with --check) | `false` |
| `-h`, `--help`                    | show this help message and exit                                                                                              | —       |
| `-m MESSAGE`, `--message MESSAGE` | Commit subject for folding eligible memory and generated-change source edits; a `docs(memory):` tag is added if omitted      | —       |
| `-C`, `--no-commit`               | Skip the project git commit/push sequence                                                                                    | `false` |

## `sase memory list`

```text
usage: sase memory list [-h]
```

Show the memory files visible from the current launch context, including loaded @ references, referenced-only plain memory paths, available files, and missing references.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase memory log`

```text
usage: sase memory log [-h] [--path MEMORY_PATH] [--agent AGENT_NAME]
                       [--id READ_ID] [--include KIND] [--json]
```

Summarize auditable reference memory reads recorded by `sase memory read`, or inspect matching read events with --path, --agent, or --id.

Options:

| Option               | Description                                                                                                        | Default |
| -------------------- | ------------------------------------------------------------------------------------------------------------------ | ------- |
| `--agent AGENT_NAME` | Only include reads by the given agent                                                                              | —       |
| `-h`, `--help`       | show this help message and exit                                                                                    | —       |
| `--id READ_ID`       | Show one memory read event by id or unambiguous id prefix                                                          | —       |
| `--include KIND`     | Include additional audit events: 'glossary' folds in the legacy sase glossary read audit log (choices: `glossary`) | —       |
| `--json`             | Emit deterministic machine-readable JSON                                                                           | `false` |
| `--path MEMORY_PATH` | Only include reads for the given memory-relative path                                                              | —       |

## `sase memory read`

```text
usage: sase memory read [-h] [-d N] [-f {json,markdown,rich}] [-p REF] -r
                        REASON
                        selector [selector ...]
```

Resolve one or more memory selectors from project sase/memory/, falling back to ~/sase/memory/ when the project file is absent. A selector is a flat note name (generated_skills.md), a bare memory-web name (glossary, every strand), or a web:keyword strand reference (glossary:stitch). The whole batch is resolved before anything is printed or logged, so one unknown selector fails the entire request. Leading YAML frontmatter is stripped from notes, child notes are listed when present, and each read appends one attributable audit log row. Identical to `sase memory show` except that it requires a reason and records an audited read before printing.

Options:

| Option                         | Description                                                                                                                                 | Default    |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| `-d N`, `--depth N`            | Cap link/mention closure recursion depth (default: unlimited); -d 0 prints only the requested selectors and lists every link as a reference | —          |
| `-f FORMAT`, `--format FORMAT` | Output format (default: markdown) (choices: `json`, `markdown`, `rich`)                                                                     | `markdown` |
| `-h`, `--help`                 | show this help message and exit                                                                                                             | —          |
| `-p REF`, `--project REF`      | Project to resolve memory from (default: infer from current directory)                                                                      | —          |
| `-r REASON`, `--reason REASON` | Non-empty reason for the audited memory read (required)                                                                                     | —          |

Arguments:

| Argument    | Description                                                                                                                                           |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `selectors` | One or more selectors: a flat note name (generated_skills.md), a bare memory-web name (glossary), or a web:keyword strand reference (glossary:stitch) |

## `sase memory show`

```text
usage: sase memory show [-h] [-d N] [-f {json,markdown,rich}] [-p REF]
                        selector [selector ...]
```

Resolve one or more memory selectors exactly like `sase memory read` — project sase/memory/ first, then ~/sase/memory/ — strip leading YAML frontmatter from notes, and append the `## Children` section when children exist. Unlike `read`, this command records no audit event, so agents consulting memory to do work must use `sase memory read` instead.

Options:

| Option                         | Description                                                                                                                                 | Default    |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| `-d N`, `--depth N`            | Cap link/mention closure recursion depth (default: unlimited); -d 0 prints only the requested selectors and lists every link as a reference | —          |
| `-f FORMAT`, `--format FORMAT` | Output format (default: markdown) (choices: `json`, `markdown`, `rich`)                                                                     | `markdown` |
| `-h`, `--help`                 | show this help message and exit                                                                                                             | —          |
| `-p REF`, `--project REF`      | Project to resolve memory from (default: infer from current directory)                                                                      | —          |

Arguments:

| Argument    | Description                                                                                                                                           |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `selectors` | One or more selectors: a flat note name (generated_skills.md), a bare memory-web name (glossary), or a web:keyword strand reference (glossary:stitch) |

## `sase memory web`

```text
usage: sase memory web [-h] {list,show} ...
```

Inspect memory webs — keyed strand collections addressed with `sase memory read <web>:<keyword>`. Running `sase memory web` defaults to `sase memory web list`.

Bare `sase memory web` defaults to `sase memory web list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand             | Summary                                |
| ---------------------- | -------------------------------------- |
| `sase memory web list` | List memory webs for a project         |
| `sase memory web show` | Show one web's filterable strand index |

### `sase memory web list`

```text
usage: sase memory web list [-h] [-f {json,names,table}] [-p REF]
```

List discovered memory webs: name, rendering (core/reference), scope, and strand count.

Options:

| Option                         | Description                                                                 | Default |
| ------------------------------ | --------------------------------------------------------------------------- | ------- |
| `-f FORMAT`, `--format FORMAT` | Output format (default: table) (choices: `json`, `names`, `table`)          | `table` |
| `-h`, `--help`                 | show this help message and exit                                             | —       |
| `-p REF`, `--project REF`      | Project to resolve memory webs from (default: infer from current directory) | —       |

### `sase memory web show`

```text
usage: sase memory web show [-h] [-b] [-f {json,names,table}] [-p REF]
                            WEB [PATTERN]
```

Print one web's strand index: keyword, slug, aliases, mention-reference count, and summary, optionally filtered by PATTERN. This is the index; `sase memory show <web>:<keyword>` is the content read.

Options:

| Option                         | Description                                                                 | Default |
| ------------------------------ | --------------------------------------------------------------------------- | ------- |
| `-b`, `--bodies`               | Extend PATTERN matching into strand bodies                                  | `false` |
| `-f FORMAT`, `--format FORMAT` | Output format (default: table) (choices: `json`, `names`, `table`)          | `table` |
| `-h`, `--help`                 | show this help message and exit                                             | —       |
| `-p REF`, `--project REF`      | Project to resolve memory webs from (default: infer from current directory) | —       |

Arguments:

| Argument  | Description                                                 |
| --------- | ----------------------------------------------------------- |
| `web`     | Memory web slug to inspect                                  |
| `pattern` | Case-insensitive substring filter over keywords and aliases |

Related: [CLI command groups](index.md).

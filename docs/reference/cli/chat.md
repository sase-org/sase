---
title: "sase chat"
description: "Discover and inspect prior agent chat transcripts"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase chat

Discover and inspect prior agent chat transcripts

Reference for `sase chat`. Run `sase chat --help` for the exact output on this checkout.

```text
usage: sase chat [-h] {list,show} ...
```

Bare `sase chat` defaults to `sase chat list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand       | Summary                                                              |
| ---------------- | -------------------------------------------------------------------- |
| `sase chat list` | List recent chat transcripts (pretty table by default, JSON with -j) |
| `sase chat show` | Show a chat transcript by agent name, path, or basename              |

## `sase chat list`

```text
usage: sase chat list [-h] [-j] [-l LIMIT] [-m MACHINE]
                      [-P {local,shared,remote,unknown}] [-q QUERY]
```

List recent chat transcripts, newest first, with the sync provenance of each one: 'local' (written here, not published), 'shared' (written here and published to an agents sidecar), 'remote' (imported from another machine), or 'unknown' (provenance could not be determined).

Options:

| Option                                     | Description                                                                                                                                                                | Default |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                             | show this help message and exit                                                                                                                                            | —       |
| `-j`, `--json`                             | Emit a machine-readable JSON array (stable schema)                                                                                                                         | `false` |
| `-l LIMIT`, `--limit LIMIT`                | Maximum number of transcripts to return (default: 20)                                                                                                                      | `20`    |
| `-m MACHINE`, `--machine MACHINE`          | Only show transcripts whose source machine matches this name (case-insensitive); remote transcripts report their origin machine, local and shared ones report this machine | —       |
| `-P PROVENANCE`, `--provenance PROVENANCE` | Only show transcripts with this sync provenance (choices: `local`, `remote`, `shared`, `unknown`)                                                                          | —       |
| `-q QUERY`, `--query QUERY`                | Case-insensitive substring filter over path/basename/content                                                                                                               | —       |

## `sase chat show`

```text
usage: sase chat show [-h] (-n AGENT | -p PATH | -b BASENAME)
                      [-f {raw,resume,response}]
```

Options:

| Option                               | Description                                                                                                                                                                                  | Default |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-n AGENT`, `--agent AGENT`          | Resolve transcript by named agent (done.response_path or meta.chat_path)                                                                                                                     | —       |
| `-b BASENAME`, `--basename BASENAME` | Chat transcript basename (with or without .md extension)                                                                                                                                     | —       |
| `-f FORMAT`, `--format FORMAT`       | Output format: 'raw' (default) prints transcript markdown, 'resume' prints flattened User/Assistant turns, 'response' prints the latest response only (choices: `raw`, `response`, `resume`) | `raw`   |
| `-h`, `--help`                       | show this help message and exit                                                                                                                                                              | —       |
| `-p PATH`, `--path PATH`             | Path to a chat transcript file (~ is expanded)                                                                                                                                               | —       |

Related: [CLI command groups](index.md).

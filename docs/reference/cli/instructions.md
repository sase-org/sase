---
title: "sase instructions"
description: "Inspect agent instruction documents."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase instructions

Inspect agent instruction documents

Reference for `sase instructions`. Run `sase instructions --help` for the exact output on this checkout.

```text
usage: sase instructions [-h] {list,readout,render,show,verify} ...
```

Inspect agent instruction documents. With no subcommand, defaults to `sase instructions list`.

Bare `sase instructions` defaults to `sase instructions list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                  | Summary                                                            |
| --------------------------- | ------------------------------------------------------------------ |
| `sase instructions list`    | Show AGENTS.md files, provider shims, and memory reference status  |
| `sase instructions readout` | Show handoff-aware declaration misses per provider and mode        |
| `sase instructions render`  | Preview the memory-built instruction bundle for this project       |
| `sase instructions show`    | Print one agent's recorded instruction bundle and check its digest |
| `sase instructions verify`  | Show observed instruction loads per provider                       |

## `sase instructions list`

```text
usage: sase instructions list [-h]
```

Show discovered AGENTS.md files across the project, its subdirectories, home, and chezmoi source, including each H1 title, managed/custom state, memory reference counts, and provider instruction shim status. This command never writes files.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase instructions readout`

```text
usage: sase instructions readout [-h] [-j] [-p PROVIDER] [-s WHEN] [-u WHEN]
```

Classify finished root runs as accepted, plan handoff, monitor handoff, other handoff, not required, miss, or unknown, per provider and delivery mode, and join audited memory reads per run. The command reports; it does not gate.

Options:

| Option                               | Description                                                | Default |
| ------------------------------------ | ---------------------------------------------------------- | ------- |
| `-h`, `--help`                       | show this help message and exit                            | —       |
| `-j`, `--json`                       | Emit one stable JSON document                              | `false` |
| `-p PROVIDER`, `--provider PROVIDER` | Filter to one provider; repeatable                         | —       |
| `-s WHEN`, `--since WHEN`            | Window start: duration (30m, 24h, 7d, 2w) or ISO timestamp | `7d`    |
| `-u WHEN`, `--until WHEN`            | Window end: duration (30m, 24h, 7d, 2w) or ISO timestamp   | —       |

## `sase instructions render`

```text
usage: sase instructions render [-h] [-a NAME] [-f KEY=VALUE] [-j] [-N] [-p]
                                [-s]
```

Render the memory-built instruction bundle the agent would receive from the current project and home sources, without delivering it. Prints the bundle Markdown by default.

Options:

| Option                             | Description                                                                                                                                                                  | Default |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a NAME`, `--agent NAME`          | Start from one agent's facts (provider from its run record); sources stay the current project and home                                                                       | —       |
| `-f KEY=VALUE`, `--fact KEY=VALUE` | Override one fact (repeatable; comma-separated pairs accepted). Keys: actor, mode, purpose, provider, project, host, vcs. mode=interactive\|export implies actor=interactive | —       |
| `-h`, `--help`                     | show this help message and exit                                                                                                                                              | —       |
| `-j`, `--json`                     | Print the normalized preview manifest instead of the bundle                                                                                                                  | `false` |
| `-N`, `--no-cache`                 | Bypass the render cache (records cache: bypass)                                                                                                                              | `false` |
| `-p`, `--parity`                   | Also check the bundle against the legacy AGENTS.md files; prints a table to stderr and exits 1 on any gap                                                                    | `false` |
| `-s`, `--sections`                 | Print the section table instead of the bundle                                                                                                                                | `false` |

## `sase instructions show`

```text
usage: sase instructions show [-h] NAME [-H] [-j] [-l] [-n NN] [-s]
```

Print a named agent's archived instruction bundle and check that the stored bytes match the manifest sha256. Dismissed agents resolve the same way as `sase agent show`. The default output is the bundle Markdown on stdout plus one summary line on stderr.

Options:

| Option              | Description                                                                         | Default |
| ------------------- | ----------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`      | show this help message and exit                                                     | —       |
| `-H`, `--helper`    | Show the helper bundle of the chosen invocation                                     | `false` |
| `-j`, `--json`      | Print the manifest JSON instead of the bundle                                       | `false` |
| `-l`, `--list`      | One row per recorded invocation (root and helper)                                   | `false` |
| `-s`, `--sections`  | Print the section table instead of the bundle                                       | `false` |
| `-n NN`, `--seq NN` | Choose an invocation sequence; default is agent_meta.json['instructions']['latest'] | —       |

Arguments:

| Argument | Description                                                |
| -------- | ---------------------------------------------------------- |
| `agent`  | Agent name (dismissed bundles and Agents-tab members work) |

## `sase instructions verify`

```text
usage: sase instructions verify [-h] [-a NAME] [-c] [-H] [-j] [-n N]
                                [-p PROVIDER] [-s WHEN] [-u WHEN]
```

Show what each provider's SASE runs and native helpers actually loaded, read from the providers' own session records. The command reports; it does not gate.

Options:

| Option                               | Description                                                | Default |
| ------------------------------------ | ---------------------------------------------------------- | ------- |
| `-a NAME`, `--agent NAME`            | One agent's runs, with per-session detail                  | —       |
| `-c`, `--coverage`                   | Show manifest coverage per provider and purpose            | `false` |
| `-h`, `--help`                       | show this help message and exit                            | —       |
| `-H`, `--helpers`                    | Show per-helper rows                                       | `false` |
| `-j`, `--json`                       | Emit one stable JSON document                              | `false` |
| `-n N`, `--limit N`                  | Newest runs per provider (default 20, max 200)             | `20`    |
| `-p PROVIDER`, `--provider PROVIDER` | Filter to one provider; repeatable                         | —       |
| `-s WHEN`, `--since WHEN`            | Window start: duration (30m, 24h, 7d, 2w) or ISO timestamp | `7d`    |
| `-u WHEN`, `--until WHEN`            | Window end: duration (30m, 24h, 7d, 2w) or ISO timestamp   | —       |

Related: [CLI command groups](index.md).

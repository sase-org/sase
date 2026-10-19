---
title: "sase stats"
description: "Show Admin Center Statistics views from the command line."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase stats

Show Admin Center Statistics views from the command line.

Reference for `sase stats`. Run `sase stats --help` for the exact output on this checkout.

```text
usage: sase stats [-h] {project} ...
```

Show Admin Center Statistics views from the command line. Bare `sase stats` lists implemented views. There are no stubs.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                                                                                                                          |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `sase stats project` | Show the Admin Center Statistics → Projects view: what each project produced, how big its code is, and this machine's agent runs |

## `sase stats project`

```text
usage: sase stats project [-h] [-D] [-F] [-f {json,markdown,rich}]
                          [-g {model,patch,project,repo}] [-j] [-p PROJECT]
                          [-r RANGE]
```

Show the Admin Center Statistics → Projects view: what each project produced (commits and committed plans, and which provider/model produced them), how big and how old its code is, and this machine's agent runs. Output and code facts come from each code repo's default branch and match on every machine; run facts come from this machine's run log and say so. Same loader and definitions as the TUI tab.

Options:

| Option                               | Description                                                                                                                                 | Default |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-F`, `--fetch`                      | Fetch each code repo's default branch before measuring (default: local refs)                                                                | `false` |
| `-f FORMAT`, `--format FORMAT`       | Output format (default: rich) (choices: `json`, `markdown`, `rich`)                                                                         | —       |
| `-g GROUP_BY`, `--group-by GROUP_BY` | Breakdown table, like the TUI's g key (default: project for several projects, model for one) (choices: `model`, `patch`, `project`, `repo`) | —       |
| `-h`, `--help`                       | show this help message and exit                                                                                                             | —       |
| `-D`, `--include-disabled`           | Also include disabled projects when no -p is given                                                                                          | `false` |
| `-j`, `--json`                       | Shorthand for --format json                                                                                                                 | `false` |
| `-p PROJECT`, `--project PROJECT`    | Project name, alias, key, or +tag; repeatable (default: every enabled project)                                                              | —       |
| `-r RANGE`, `--range RANGE`          | today, 24h, 7d, 30d, 90d, all, Nh/Nd/Nw, YYYY-MM, YYYY-MM-DD, or START..END (default: 7d, the TUI default)                                  | —       |

Related: [CLI command groups](index.md).

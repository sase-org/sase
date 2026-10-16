---
title: "sase usage"
description: "Inspect cached provider subscription-usage observations and submit explicit refreshes."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase usage

Inspect and refresh cached LLM subscription usage

Reference for `sase usage`. Run `sase usage --help` for the exact output on this checkout.

```text
usage: sase usage [-h] {list,refresh} ...
```

Inspect cached provider subscription-usage observations and submit explicit refreshes. Running `sase usage` defaults to `sase usage list`. The list command never calls provider CLIs or APIs; use `sase usage refresh` to submit bounded refresh work.

Bare `sase usage` defaults to `sase usage list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                                                  |
| -------------------- | -------------------------------------------------------- |
| `sase usage list`    | List cached subscription usage without probing providers |
| `sase usage refresh` | Submit explicit subscription-usage refresh work          |

## `sase usage list`

```text
usage: sase usage list [-h] [-j] [-P] [-p PROVIDER] [-v]
```

Render the cached subscription-usage snapshot. This command is strictly offline and does not start AXE, log in, or call provider CLIs. Missing observations are reported as data.

Options:

| Option                               | Description                                          | Default |
| ------------------------------------ | ---------------------------------------------------- | ------- |
| `-h`, `--help`                       | show this help message and exit                      | —       |
| `-j`, `--json`                       | Emit one stable JSON document                        | `false` |
| `-P`, `--plain`                      | Emit undecorated line-oriented text                  | `false` |
| `-p PROVIDER`, `--provider PROVIDER` | Filter to one provider; repeatable                   | —       |
| `-v`, `--verbose`                    | Show source, diagnostic, and exact timestamp details | `false` |

## `sase usage refresh`

```text
usage: sase usage refresh [-h] [-b] [-j] [-P] [-p PROVIDER] [-v]
```

Submit bounded durable refresh work for provider subscription usage. By default this waits for submitted or joined work and then renders the refreshed cache. Use --background to return after submission.

Options:

| Option                               | Description                                            | Default |
| ------------------------------------ | ------------------------------------------------------ | ------- |
| `-b`, `--background`                 | Submit or join refresh work and return without waiting | `false` |
| `-h`, `--help`                       | show this help message and exit                        | —       |
| `-j`, `--json`                       | Emit one stable JSON document                          | `false` |
| `-P`, `--plain`                      | Emit undecorated line-oriented text                    | `false` |
| `-p PROVIDER`, `--provider PROVIDER` | Filter to one provider; repeatable                     | —       |
| `-v`, `--verbose`                    | Show source, diagnostic, and exact timestamp details   | `false` |

Related: [CLI command groups](index.md).

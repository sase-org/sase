---
title: "sase tmux-agent"
description: "Launch an interactive agent CLI in a new tmux window."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase tmux-agent

Launch an interactive agent CLI in a new tmux window

Reference for `sase tmux-agent`. Run `sase tmux-agent --help` for the exact output on this checkout.

```text
usage: sase tmux-agent [-h] [-c <dir>] [-e <level>] [-j] [-l] [-n] [-r] [-s]
                       [-v]
                       [<provider>]
```

Launch an interactive agent CLI in a new tmux window. A bare `sase tmux-agent` paints a centered tmux display-menu of every registered agent CLI; choosing a row (or passing a provider) opens a new window in the current pane's directory. There is no `list` subcommand: a bare invocation must open the menu, because the tmux key binding (`bind A run "sase tmux-agent"`) depends on that. Use `-l|--list` to print the catalog. `--renumber` is an internal hook invoked when an agent CLI window exits.

Options:

| Option                           | Description                                                                                                                                                                                                      | Default |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-c <dir>`, `--dir <dir>`        | Launch directory (default: current tmux pane path, else $PWD)                                                                                                                                                    | —       |
| `-n`, `--dry-run`                | Print the window name, directory, env, and exact command; change nothing                                                                                                                                         | `false` |
| `-e <level>`, `--effort <level>` | Explicit reasoning effort for this launch (off, none, minimal, low, medium, high, xhigh, max); unsupported levels are a usage error (choices: `high`, `low`, `max`, `medium`, `minimal`, `none`, `off`, `xhigh`) | —       |
| `-h`, `--help`                   | show this help message and exit                                                                                                                                                                                  | —       |
| `-j`, `--json`                   | Emit a versioned JSON envelope of the catalog or the dry-run plan                                                                                                                                                | `false` |
| `-l`, `--list`                   | Print the catalog as a table; works outside tmux (not a subcommand)                                                                                                                                              | `false` |
| `-r`, `--refresh`                | Rebuild the catalog cache before doing anything else                                                                                                                                                             | `false` |
| `-s`, `--safe`                   | Launch without the provider's approval-bypass args                                                                                                                                                               | `false` |
| `-v`, `--verbose`                | With --list, add resolved paths, full commands, and install hints                                                                                                                                                | `false` |

Arguments:

| Argument   | Description                                                     |
| ---------- | --------------------------------------------------------------- |
| `provider` | Provider to launch directly (omit to paint the tmux Agent menu) |

Related: [CLI command groups](index.md).

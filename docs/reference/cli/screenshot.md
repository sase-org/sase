---
title: "sase screenshot"
description: "Launch or reuse a real `sase tui` in tmux, drive it with keypresses and typed text, ask the live app to export SVG, and rasterize that SVG to PNG."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase screenshot

Capture a PNG of a real live SASE TUI

Reference for `sase screenshot`. Run `sase screenshot --help` for the exact output on this checkout.

```text
usage: sase screenshot [-h] [-H ALIAS_OR_SSH] [-k] [-o PATH] [-p KEY] [-d MS]
                       [-s COLSxROWS] [-S] [-t SECONDS] [-T TEXT] [-w REGEX]
                       [-W TMUX_TARGET]
                       ...
```

Launch or reuse a real `sase tui` in tmux, drive it with keypresses and typed text, ask the live app to export SVG, and rasterize that SVG to PNG. Repeatable -p/--press, -T/--type, and -w/--wait-for form one argv-ordered input script.

Options:

| Option                                   | Description                                                                                     | Default   |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------- | --------- |
| `-h`, `--help`                           | show this help message and exit                                                                 | —         |
| `-H ALIAS_OR_SSH`, `--host ALIAS_OR_SSH` | Run the SVG capture on an enrolled machine alias or raw SSH destination                         | —         |
| `-k`, `--keep`                           | Leave a newly launched tmux window running after capture                                        | `false`   |
| `-o PATH`, `--output PATH`               | Output path (default: managed temporary screenshot path)                                        | —         |
| `-p KEY`, `--press KEY`                  | Send one tmux key name; repeats interleave with --type and -w in argv order                     | —         |
| `-d MS`, `--settle-ms MS`                | Extra settle delay before capture in milliseconds (default: 0)                                  | `0`       |
| `-s COLSxROWS`, `--size COLSxROWS`       | Pane geometry for a new capture window (default: 120x40)                                        | `120, 40` |
| `-S`, `--svg`                            | Write SVG output and skip PNG rasterization                                                     | `false`   |
| `-t SECONDS`, `--timeout SECONDS`        | Overall capture deadline in seconds (default: 60)                                               | `60.0`    |
| `-T TEXT`, `--type TEXT`                 | Send literal TUI text (tmux send-keys -l); repeats interleave with -p and -w in argv order      | —         |
| `-w REGEX`, `--wait-for REGEX`           | Wait for tmux screen text to match a regex; repeats interleave with -p and --type in argv order | —         |
| `-W TMUX_TARGET`, `--window TMUX_TARGET` | Capture an existing tmux target instead of launching a new TUI                                  | —         |

Arguments:

| Argument   | Description                                              |
| ---------- | -------------------------------------------------------- |
| `tui_args` | Arguments forwarded to `sase tui` after a `--` separator |

Related: [CLI command groups](index.md).

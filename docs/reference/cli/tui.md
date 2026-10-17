---
title: "sase tui"
description: "Open sase's TUI for agents, Patches, artifacts, notifications, and Services"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase tui

Open sase's TUI for agents, Patches, artifacts, notifications, and Services

Reference for `sase tui`. Run `sase tui --help` for the exact output on this checkout.

```text
usage: sase tui [-h] [query] [-m {large,small}] [-M {big,little}]
                [-p [PROFILE]] [-r REFRESH_INTERVAL] [-R]
                [-s SANITY_REFRESH_INTERVAL]
                [-t {artifacts,changespecs,patches,agents,services,axe}] [-T]
                [-x] [-v {git,hg,auto}]
```

Options:

| Option                                                                            | Description                                                                                                                                                                                                                                               | Default  |
| --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `-h`, `--help`                                                                    | show this help message and exit                                                                                                                                                                                                                           | —        |
| `-M MODEL_SIZE`, `--model-size MODEL_SIZE`                                        | Deprecated: use --model-tier instead (choices: `big`, `little`)                                                                                                                                                                                           | —        |
| `-m MODEL_TIER`, `--model-tier MODEL_TIER`                                        | Override model tier for ALL LLM provider instances (large or small) (choices: `large`, `small`)                                                                                                                                                           | —        |
| `-x`, `--no-service`, `--no-axe`                                                  | Disable auto-starting the service host on startup                                                                                                                                                                                                         | `false`  |
| `-p PROFILE`, `--profile PROFILE`                                                 | Profile the TUI session with pyinstrument. Optionally provide a file path for the output (default: $SASE_TMPDIR/ace_profile_<timestamp>.txt)                                                                                                              | —        |
| `-r REFRESH_INTERVAL`, `--refresh-interval REFRESH_INTERVAL`                      | Auto-refresh interval in seconds (default: 10, 0 to disable)                                                                                                                                                                                              | `10`     |
| `-R`, `--restart-service`, `--restart-axe`                                        | Restart the service host on startup (no-op if it is not running)                                                                                                                                                                                          | `false`  |
| `-s SANITY_REFRESH_INTERVAL`, `--sanity-refresh-interval SANITY_REFRESH_INTERVAL` | Full sanity-refresh interval in seconds (default: 300). Missed watcher or token changes are still reconciled at least this often.                                                                                                                         | `300`    |
| `-t TAB`, `--tab TAB`                                                             | Tab to focus on startup; 'services' is the Services tab ('axe' remains a legacy alias), and 'changespecs'/'patches' remain legacy aliases for 'artifacts' (default: agents) (choices: `agents`, `artifacts`, `axe`, `changespecs`, `patches`, `services`) | `agents` |
| `-T`, `--tmux`                                                                    | Launch the TUI in a new tmux window named 'sase_tmux_<N>' and print its session/window target on stdout. Useful for agents that need to drive the TUI via 'tmux send-keys' and observe it via 'tmux capture-pane'.                                        | `false`  |
| `-v VCS_PROVIDER`, `--vcs-provider VCS_PROVIDER`                                  | Override VCS provider ('git', 'hg', or 'auto' for auto-detection) (choices: `auto`, `git`, `hg`)                                                                                                                                                          | —        |

Arguments:

| Argument | Description                                                                                                                                                                                                       |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `query`  | Query string for filtering Patches (default: last used Patches query, first saved Patches query, or '!!!' for error suffixes). Examples: '"feature" AND "Ready"', '"myproject" OR "bugfix"', '!!! AND @myproject' |

Related: [CLI command groups](index.md).

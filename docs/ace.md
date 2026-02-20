# ACE TUI User Guide

## Overview

ACE (Agentic ChangeSpec Explorer) is the primary TUI for the SASE toolkit. It provides an interactive interface for
navigating, managing, and operating on ChangeSpecs, agents, and the Axe daemon.

## Launching

```bash
sase ace [QUERY] [options]
```

If no query is provided, the last used query is loaded (falling back to `!!!` for error suffixes).

### CLI Options

| Option                     | Description                                                    |
| -------------------------- | -------------------------------------------------------------- |
| `QUERY` (positional)       | Query string for filtering ChangeSpecs                         |
| `-m`, `--model-tier`       | Override model tier for all LLM providers (`large` or `small`) |
| `-r`, `--refresh-interval` | Auto-refresh interval in seconds (default: 10, 0 to disable)   |
| `--vcs-provider`           | Override VCS provider (`git`, `hg`, or `auto`)                 |
| `--agent`                  | Run in headless agent mode (returns JSON to stdout)            |
| `--keys`                   | Key names to press in agent mode (e.g., `j j Enter`)           |
| `--size`                   | Terminal size as WIDTHxHEIGHT for agent mode (default: 120x40) |

### Examples

```bash
sase ace                              # Last query or "!!!"
sase ace '"feature" AND "Drafted"'    # Filter by name and status
sase ace '@myproject'                 # Filter by project
sase ace -m small -r 30 '!!! OR @@@' # Small model, 30s refresh
```

### Agent Mode (Headless)

The `--agent` flag runs ACE headlessly and returns structured JSON output, useful for end-to-end testing and scripting:

```bash
sase ace --agent                          # See initial TUI state as JSON
sase ace --agent --keys j j               # Navigate down two items
sase ace --agent --keys slash             # Open query modal
sase ace --agent --keys tab               # Switch to agents tab
sase ace --agent --size 200x50 --keys j   # Custom terminal size
```

## Tab System

ACE has three tabs, cycled with `Tab` and `Shift+Tab`:

| Tab                   | Description                                                |
| --------------------- | ---------------------------------------------------------- |
| **CLs** (ChangeSpecs) | Browse and act on ChangeSpecs matching the current query   |
| **Agents**            | View running and completed agents, their files and prompts |
| **Axe**               | Monitor the Axe daemon and background commands             |

## Keybindings: CLs Tab

### Navigation

| Key                 | Action                                    |
| ------------------- | ----------------------------------------- |
| `j` / `k`           | Move to next / previous CL                |
| `<` / `>` / `~`     | Navigate to ancestor / child / sibling CL |
| `Ctrl+O` / `Ctrl+K` | Jump back / forward in CL history         |
| `Ctrl+D` / `Ctrl+U` | Scroll detail panel down / up (half page) |

### CL Actions

| Key           | Action                                                      |
| ------------- | ----------------------------------------------------------- |
| `s`           | Change status (opens status modal)                          |
| `S`           | Bulk status change for all marked CLs                       |
| `d`           | Show diff                                                   |
| `w`           | Reword CL description                                       |
| `W`           | Add tag to CL description                                   |
| `M`           | Mail CL (must have ready-to-mail suffix)                    |
| `e`           | Edit spec file                                              |
| `v`           | View files (hint mode)                                      |
| `h`           | Edit hooks                                                  |
| `H`           | Add hooks from failed targets                               |
| `a`           | Accept proposal (`!` = spec only, `@` = mark ready to mail) |
| `b`           | Rebase CL onto parent                                       |
| `R`           | Rewind to previous commit (non-Sub/Rev CLs only)            |
| `n`           | Rename CL (non-Sub/Rev CLs only)                            |
| `C`           | Checkout CL in primary workspace                            |
| `c` + `1`-`9` | Checkout CL in workspace 1-9                                |
| `T`           | Checkout CL + open tmux (primary workspace)                 |
| `t` + `1`-`9` | Checkout CL + open tmux in workspace 1-9                    |

### Marking

| Key | Action                                           |
| --- | ------------------------------------------------ |
| `m` | Mark / unmark current CL (auto-advances to next) |
| `u` | Clear all marks                                  |

### Fold Mode (`z` prefix)

| Key     | Action                 |
| ------- | ---------------------- |
| `z` `c` | Toggle commits section |
| `z` `h` | Toggle hooks section   |
| `z` `m` | Toggle mentors section |
| `z` `z` | Toggle all sections    |

### Workflows and Agents

| Key     | Action                                          |
| ------- | ----------------------------------------------- |
| `r`     | Run workflow on current CL                      |
| `@`     | Run a custom agent (opens project/CL selection) |
| `Space` | Run agent from current CL                       |
| `!`     | Run background command                          |

### Leader Mode (`,` prefix)

| Key     | Action                               |
| ------- | ------------------------------------ |
| `,` `!` | Run command using current CL context |

### Copy Mode (`%` prefix)

| Key     | Action                     |
| ------- | -------------------------- |
| `%` `%` | Copy ChangeSpec            |
| `%` `!` | Copy ChangeSpec + snapshot |
| `%` `b` | Copy bug number            |
| `%` `c` | Copy CL number             |
| `%` `n` | Copy CL name               |
| `%` `p` | Copy project spec file     |
| `%` `s` | Copy sase ace snapshot     |

## Keybindings: Agents Tab

### Navigation

| Key                 | Action                            |
| ------------------- | --------------------------------- |
| `j` / `k`           | Move to next / previous agent     |
| `g` / `G`           | Scroll file panel to top / bottom |
| `Ctrl+D` / `Ctrl+U` | Scroll file panel down / up       |
| `Ctrl+F` / `Ctrl+B` | Scroll prompt panel down / up     |

### Agent Actions

| Key | Action                                       |
| --- | -------------------------------------------- |
| `@` | Run custom agent                             |
| `!` | Run background command                       |
| `r` | Revive chat as agent                         |
| `x` | Kill / dismiss agent                         |
| `e` | Edit chat in editor                          |
| `p` | Toggle file / prompt layout                  |
| `i` | Toggle thinking / file panel (context-aware) |

### Workflow Folding

| Key       | Action                           |
| --------- | -------------------------------- |
| `l` / `h` | Expand / collapse workflow steps |
| `L` / `H` | Expand / collapse all workflows  |

### Copy Mode (`%` prefix)

| Key     | Action                 |
| ------- | ---------------------- |
| `%` `c` | Copy chat file path    |
| `%` `s` | Copy sase ace snapshot |

## Keybindings: Axe Tab

### Navigation

| Key       | Action                              |
| --------- | ----------------------------------- |
| `j` / `k` | Move to next / previous command     |
| `g`       | Scroll to top                       |
| `G`       | Scroll to bottom (pins auto-scroll) |
| `r`       | Show runners info                   |

### Background Commands

| Key | Action                               |
| --- | ------------------------------------ |
| `@` | Run agent                            |
| `!` | Run background command               |
| `X` | Kill current command (or toggle axe) |

### Copy Mode (`%` prefix)

| Key     | Action                 |
| ------- | ---------------------- |
| `%` `o` | Copy visible output    |
| `%` `O` | Copy full output       |
| `%` `s` | Copy sase ace snapshot |

### Axe Control

| Key | Action                  |
| --- | ----------------------- |
| `x` | Clear output            |
| `X` | Start / stop axe daemon |
| `Q` | Stop axe and quit       |

## Query System

### Editing Queries

Press `/` to open the query editor. The current canonical query is pre-filled.

To save a query, prefix with `#`:

- `#3 "myproject"` -- save to slot 3
- `# "myproject"` -- save to next available slot
- `#3` (no query) -- delete slot 3

### Saved Queries

Press `1`-`9` or `0` to instantly load a saved query. These also work from within the help modal (`?`).

### Query History

| Key | Action                                |
| --- | ------------------------------------- |
| `^` | Navigate to previous query in history |
| `_` | Navigate to next query in history     |

Query history is available on the CLs tab and tracks queries as you switch between them.

## Global Keybindings

These work on all tabs:

| Key                 | Action                                                                     |
| ------------------- | -------------------------------------------------------------------------- |
| `Tab` / `Shift+Tab` | Switch between CLs, Agents, and Axe tabs                                   |
| `.`                 | Toggle visibility of reverted CLs (CLs tab) or non-run agents (Agents tab) |
| `N`                 | Show notifications                                                         |
| `X`                 | Start / stop axe daemon (or select process)                                |
| `Q`                 | Stop axe daemon and quit                                                   |
| `y`                 | Refresh current tab                                                        |
| `Y`                 | Sync workspace (CLs tab)                                                   |
| `q`                 | Quit                                                                       |
| `?`                 | Show help modal                                                            |

## Auto-Refresh

ACE auto-refreshes data at a configurable interval (default: 10 seconds). The remaining time until the next refresh is
shown in the info panel. Set `--refresh-interval 0` to disable.

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

| Key             | Action                                                      |
| --------------- | ----------------------------------------------------------- |
| `a`             | Accept proposal (`!` = spec only, `@` = mark ready to mail) |
| `b`             | Rebase CL onto parent                                       |
| `C` / `c1`-`c9` | Checkout CL (primary / workspace 1-9)                       |
| `d`             | Show diff                                                   |
| `e`             | Edit spec file                                              |
| `h`             | Edit hooks                                                  |
| `H`             | Add hooks from failed targets                               |
| `M`             | Mail CL                                                     |
| `m`             | Mark / unmark current CL (auto-advances to next)            |
| `n`             | Rename CL (non-Sub/Rev CLs only)                            |
| `R`             | Rewind to previous commit (non-Sub/Rev CLs only)            |
| `s`             | Change status (opens status modal)                          |
| `S`             | Bulk status change for all marked CLs                       |
| `T` / `t1`-`t9` | Checkout + tmux (primary / workspace 1-9)                   |
| `u`             | Clear all marks                                             |
| `v`             | View files (hint mode)                                      |
| `w`             | Reword CL description                                       |
| `W`             | Add tag to CL description                                   |
| `Y`             | Sync workspace                                              |

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
| `L`     | Open agent run log modal                        |
| `r`     | Run workflow on current CL                      |
| `@`     | Run a custom agent (opens project/CL selection) |
| `Space` | Run agent from current CL                       |

### Bang Mode (`!` prefix)

| Key  | Action                                            |
| ---- | ------------------------------------------------- |
| `!!` | Run background command (opens hook history modal) |
| `!x` | Start / stop axe (or select process)              |

### Hook History Modal

Pressing `!!` opens the hook history modal showing previously run background commands:

| Key         | Action                                     |
| ----------- | ------------------------------------------ |
| `j` / `k`   | Navigate through hook history              |
| `Enter`     | Select and execute highlighted hook        |
| `Ctrl+D`    | Delete highlighted hook from history       |
| `Ctrl+G`    | Edit first — select hook and open in input |
| `Esc` / `q` | Cancel and close modal                     |

The modal supports live filtering as you type in the search box and displays last-used timestamps for each hook.

### Leader Mode (`,` prefix)

| Key        | Action                                              |
| ---------- | --------------------------------------------------- |
| `,!`       | Run command using current CL context                |
| `,h`       | Run agent (home directory)                          |
| `,m`       | Kill running mentors                                |
| `,r`       | Show runners info                                   |
| `,<space>` | Run agent from current CL (skips project selection) |

### Copy Mode (`%` prefix)

| Key  | Action                     |
| ---- | -------------------------- |
| `%%` | Copy ChangeSpec            |
| `%!` | Copy ChangeSpec + snapshot |
| `%b` | Copy bug number            |
| `%c` | Copy CL number             |
| `%n` | Copy CL name               |
| `%p` | Copy project spec file     |
| `%s` | Copy sase ace snapshot     |

## Keybindings: Agents Tab

### Navigation

| Key                 | Action                                                     |
| ------------------- | ---------------------------------------------------------- |
| `j` / `k`           | Move to next / previous agent                              |
| `g` / `G`           | Scroll to top / bottom (file, thinking, or metadata panel) |
| `Ctrl+D` / `Ctrl+U` | Scroll file panel down / up                                |
| `Ctrl+F` / `Ctrl+B` | Scroll prompt panel down / up                              |

### Agent Actions

| Key                 | Action                                                       |
| ------------------- | ------------------------------------------------------------ |
| `@`                 | Run custom agent                                             |
| `a`                 | Toggle auto-approve / answer HITL                            |
| `n`                 | Name agent                                                   |
| `r`                 | Resume agent (by name if running, by chat file if completed) |
| `v`                 | View files (hint mode)                                       |
| `w`                 | Unwait a WAITING agent (run immediately)                     |
| `x`                 | Kill / dismiss agent                                         |
| `e`                 | Edit chat in editor                                          |
| `E`                 | Edit panel content in editor                                 |
| `]` / `[`           | Cycle panels: file → thinking → metadata (forward / reverse) |
| `p`                 | Toggle file / prompt layout                                  |
| `Ctrl+N` / `Ctrl+P` | Next / previous file in panel                                |
| `-`                 | Reset file trim to default                                   |
| `=`                 | Show all file lines                                          |

### Workflow Folding

| Key       | Action                           |
| --------- | -------------------------------- |
| `l` / `h` | Expand / collapse workflow steps |
| `L` / `H` | Expand / collapse all workflows  |

### Leader Mode (`,` prefix)

| Key        | Action                                              |
| ---------- | --------------------------------------------------- |
| `,r`       | Show runners info                                   |
| `,<space>` | Run agent from current agent's CL (skips selection) |

### Bang Mode (`!` prefix)

| Key  | Action                               |
| ---- | ------------------------------------ |
| `!!` | Run background command               |
| `!x` | Start / stop axe (or select process) |

### Copy Mode (`%` prefix)

| Key  | Action                 |
| ---- | ---------------------- |
| `%c` | Copy chat file path    |
| `%E` | Copy file path         |
| `%s` | Copy sase ace snapshot |

## Keybindings: Axe Tab

### Navigation

| Key                 | Action                              |
| ------------------- | ----------------------------------- |
| `j` / `k`           | Move to next / previous command     |
| `Ctrl+N` / `Ctrl+P` | Next / previous jack output         |
| `g`                 | Scroll to top                       |
| `G`                 | Scroll to bottom (pins auto-scroll) |

### Commands

| Key | Action                           |
| --- | -------------------------------- |
| `@` | Run agent                        |
| `x` | Start / stop axe (or kill bgcmd) |
| `X` | Clear output                     |

### Leader Mode (`,` prefix)

| Key        | Action                                           |
| ---------- | ------------------------------------------------ |
| `,r`       | Show runners info                                |
| `,<space>` | Run agent from current context (skips selection) |

### Bang Mode (`!` prefix)

| Key  | Action                               |
| ---- | ------------------------------------ |
| `!!` | Run background command               |
| `!x` | Start / stop axe (or select process) |

### Copy Mode (`%` prefix)

| Key  | Action                 |
| ---- | ---------------------- |
| `%o` | Copy visible output    |
| `%O` | Copy full output       |
| `%s` | Copy sase ace snapshot |

### Axe Control

| Key | Action            |
| --- | ----------------- |
| `Q` | Stop axe and quit |

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

| Key                 | Action                                                                            |
| ------------------- | --------------------------------------------------------------------------------- |
| `Tab` / `Shift+Tab` | Switch between CLs, Agents, and Axe tabs                                          |
| `#`                 | Open XPrompt Browser (see [XPrompt Browser](#xprompt-browser) below)              |
| `.`                 | Toggle visibility of hidden items (reverted CLs, non-run agents, or axe commands) |
| `i`                 | Mark user as inactive (shows IDLE indicator; any keypress re-activates)           |
| `N`                 | Show notifications                                                                |
| `Q`                 | Stop axe daemon and quit                                                          |
| `y`                 | Refresh current tab                                                               |
| `q`                 | Quit                                                                              |
| `?`                 | Show help modal                                                                   |

## XPrompt Browser

Press `#` on any tab to open the XPrompt Browser modal. It displays all discovered xprompts in a two-panel layout: a
filterable list on the left and a syntax-highlighted preview on the right.

Xprompts are grouped by source (CWD `.xprompts/`, CWD `xprompts/`, Home `~/.xprompts/`, Home `~/xprompts/`,
project-specific, config `sase.yml`, plugins, built-in). Workflow xprompts (multi-step YAML) are marked with a gear
icon.

### Keybindings

| Key      | Action                                |
| -------- | ------------------------------------- |
| `Ctrl+N` | Navigate to next xprompt              |
| `Ctrl+P` | Navigate to previous xprompt          |
| `Ctrl+D` | Scroll preview panel down             |
| `Ctrl+U` | Scroll preview panel up / clear input |
| `Enter`  | Edit highlighted xprompt in `$EDITOR` |
| `Ctrl+O` | Add a new xprompt                     |
| `Esc`    | Close browser                         |

Type in the filter input to narrow the list in real time.

## Idle Detection

ACE tracks user activity and displays an orange **IDLE** badge in the top bar when the user has been inactive for longer
than the configured threshold (`ace.inactive_seconds`, default: 600 seconds). The badge is also shown when the user
presses `i` to manually mark themselves as inactive.

Any keypress re-activates the user and hides the badge. External tools (e.g., chop scripts) can call `is_idle()` from
`sase.ace.tui_activity` to check idle status programmatically.

## Agent Run Log Modal

Press `L` on the CLs tab to open the agent run log modal. It shows all agents (running, completed, and dismissed) that
have been associated with the current CL.

| Key         | Action                      |
| ----------- | --------------------------- |
| `j` / `k`   | Navigate through agent list |
| `Enter`     | Jump to agent in Agents tab |
| `Esc` / `q` | Close modal                 |

## Tab Bar Display

The tab bar shows contextual counts alongside each tab label using the format `(MxD.H)`:

- **M** — main count (CLs, running agents, or running jacks)
- **x*D*** — done/completed count (separated by `x`)
- **._H_** — hidden count, shown when hidden items are visible (separated by `.`)

Examples:

- **CLs tab**: `CLs (5)` for 5 CLs, or `CLs (5.2)` when 2 hidden (reverted) CLs are visible
- **Agents tab**: `Agents (2)` for 2 running agents, `Agents (2x1)` for 2 running + 1 done, `Agents (2x1.3)` with 3
  hidden also visible
- **AXE tab**: `AXE (3)` for 3 running jacks, `AXE (3x2.1)` for 3 jacks + 2 done bgcmds + 1 hidden command visible

## File Panel Trimming

When viewing agent files on the Agents tab, large files are automatically trimmed to fit the visible viewport. A blue
indicator shows "N more lines below" when content is trimmed. Trim controls (`-`, `=`) are listed in the
[Agent Actions](#agent-actions) keybindings above. Trim state is preserved when switching between agents or refreshing
data.

## Agent Auto-Naming

All agents are automatically assigned a short alphabetic name (`a`, `b`, ..., `z`, `aa`, `ab`, ...) when launched
without an explicit `%name` directive. Names are allocated sequentially, reusing names from dismissed agents. This
enables the resume-by-name workflow: press `r` on a running named agent to queue a follow-up that waits for it to finish
and then loads its conversation history.

## Agents Tab Metadata Panel

The Agents tab metadata panel (cycled to via `]`/`[`) shows structured information about the selected agent:

- **Agent details**: Name, status, model, provider, CL association, timestamps
- **AGENT REPLY**: The agent's live or completed reply content, streamed from `live_reply.md` during execution and read
  from the artifacts directory after completion

When the file or thinking panel is empty, the `g`/`G` keys automatically fall back to scrolling the metadata panel.

## Custom Keymaps

All TUI keybindings are configurable via the `ace.keymaps` section in `sase.yml`. You can remap any built-in key and
define entirely new prefix-key modes.

### Remapping Built-in Keys

Override any app-level keybinding under `ace.keymaps.app`:

```yaml
ace:
  keymaps:
    app:
      next_changespec: "n" # Remap j → n
      prev_changespec: "p" # Remap k → p
      mark_inactive: "I" # Remap i → I
```

### Custom Modes

Define user-defined prefix-key modes under `ace.keymaps.modes`. Each custom mode has a `prefix` key and a `keys` dict
where each sub-key specifies either a `shell` command or a built-in `action`:

```yaml
ace:
  keymaps:
    modes:
      my_mode:
        prefix: ";"
        keys:
          run_tests:
            key: "t"
            shell: "just test"
          show_log:
            key: "l"
            shell: "git log --oneline -20"
          refresh:
            key: "r"
            action: "refresh"
```

Pressing `;` activates the mode, then pressing `t` runs `just test`, `l` shows the git log, etc.

### Validation

The keymap loader validates all configuration:

- **Invalid keys** are reverted to their defaults with a warning
- **Duplicate keys** (two actions bound to the same key) are detected and the conflicting override is reverted
- **Prefix conflicts** between custom mode prefixes and existing app bindings are warned

See [`docs/configuration.md`](configuration.md) for the full `ace.keymaps` configuration reference.

## Auto-Refresh

ACE auto-refreshes data at a configurable interval (default: 10 seconds). The remaining time until the next refresh is
shown in the info panel. Set `--refresh-interval 0` to disable.

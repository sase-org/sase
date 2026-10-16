---
title: Launching the TUI
description: How to start sase tui, including CLI options, screenshots, and clipboard transports.
---

# Launching the TUI

This page lists how to start the sase TUI, its CLI options, screenshot capture, and
clipboard transports.

## Launching

```bash
sase tui [QUERY] [options]
```

Run `sase tui` from an interactive terminal. It opens on the Agents tab and starts the
service host (pass `-x` to skip that). Press `?` on any tab for the keymap and a short
guide, `:` for the [Command Line](global-controls.md#command-line), `;` for the
[Command Palette](global-controls.md#command-palette), and `q` to quit. The command was previously
`sase ace`, which no longer exists; the TUI's settings still live under the `ace:`
section of `sase.yml` (for example `ace.keymaps` and `ace.page_size`).

If no Patches query is provided, sase's TUI loads the last used Patches query, then the
first saved Patches query, then falls back to `!!!` for error suffixes. The top-level
Agents tab restores its own last submitted Agents query after startup.

### CLI Options

| Option                                     | Description                                                                                                                                                  |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `QUERY` (positional)                       | Query string for filtering Patches                                                                                                                           |
| `-m`, `--model-tier`                       | Override model tier for all LLM providers (`large` or `small`)                                                                                               |
| `-M`, `--model-size`                       | Deprecated alias for `--model-tier` (`big` or `little`)                                                                                                      |
| `-p`, `--profile [PATH]`                   | Profile the TUI session with pyinstrument; optional output path                                                                                              |
| `-r`, `--refresh-interval`                 | Auto-refresh interval in seconds (default: 10, 0 to disable)                                                                                                 |
| `-s`, `--sanity-refresh-interval`          | Full sanity-refresh interval in seconds (default: 300); see [Auto-Refresh](global-controls.md#auto-refresh)                                                                    |
| `-x`, `--no-service`, `--no-axe`           | Disable auto-starting the service host on startup                                                                                                            |
| `-v`, `--vcs-provider`                     | Override VCS provider (`git`, `hg`, or `auto`)                                                                                                               |
| `-R`, `--restart-service`, `--restart-axe` | Restart an already-running service host on startup (no-op if it is not running)                                                                              |
| `-t`, `--tab`                              | Tab to focus on startup (`agents` by default, `artifacts`, or `services`; `axe` is a compatibility alias, and `changespecs` and `patches` alias `artifacts`) |
| `-T`, `--tmux`                             | Launch sase's TUI in a new tmux window and print the target for external control                                                                             |

When profiling is enabled, sase's TUI writes text output to `PATH`. If `PATH` is
omitted, it uses the managed temp tree:
`$SASE_TMPDIR/ace-profiles/ace_profile_<timestamp>.txt` when `SASE_TMPDIR` is set, or
`$SASE_HOME/tmp/ace-profiles/ace_profile_<timestamp>.txt` otherwise (`SASE_HOME`
defaults to `~/.sase`). On exit, sase's TUI prints the shortened path and copies it when
a clipboard tool is available.

### Examples

```bash
sase tui                              # Last query, first saved query, or "!!!"
sase tui '"feature" AND "Drafted"'    # Filter by name and status
sase tui '+myproject'                 # Filter by project
sase tui -m small -r 30 '!!! OR @@@' # Small model, 30s refresh
```

When `--profile` is enabled, sase's TUI prints a shortened profile-output path after the
TUI exits and tries to copy that shortened path to the system clipboard (`pbcopy`,
`wl-copy`, `xclip`, or `xsel` when available).

### Agent Screenshots

Use `sase screenshot` when you need a PNG of the real TUI state an agent would see. The
command starts `sase tui` in the detached `sase_ace_agents` tmux session at `120x40`,
waits for the screen to paint, sends optional tmux keys, asks the live app to export
SVG, then rasterizes that SVG with the same bundled-font renderer used by the golden PNG
suite.

```bash
sase screenshot -o /tmp/sase.png
sase screenshot -p j -p j -w 'Ready' -o /tmp/sase.png
sase screenshot -p / -w INSERT --type 'machine:apollo' -w 'machine:apollo' -p enter -o /tmp/sase.png
sase screenshot --host apollo -o /tmp/sase-remote.png
sase screenshot --keep -- -t services
sase screenshot --window sase_ace_agents:sase_tmux_1 -o /tmp/sase-again.png
```

Repeatable `-p/--press`, `-T/--type`, and `-w/--wait-for` form one argv-ordered input
script, so a query filter can be typed and submitted without a second `--window`
capture. `--type` sends literal TUI text (`tmux send-keys -l`). Send the query key as a
literal `-p /`: tmux has no `slash` key name, so `-p slash` types the letters `slash`.
Wait for the input to open (`-w INSERT`) before typing, and wait for the typed text
before `-p enter`.

By default, the tmux window is killed after capture. Pass `--keep` to leave it running,
drive it manually with `tmux send-keys`, and recapture it later with `--window`. The
command pins TUI animations off and uses truecolor terminal defaults, but it still shows
live machine state and timestamps by design. If capture times out, the error includes
the final `tmux capture-pane` text so you can see what the TUI was showing.

Pass `--host` to run the live TUI and SVG export on an enrolled machine alias or any raw
SSH destination, then fetch the SVG and rasterize it locally. Enrollment only supplies a
convenient `ssh_target`; SSH itself is full shell access and uses your normal SSH trust
boundary, not gateway-scoped credentials. Remote screenshots show that machine's
installed `sase` and state, not your local working tree. The remote `sase` commands run
through the account's noninteractive login shell so tools installed under login-profile
paths such as `~/.local/bin` can be found without allocating a terminal. Check the
printed `remote_sase_version=sase <version>` line when comparing results; it is read
from `sase version --json` on the remote host. A remote host needs `sase`, `tmux`, and
SSH access, but it does not need the local visual rasterizer dependencies.

### Clipboard Transports

Every copy inside sase's TUI runs in the background and tries both a verifiable system
transport and OSC 52 for the client terminal. Inside tmux, sase's TUI tries
`tmux load-buffer -w -` first; otherwise the system candidates are `pbcopy`, `wl-copy`,
`xclip`, and `xsel` as appropriate for the platform and display environment. A plain
`Copied …` toast means a subprocess transport confirmed success, while
`Copied … (OSC 52)` means sase's TUI emitted the terminal escape sequence without a
verifiable subprocess result. OSC 52 payloads above the terminal-safe size limit are
skipped. If neither transport works, sase's TUI opens the generated text in a read-only
fallback view so it can still be selected and recovered.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Global controls](global-controls.md) — command palette, command line, auto-refresh.
- [TUI keymaps](keymaps.md) — generated keymap defaults.

## `sase screenshot`

Capture a PNG from a real `sase tui` running in tmux. The command launches in the
detached `sase_ace_agents` session unless `--window` names an existing tmux target. See
[Agent screenshots](#agent-screenshots).

<a id="cli-options-1"></a>
Moved to [sase screenshot](launching.md#sase-screenshot).

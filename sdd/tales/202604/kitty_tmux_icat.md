---
create_time: 2026-04-30 01:53:30
status: done
prompt: sdd/prompts/202604/kitty_tmux_icat.md
---
# Plan: Make Kitty `icat` Work Reliably In `tm` Sessions

## Context

Kitty image display works outside tmux, but inside `tm`/tmuxinator sessions the terminal path currently does not expose
a real Kitty client to tmux. Diagnostics showed:

- `tmux 3.5a`, new enough for passthrough.
- `allow-passthrough on` is already configured.
- The attached tmux client reports `client_termname=tmux-256color`, not `xterm-kitty`.
- `kitten icat --detect-support` fails because the graphics/query escapes are not reaching a Kitty terminal.
- `tm` resolves to `~/.local/bin/tm`, a pipx-managed `tmux-utils` script. The script calls
  `tmuxinator start "$SESSION_NAME" ...`; when `TMUX` is empty, tmuxinator attaches immediately, so the script's later
  custom attach logic is not reached.

Kitty's `icat` supports tmux passthrough detection, and tmux supports DCS passthrough with `allow-passthrough`, but both
require the tmux client to ultimately be attached to a terminal that understands the Kitty graphics protocol. A client
attached through another tmux layer is not equivalent to a Kitty client.

## Goal

Make future `tm <session>` launches create or switch to tmux sessions through a Kitty-capable attachment path when
available, and prevent silently creating tmux clients through an outer tmux layer where Kitty graphics cannot work.

## Proposed Changes

1. Add a chezmoi-managed `~/bin/tm` wrapper so it appears earlier in `PATH` than the pipx-managed `~/.local/bin/tm`.

2. Keep compatibility with the existing `tm` interface:
   - Preserve `-h/--help`, `-d/--debug`, `-v/--verbose`.
   - Preserve delegated `tmuxinator` commands such as `tm -edit`.
   - Preserve automatic project file creation from `~/.config/tmuxinator/default.yml`.
   - Preserve optional alternate socket handling if a second positional argument is passed.

3. Change the session startup flow:
   - Run `tmuxinator start --no-attach "$SESSION_NAME" root="$root"` so `tm` owns the attach/switch step.
   - If already inside tmux, use `tmux switch-client -t "$SESSION_NAME"` as before.
   - If outside tmux, use `exec tmux -u attach-session -d -t "$SESSION_NAME"` so the active terminal becomes the
     controlling tmux client and stale attached clients do not constrain the session.

4. Add a nested-terminal guard:
   - Before attaching from outside tmux, inspect `$TERM` and `$TERM_PROGRAM`.
   - If they indicate the shell is already under a tmux/screen-style terminal, print a short actionable warning that
     Kitty graphics will not work through this attach path.
   - Prefer failing before attaching over silently creating another `client_termname=tmux-256color` client.
   - Allow an explicit override environment variable for rare cases where the user knowingly wants the old behavior.

5. Tighten tmux passthrough config:
   - Keep passthrough enabled.
   - Consider `allow-passthrough all` instead of `on` so passthrough is not limited by tmux visibility checks.
   - Add a focused comment explaining this is for Kitty graphics protocol passthrough.

6. Verification:
   - Run shell syntax checks on the new wrapper.
   - Run `just check` in the chezmoi repo because that repo will be modified.
   - Apply the chezmoi changes with `chezmoi apply --force` after verification.
   - Confirm `zsh -lic 'whence -v tm'` resolves to `~/bin/tm`.
   - Confirm the tmux config reports passthrough enabled.

## Expected User Test

From a fresh Kitty shell, not already inside local tmux:

```sh
tm sase
tmux display-message -p 'client_termname=#{client_termname} client_termfeatures=#{client_termfeatures}'
kitten icat docs/images/sase-component-communication.png
kitten icat --passthrough tmux --transfer-mode stream docs/images/sase-component-communication.png
```

The key success condition is `client_termname=xterm-kitty` or another Kitty-capable terminal name. If it still says
`tmux-256color`, the session is being attached through an outer tmux layer and Kitty graphics cannot be made reliable by
remote tmux config alone.

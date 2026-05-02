---
create_time: 2026-04-30 10:48:45
status: done
prompt: sdd/prompts/202604/tm_kitty_terminal_fix.md
---
# Plan: Fix `tm` startup under Kitty across machines

## Context

The recent `tm` wrapper change intentionally prevents attaching a tmux client from a nested tmux/screen-style terminal,
because Kitty graphics passthrough only works reliably when the tmux client is attached from a Kitty-capable outer
terminal. The failing machine shows two separate symptoms:

- A plain `tm sase` reports `TERM=tmux-256color` and refuses to attach.
- Forcing `TERM=xterm-kitty tm sase` bypasses that guard, but zsh/tmux/ncurses cannot resolve `xterm-kitty`.

The dotfiles currently export `TERM=tmux-256color` globally from `home/dot_profile`, while tmux itself already sets
`default-terminal "tmux-256color"` in `home/dot_config/tmux/tmux.conf`. This global override makes fresh shells outside
tmux look like tmux clients. The other machine also lacks usable `xterm-kitty` terminfo.

## Goals

- Let the outer terminal set `TERM`, so Kitty shells keep `TERM=xterm-kitty` instead of being rewritten to
  `tmux-256color`.
- Keep tmux panes using `tmux-256color` through tmux configuration, where that setting belongs.
- Make fresh-machine bootstrap behavior clear when Kitty terminfo is missing.
- Preserve the useful nested-terminal protection in `tm`.
- Validate the change in the chezmoi repo before applying it.

## Proposed Changes

1. Remove the global `export TERM=tmux-256color` from `home/dot_profile`.
   - Do not replace it with another global `TERM` assignment.
   - If a fallback is needed for non-graphical console environments, make it narrowly scoped and avoid overriding an
     already-set `TERM`.

2. Leave `home/dot_config/tmux/tmux.conf` as the source of tmux's internal terminal type.
   - Keep `set -g default-terminal "tmux-256color"`.
   - Keep `set -g allow-passthrough all` for Kitty graphics passthrough.

3. Add a small machine bootstrap/check for Kitty terminfo.
   - Prefer an idempotent chezmoi script that checks `infocmp xterm-kitty`.
   - If terminfo is missing and `kitty` is installed, install the local Kitty terminfo into the user's terminfo
     database.
   - If terminfo is still unavailable, emit an actionable warning naming the expected fixes: install the distribution's
     Kitty/kitty-terminfo package, use `kitty +kitten ssh` for remote shells, or otherwise install the `xterm-kitty`
     terminfo entry.
   - Keep this script non-fatal so non-Kitty machines and headless hosts are not blocked by `chezmoi apply`.

4. Tighten `tm` diagnostics without weakening the guard.
   - Keep the `TM_ALLOW_NESTED=1` bypass.
   - Consider changing the message to call out a likely global `TERM` override when `$TMUX` is unset but `TERM` starts
     with `tmux` or `screen`.
   - Avoid adding logic that silently attaches from an environment known to be bad for Kitty graphics.

5. Add focused tests if practical.
   - A bash test can exercise the guard behavior by sourcing or invoking a testable helper if the script can be made
     test-friendly without a broad refactor.
   - At minimum, add a shell/static validation step for the changed scripts and rely on existing `just check`.

## Validation

Run these in `/home/bryan/.local/share/chezmoi` after implementation:

- `git status --short` before and after edits, to distinguish planned changes from existing work.
- `just check`, as required by the external-repo memory for chezmoi changes.
- A local smoke check:
  - `env -u TMUX TERM=xterm-kitty /path/to/tm <session>` should not trip the nested-terminal guard when terminfo exists.
  - `env -u TMUX TERM=tmux-256color /path/to/tm <session>` should still refuse unless `TM_ALLOW_NESTED=1`.
  - `infocmp xterm-kitty` should succeed on a Kitty-capable machine after bootstrap.

After the user asks to apply the implementation:

- Run `chezmoi apply --force` after committing, per project memory.
- On the failing machine, update/apply dotfiles, open a new Kitty shell outside tmux, and verify:
  - `echo "$TERM"` reports `xterm-kitty`.
  - `infocmp xterm-kitty` succeeds.
  - `tm sase` attaches without the nested-terminal refusal.

## Risks and Tradeoffs

- Removing the global `TERM` override can reveal machines with incomplete terminal setup. That is desirable: terminal
  identity should come from the terminal emulator or tmux, not from `.profile`.
- Automatically installing Kitty terminfo is distribution-dependent. The safest implementation is best-effort and
  idempotent, with a clear warning rather than a hard failure.
- Testing the full `tm` path is awkward because it starts real tmuxinator/tmux sessions. Keep automated tests focused on
  environment classification and validate the full path with smoke commands.

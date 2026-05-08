---
create_time: 2026-05-08 17:52:36
status: done
prompt: sdd/prompts/202605/disable_kitty_cmd_f.md
---
# Plan: Disable Kitty cmd+f Interception for SASE Prompt Word Navigation

## Context

The previous SASE app change added prompt-local `alt+f` and `alt+b` bindings in
`src/sase/ace/tui/widgets/prompt_text_area.py`, with tests covering both Textual synthetic `alt+*` input and raw
terminal `ESC f` / `ESC b` sequences. The new failure is upstream of the app: on macOS kitty binds `cmd+f` to its own
`search_scrollback` action, so the key never reaches the SASE Textual app as the word-forward Meta sequence.

Kitty's official config documentation lists:

- `map cmd+f search_scrollback` as a default scrollback search shortcut.
- `no_op` as the supported way to unbind a shortcut so kitty stops intercepting the key and passes it through to the
  child program.

This repo does not own kitty config directly. The managed kitty config lives in the chezmoi repo at:

- `/home/bryan/.local/share/chezmoi/home/dot_config/kitty/kitty.conf`

The active generated config at `~/.config/kitty/kitty.conf` currently matches the managed file and only contains theme
inclusion, bell settings, and one `ctrl+shift+y` kitten binding. The chezmoi repo also has an onchange script that
reloads kitty by sending `SIGUSR1` when kitty config files change.

## Goal

Make `<cmd+f>` usable as SASE prompt forward-word navigation in kitty by disabling kitty's default `cmd+f` scrollback
search binding, without changing the SASE TUI keymap again.

## Proposed Change

Update the chezmoi-managed kitty config:

```conf
# Let terminal apps receive Cmd+F, e.g. SASE prompt word-forward navigation.
map cmd+f no_op
```

Place the line near the existing explicit kitty keymap in `home/dot_config/kitty/kitty.conf` so local shortcut overrides
stay grouped.

I would not add a `cmd+b` override. The user reported `cmd+b` already works, and kitty's documented default conflict
here is specifically `cmd+f`. Keeping the change narrow avoids unnecessarily changing unrelated terminal behavior.

## Validation Plan

1. Inspect the diff in the chezmoi repo and confirm it only changes `home/dot_config/kitty/kitty.conf`.
2. Run `just check` in `/home/bryan/.local/share/chezmoi`, per the external repo memory instructions for chezmoi
   changes.
3. Run `chezmoi diff ~/.config/kitty/kitty.conf` or equivalent to verify the target config would receive the new
   mapping.
4. Run `chezmoi apply --force ~/.config/kitty/kitty.conf` so the managed file is copied into the live kitty config. This
   should trigger the existing kitty reload script if the template hash changes.
5. Verify `~/.config/kitty/kitty.conf` contains `map cmd+f no_op`.

## Manual Acceptance Check

After the config is applied and kitty is reloaded, open a fresh or reloaded kitty window running SASE, focus the prompt,
put the cursor at the start of `alpha beta`, and press `<cmd+f>`. Expected behavior: the cursor moves to the end of
`alpha` instead of opening kitty scrollback search.

If the existing kitty process still handles `cmd+f` as search after `chezmoi apply`, restart kitty once. That would
indicate the running process did not pick up the reload signal, not that the config line is wrong.

## Risks and Tradeoffs

- This removes kitty scrollback search on `<cmd+f>` globally for this kitty profile. Kitty scrollback search remains
  available through its other default shortcut, `ctrl+shift+/`, unless that is overridden elsewhere.
- `cmd+f` pass-through semantics depend on kitty's macOS modifier handling. The SASE app already validates the terminal
  input path for `ESC f`, so once kitty passes the key through, the app-side behavior is covered.
- No SASE source or default keymap updates should be needed. The prior app binding is already present and tested.

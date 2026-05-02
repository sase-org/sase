---
create_time: 2026-04-29 19:46:23
status: done
prompt: sdd/prompts/202604/semicolon_command_palette.md
---
# Plan: Make `;` Also Open the Ace Command Palette

## Context

The ace TUI command palette is currently an app-level keymap action:

- `src/sase/default_config.yml` sets `ace.keymaps.app.open_command_palette: "colon"`.
- `src/sase/ace/tui/keymaps/loader.py` turns each app keymap into a Textual `Binding`.
- Textual `Binding` supports comma-separated key alternatives, so one action can be bound to multiple physical keys with
  a single binding string such as `"colon,semicolon"`.
- The command palette catalog, help modal, and tests derive display text from the same keymap registry, so a default
  change needs display/validation support rather than only adding a second hardcoded binding.

## Goal

Pressing either `:` or `;` opens the same command palette from every ace TUI tab, while keeping `open_command_palette`
as one configurable command.

## Approach

1. Add first-class support for comma-separated key alternatives in the keymap layer.
   - Extend key validation so a keymap value such as `"colon,semicolon"` is valid when every segment is a valid Textual
     key.
   - Split compound bindings during duplicate/conflict detection so `semicolon` still conflicts with any other app
     action or custom mode prefix that tries to claim it.
   - Keep existing single-key behavior unchanged.

2. Change the bundled default keymap.
   - Update `src/sase/default_config.yml` from `open_command_palette: "colon"` to
     `open_command_palette: "colon,semicolon"`.
   - Do not add a new `AppKeymaps` field or new command id; this remains the existing `app.open_command_palette` action.

3. Make display surfaces readable.
   - Update key display formatting so compound app bindings render as `: / ;` in the command palette catalog and help
     modal.
   - Preserve existing formatting for true multi-step mode sequences such as `%n`, `,t`, and `Ctrl+D x`.

4. Add regression coverage.
   - Unit tests for compound key validation and duplicate detection.
   - Keymap/catalog tests proving the default palette opener includes both `colon` and `semicolon` and displays clearly.
   - TUI pilot tests proving `semicolon` opens `CommandPaletteModal`, alongside the existing `colon` coverage.

## Verification

After implementation:

1. Run focused tests:
   - `pytest tests/test_keymaps.py tests/test_keymaps_validation.py tests/test_command_catalog.py tests/test_command_palette_wiring.py tests/test_command_palette_e2e.py`

2. Because this repo requires it after file changes, run:
   - `just install`
   - `just check`

## Risks and Notes

- A user can still override `ace.keymaps.app.open_command_palette` to a single key if they want to opt out of the
  default dual binding.
- If a user-defined custom mode uses `semicolon` as its prefix without overriding the palette key, the compound-key
  conflict detection should warn just like a normal app key conflict.
- This avoids a second hardcoded binding that would be invisible to config validation, help text, and the command
  palette catalog.

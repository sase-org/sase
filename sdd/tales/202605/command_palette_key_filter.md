---
create_time: 2026-05-08 15:39:27
status: done
prompt: sdd/prompts/202605/command_palette_key_filter.md
---
# Command Palette `key:<key>` Filter Plan

## Goal

Add a special command palette filter form, `key:<key>`, that restricts the palette to commands whose keymap trigger
contains `<key>`. The behavior should work for app bindings, saved-query digit bindings, built-in mode chords, and
custom mode chords because they all already flow through `CommandSpec.key_sequence` and `CommandSpec.key_display`.

## Current Shape

- `src/sase/ace/tui/commands/catalog.py` builds a complete command catalog from `KeymapRegistry`.
- Each `CommandSpec` already has:
  - `key_sequence`: raw Textual key names, for example `("j",)`, `("comma", "t")`, or `("colon,semicolon",)`.
  - `key_display`: human-facing trigger text, for example `j`, `,t`, or `: / ;`.
- `src/sase/ace/tui/modals/command_palette_modal.py` owns query scoring and filtering via `_score_match()` and
  `_filter_specs()`.
- Tests for modal-level filtering live in `tests/test_command_palette_modal.py`; catalog key representation tests live
  in `tests/test_command_catalog.py`.

## Proposed Semantics

1. Treat a query as a key filter only when, after leading/trailing whitespace is stripped, it starts with `key:`
   case-insensitively.
2. The key needle is the stripped text after `key:`. For `key:` with no needle, return all commands in their existing
   order so partially typed filters do not blank the palette.
3. Match case-insensitively against:
   - every raw key sequence part in `CommandSpec.key_sequence`;
   - every raw key alternative inside comma-separated app bindings like `colon,semicolon`;
   - the joined raw sequence/chord, so mode triggers can be searched as a whole;
   - `CommandSpec.key_display`, so display-oriented searches such as `key::`, `key:;`, `key:,t`, and `key:Ctrl+D` work.
4. For key filters, do not use the normal label/category/alias ranking. Preserve the current catalog/category order for
   matches, because the key filter is a boolean narrowing operation.
5. Leave normal queries unchanged, including existing key-display scoring when the input does not use `key:`.

## Implementation Steps

1. Add small pure helpers in `command_palette_modal.py`:
   - `_parse_key_filter(query: str) -> str | None`
   - `_spec_matches_key_filter(spec: CommandSpec, needle: str) -> bool`
2. Update `_filter_specs()` to branch early when `_parse_key_filter()` returns a string:
   - empty needle returns `list(specs)`;
   - non-empty needle returns only specs whose trigger candidates contain the needle.
3. Add unit coverage in `tests/test_command_palette_modal.py`:
   - `key:j` returns commands with raw key/chord containing `j`.
   - `key:,t` can match a mode chord via display text.
   - `key::` and/or `key:semicolon` can match app bindings with comma-separated alternatives.
   - key filtering does not match labels/aliases/categories.
   - `KEY:` is accepted case-insensitively.
   - bare `key:` returns all commands.
4. Run focused tests:
   - `pytest tests/test_command_palette_modal.py`
   - `pytest tests/test_command_catalog.py`
5. Because this repo requires it after edits, run `just install` if needed, then `just check` before reporting back.

## Non-Goals

- Do not change `CommandSpec` or the keymap registry unless tests reveal missing trigger data.
- Do not add combined command text plus key filters such as `key:j refresh`; the requested special form is a simple
  key-trigger filter.
- Do not change palette display, execution, or command availability rules.

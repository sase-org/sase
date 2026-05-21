---
create_time: 2026-05-21 14:47:59
status: done
prompt: sdd/prompts/202605/command_palette_key_hint.md
---
# Command Palette Key Filter Hint Plan

## Goal

Document the command palette's special `key:<key>` query syntax at the point of use so users can discover it while
filtering commands. The hint should make clear that normal text searches commands, while `key:<key>` narrows by key
trigger, for example `key:j`, `key::`, or `key:,t`.

## Current Shape

- `src/sase/ace/tui/modals/command_palette_modal.py` owns the command palette UI.
- The input is currently a `FilterInput` with placeholder text `Type a command...`.
- `_filter_specs()` already supports the `key:<key>` branch and preserves existing behavior for normal queries.
- The modal footer currently documents execution/navigation only: `Enter run · Esc close · ↑/↓ move`.
- Palette styling is centralized in `src/sase/ace/tui/styles.tcss`, including the input, list, empty state, and footer.
- Modal tests live in `tests/test_command_palette_modal.py`; they already cover key-filter semantics but not
  discoverability text.

## Proposed UX

1. Add a short, always-visible hint directly under the command palette input rather than relying only on placeholder
   text. Placeholder text disappears as soon as the user types, while the requested syntax is documentation users may
   need while editing an active query.
2. Keep the input placeholder broad and low-noise, optionally upgrading it to mention both modes in a compact way.
3. Use a concise hint string such as: `Search command text, or use key:<key> for keymaps (key:j, key::, key:,t)`
4. Style the hint like other modal hints (`$text-muted`, one line, compact spacing) so it reads as help text, not a
   command row or warning.
5. Avoid changing `_filter_specs()` behavior, command ordering, command catalog shape, or execution logic.

## Implementation Steps

1. In `CommandPaletteModal.compose()`, insert a `Static` hint immediately after `#command-palette-filter-input` with a
   stable id such as `command-palette-input-hint`.
2. Consider extracting the text to a module constant so tests assert one source of truth and future wording changes are
   localized.
3. Update `styles.tcss` for `CommandPaletteModal #command-palette-input-hint`:
   - full width;
   - muted text color;
   - one-line height;
   - bottom margin before the option list. Adjust the input's current bottom margin so the input, hint, and list spacing
     remains balanced.
4. Add focused modal tests in `tests/test_command_palette_modal.py`:
   - the input placeholder mentions `key:<key>` or the hint text is rendered with that syntax;
   - the hint includes at least one concrete example such as `key:j`;
   - existing filtering tests continue to prove the documented syntax matches real behavior.
5. Run focused checks:
   - `pytest tests/test_command_palette_modal.py`
6. Because this repo requires it after code edits, run `just install` if needed and `just check` before reporting back.

## Risks And Tradeoffs

- A hint line consumes vertical space in the modal. The command palette container uses `height: 70%` and the command
  list uses `height: 1fr`, so the list should shrink by one line without destabilizing the layout.
- Putting all examples into the placeholder alone would be less discoverable after typing starts; the separate hint is
  more useful documentation for this syntax.
- The hint wording should stay short enough for common terminal widths. If tests or manual inspection show wrapping, use
  fewer examples and keep the canonical `key:<key>` form.

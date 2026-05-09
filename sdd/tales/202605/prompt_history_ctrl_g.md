---
create_time: 2026-05-09 11:25:57
status: done
prompt: sdd/prompts/202605/prompt_history_ctrl_g.md
---
# Plan: Add `,<ctrl+g>` Prompt History Edit Shortcut

## Goal

Add a leader-mode keymap `,<ctrl+g>` that opens the most relevant prompt history entry directly in the user's editor,
matching the behavior of pressing `,.` to open prompt history and then pressing `<ctrl+g>` on the default highlighted
entry.

## Current Behavior

- `,` enters leader mode through `start_leader_mode`.
- `,.` dispatches `leader_mode.keys["prompt_history"]` to `_start_prompt_history_from_last_selection()`.
- `_start_prompt_history_from_last_selection()`:
  - loads the last custom agent selection,
  - resolves the VCS prompt prefix for that selection,
  - creates a home-mode `PromptContext`,
  - opens `PromptHistoryModal` sorted by that last selection,
  - handles `PromptHistoryAction.EDIT_FIRST` by applying the VCS prefix to the selected prompt and calling
    `_open_editor_for_agent_prompt()`.
- Inside `PromptHistoryModal`, `<ctrl+g>` returns `EDIT_FIRST` for the currently selected entry. On initial open, that
  is the first filtered history item.

## Proposed Design

Add a new typed leader-mode command, tentatively named `prompt_history_edit_first`, with default key `ctrl+g`.

Extend `_start_prompt_history_from_last_selection()` with an `edit_first: bool = False` option. When `edit_first=True`,
it should perform the same setup as `,.`, select the first prompt history entry using the same sort/filter rules as
`PromptHistoryModal`, apply the same VCS prefix replacement, and call the same editor-launch branch that currently
handles `PromptHistoryAction.EDIT_FIRST`.

This keeps the shortcut behavior anchored to the existing prompt-history workflow instead of introducing a separate
launch path.

## Implementation Steps

1. Add `prompt_history_edit_first: "ctrl+g"` to leader-mode defaults in both:
   - `src/sase/ace/tui/keymaps/types.py`
   - `src/sase/default_config.yml`

2. Teach leader-mode dispatch in `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py` to route the new subkey to:
   - `_start_prompt_history_from_last_selection(edit_first=True)`

3. Factor the prompt-history "edit first" handling inside `src/sase/ace/tui/actions/agent_workflow/_entry_points.py` so
   the modal callback and the direct shortcut share the same editor-launch logic.

4. For selecting the first history item, match `PromptHistoryModal` semantics:
   - use `get_prompts_for_fzf(current_branch=name, current_workspace="home", include_cancelled=True)`,
   - exclude cancelled prompts for this default shortcut,
   - use the first remaining item,
   - if there is no matching history entry, notify clearly and clear `_prompt_context`.

5. Update user-facing command surfaces:
   - command palette leader labels in `src/sase/ace/tui/commands/catalog.py`,
   - leader footer in `src/sase/ace/tui/widgets/keybinding_footer.py`,
   - help modal leader sections in `src/sase/ace/tui/modals/help_modal/bindings.py`.

6. Add focused tests:
   - default registry includes `prompt_history_edit_first == "ctrl+g"`,
   - leader dispatch calls `_start_prompt_history_from_last_selection(edit_first=True)`,
   - command catalog contains `leader.prompt_history_edit_first` with display `, Ctrl+G` or the formatter's established
     equivalent,
   - direct edit-first entry selection uses the same first non-cancelled prompt that the modal would initially
     highlight.

7. Run targeted tests first, then run the repo check required by the repo instructions after implementation:
   - `just install` if needed,
   - targeted pytest for keymaps, leader dispatch, command catalog, and prompt-history entry-point behavior,
   - `just check`.

## Risks and Notes

- `ctrl+g` is already used inside prompt input and prompt-history modal contexts, but leader mode handles the key only
  after `,`, so this should not conflict with those focused-widget bindings.
- The existing `,.` then `<ctrl+g>` path does not run `%edit` directive handling in this entry-point branch. The new
  shortcut should preserve that behavior unless we intentionally change both paths together later.
- If command-palette formatting displays multi-key sequences with a space when one part is multi-character, the expected
  display will likely be `, Ctrl+G`; tests should assert the actual established formatter output.

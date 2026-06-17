---
create_time: 2026-06-17 10:15:22
status: done
prompt: sdd/prompts/202606/prompt_stack_ctrl_minus_add_pane.md
---
# Plan: Migrate Prompt Stack Add-Pane From `-` to `Ctrl+-`

## Context

The prompt stack currently has a normal-mode `-` keymap in `src/sase/ace/tui/widgets/_vim_normal_editing.py`. It calls
`PromptInputBar.add_bottom_pane()`, which syncs live pane text, clears active completion state, appends an empty pane
with `PromptStackState.append_bottom("")`, selects that new pane, rebuilds the stack, and returns the user to insert
mode.

One important finding: despite the request wording saying "below the current prompt input widget", the current wired
behavior appends a new bottom pane, not a pane directly below an arbitrary active pane. The stack model does have
`insert_below()`, but that helper is not used by the existing keymap. This plan therefore treats the requested work as a
keymap migration, preserving the current append-to-bottom behavior. If the desired product change is literally "insert
below the active pane", that should be an explicit follow-up or a plan revision.

Textual normalizes the hyphen key name to `minus`, so the implementation should match `event.key == "ctrl+minus"` while
displaying the shortcut to users as `Ctrl+-` / `[^-]`.

## Scope

- Move prompt stack add-pane from normal-mode `-` to prompt-widget-local `Ctrl+-`.
- Retire the old `-` add-pane shortcut so plain hyphen no longer mutates the stack in normal mode.
- Keep the existing add-pane behavior: prompt mode only, append an empty bottom pane, select it, rebuild, and land in
  insert mode.
- Make the new shortcut available from insert and normal mode, matching the recent prompt-stack Ctrl+Shift focus/reorder
  migration.
- Do not add a config key in `src/sase/default_config.yml`; this is a hardcoded prompt input widget binding like the
  adjacent stack chords.

## Implementation Plan

1. Add a `Ctrl+-` handler in `PromptTextArea._on_key()`.
   - Place it near the other prompt-stack structural handlers, before visual and normal-mode dispatch.
   - Match `ctrl+minus` for Textual's normalized key name.
   - Enable it in `insert` and `normal` modes, not visual modes.
   - Always `stop()` and `prevent_default()` when matched so the key cannot fall through to text insertion, completion,
     normal-mode editing, or app-level bindings.
   - Find the containing `PromptInputBar` and call `bar.add_bottom_pane()`.

2. Retire the old plain `-` normal-mode keymap.
   - Remove the `key == "-"` branch from `_vim_normal_editing.py`.
   - Leave insert-mode plain hyphen behavior alone, so typing `-` still inserts a literal hyphen in prompt text.
   - Leave feedback / approve-prompt bars non-stackable; `add_bottom_pane()` already no-ops unless
     `self._mode == "prompt"`.

3. Keep stack mutation internals unchanged.
   - Continue using `PromptInputBar.add_bottom_pane()` and `PromptStackState.append_bottom()`.
   - Do not switch to `insert_below()` in this migration, because that would change ordering semantics beyond the keymap
     migration.
   - Preserve live-edit syncing, completion cleanup, selected-pane focus, and insert-mode landing behavior.

4. Update discoverability and comments.
   - Update prompt-stack subtitles from `[-] add` to `[^-] add` where the add shortcut is currently advertised.
   - Consider adding a concise insert-mode `[^-] add` hint only if it fits the existing subtitle without making the line
     crowded; at minimum, the help modal must document the new shortcut.
   - Update `PROMPT_INPUT_SECTION` in `src/sase/ace/tui/modals/help_modal/binding_common.py` with a `Ctrl+-` entry for
     adding a prompt pane.
   - Update nearby docstrings/comments in `prompt_input_bar.py`, `_prompt_input_bar_stack_actions.py`,
     `prompt_stack.py`, and `test_prompt_stack_keymaps.py` that still describe `-` as the add-pane keymap.

5. Update focused tests.
   - In `tests/ace/tui/widgets/test_prompt_stack_keymaps.py`, migrate the add-pane test from `pilot.press("-")` to
     `pilot.press("ctrl+minus")`.
   - Add or update coverage that `Ctrl+-` works from insert mode and leaves the new pane selected in insert mode.
   - Add retired-key coverage: after entering normal mode, plain `-` no longer adds a pane.
   - Keep or update feedback-mode coverage so `Ctrl+-` does not create stack panes outside prompt mode.
   - In subtitle tests, replace `[-] add` expectations with `[^-] add` wherever the subtitle advertises the add-pane
     shortcut.
   - In help-modal tests, assert `("Ctrl+-", "Add prompt pane")` or an equivalent wording appears in every prompt input
     help section.

6. Verify.
   - Run `just install` first, following the repo workflow.
   - Run targeted tests:
     `./.venv/bin/python -m pytest tests/ace/tui/widgets/test_prompt_stack_keymaps.py tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py tests/test_keymaps_display_help.py`
   - Run `just check` before reporting completion.

## Risks and Mitigations

- **Key name ambiguity**: Textual's runtime key name is `ctrl+minus`, while user docs should say `Ctrl+-`. Tests should
  use `ctrl+minus` so they match runtime normalization.
- **Behavior ambiguity**: existing code appends to the bottom, not directly below active pane. This plan preserves
  existing semantics to keep the migration narrow.
- **Subtitle crowding**: insert-mode subtitles are already dense. Prefer updating the existing normal-mode add hint and
  the help modal; only add insert-mode subtitle text if the resulting line remains readable.
- **Accidental text insertion**: the new handler must run before normal/default TextArea handling and must prevent
  default when `Ctrl+-` is recognized.

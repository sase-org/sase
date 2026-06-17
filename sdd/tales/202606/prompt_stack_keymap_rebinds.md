---
create_time: 2026-06-17 11:37:12
status: done
prompt: sdd/prompts/202606/prompt_stack_keymap_rebinds.md
---
# Prompt Stack Keymap Rebinds Plan

## Context

The current prompt-stack keymaps use terminal-sensitive chords:

- `Ctrl+H` / `Ctrl+L` focus the previous / next prompt pane.
- `Ctrl+Shift+H` / `Ctrl+Shift+L` move the active pane higher / lower.
- `Ctrl+Shift+-` toggles the xprompt/frontmatter properties panel.

Those key choices are unreliable in real terminals. Rebind the prompt-stack controls to keys that are more likely to be
delivered intact, while preserving the existing stack model behavior: pane focus and reorder still cycle at stack edges,
and moved/focused panes keep normal mode.

## Keymap Decisions

1. Pane focus moves to normal-mode `K` / `J`.
   - `K` replaces `Ctrl+H`: focus the previous / higher pane.
   - `J` replaces `Ctrl+L`: focus the next / lower pane.
   - These are prompt-normal-mode-only controls.
   - This intentionally retires Vim normal-mode `J` line join.
   - While the prompt text area owns focus, swallow bare normal-mode `J` / `K` even when no pane movement occurs, so
     they do not leak to the app-level Agents-tab `J` / `K` panel-focus bindings.
   - Do not activate these controls after a pending normal-mode prefix such as the comma leader.

2. Pane reorder moves to normal-mode `Up` / `Down`.
   - `Up` replaces `Ctrl+Shift+H`: move the active pane higher / earlier.
   - `Down` replaces `Ctrl+Shift+L`: move the active pane lower / later.
   - I will make these normal-mode-only as well. This avoids stealing insert-mode cursor movement and insert-mode
     completion navigation, where `up` / `down` are already meaningful.
   - In a single-pane prompt, leave normal-mode arrow cursor movement intact because there is no pane to reorder.

3. Remove the old structural prompt-stack chords.
   - `Ctrl+H` / `Ctrl+L` no longer focus panes.
   - `Ctrl+Shift+H` / `Ctrl+Shift+L` no longer reorder panes.
   - Keep insert-mode `Ctrl+L` completion behavior unchanged; only the pane-focus fallback is removed.

4. The xprompt/frontmatter properties panel toggle moves to `Ctrl+Shift+=`.
   - Replace the old body toggle `ctrl+shift+minus`.
   - Recognize Textual spellings that represent the shifted equals / plus key path: `ctrl+shift+equal`,
     `ctrl+shift+equals`, `ctrl+shift+plus`, and `ctrl+plus`.
   - Do not keep the old `ctrl+shift+minus` or `ctrl+underscore` property-panel toggle aliases; `ctrl+underscore` should
     remain associated with the add-pane legacy path, not the panel toggle.

## Implementation Plan

1. Update prompt-local key dispatch in `src/sase/ace/tui/widgets/prompt_text_area.py`.
   - Replace the `Ctrl+H` / `Ctrl+L` focus block with a normal-mode `K` / `J` block before Vim normal-mode editing
     dispatch.
   - Replace the `Ctrl+Shift+H` / `Ctrl+Shift+L` reorder block with a normal-mode `up` / `down` reorder block.
   - Remove the insert-mode `Ctrl+L` pane-focus fallback after completion handling, preserving `Ctrl+L` completion
     acceptance.
   - Keep existing completion navigation on insert-mode `up` / `down`.

2. Retire Vim normal-mode `J` join behavior.
   - Remove or neutralize the `J -> _join_lines()` dispatch in the normal-mode editing mixin.
   - Keep `J` as a prompt-local structural key in multi-pane normal mode and as a swallowed no-op otherwise.
   - Remove dead join-specific tests or replace them with focused no-join regression coverage.

3. Update frontmatter panel toggle constants and handling.
   - Change `FRONTMATTER_PANEL_BODY_TOGGLE_KEYS` / `FRONTMATTER_PANEL_TOGGLE_KEYS` in
     `src/sase/ace/tui/widgets/frontmatter_panel.py` to the new equals / plus spellings.
   - Update `PromptTextArea` and `FrontmatterPanel.on_key()` comments/docstrings to describe `Ctrl+Shift+=`.
   - Keep `,f` behavior unchanged.

4. Update user-facing labels and inline docs.
   - Update prompt subtitles in `src/sase/ace/tui/widgets/prompt_input_bar.py`:
     - Insert mode should point users to `[Esc] nav` rather than advertising normal-mode-only pane movement.
     - Normal mode should advertise `K/J` for pane focus and `Up/Down` for pane movement.
   - Update help modal prompt-input entries in `src/sase/ace/tui/modals/help_modal/binding_common.py`.
   - Update action/model docstrings and comments in prompt stack modules that still name the old chords.
   - Update `docs/ace.md` prompt-stack key tables, which still mention older comma-leader pane movement, so the docs
     align with the current prompt-stack controls.

5. Update focused tests.
   - Rewrite `tests/ace/tui/widgets/test_prompt_stack_keymaps.py` to use `K` / `J` for focus and `up` / `down` for
     reorder.
   - Cover cycling at stack edges for the new keys.
   - Cover normal-mode-only behavior: `K` / `J` do not focus panes in insert mode, and `up` / `down` do not reorder
     panes in insert mode.
   - Cover old-key regressions: `Ctrl+H` / `Ctrl+L` no longer focus panes, and `Ctrl+Shift+H` / `Ctrl+Shift+L` no longer
     reorder panes.
   - Update comma-leader coexistence tests so retired `,J` / `,K` do not accidentally trigger the new bare `J` / `K`
     focus behavior.
   - Update frontmatter panel tests from `ctrl+shift+minus` to the new equals / plus key spelling and add a regression
     that the old minus chord no longer opens the panel.
   - Update help/subtitle tests in `tests/test_keymaps_display_help.py` and
     `tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py`.

## Validation

After implementation, run:

1. `just install`
2. Focused tests:
   - `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps.py`
   - `pytest tests/ace/tui/widgets/test_frontmatter_panel.py`
   - `pytest tests/test_keymaps_display_help.py tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py`
   - any remaining prompt normal-mode test file after the `J` join retirement
3. `just check`

No Rust core or sibling repository changes are expected. No `src/sase/default_config.yml` change is expected because
these prompt-stack controls are prompt-widget-local, not configurable app keymap registry bindings.

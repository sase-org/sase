---
create_time: 2026-06-17 11:46:11
status: done
prompt: sdd/prompts/202606/prompt_ctrl_g_stack_editor.md
---
# Plan: Make Ctrl+G the Stacked Prompt Editor Key

## Goal

Remove the prompt input widget's `Ctrl+Shift+G` keymap and make `Ctrl+G` the single editor key. When the prompt bar
contains multiple visible prompt panes, `Ctrl+G` should open the whole prompt stack in the editor using the current
all-stack editor behavior. When the prompt bar has only one pane, `Ctrl+G` should keep the existing single-prompt editor
behavior.

## Current State

- `PromptTextArea.BINDINGS` binds:
  - `ctrl+g` -> `open_editor`
  - `ctrl+shift+g` -> `open_all_editor`
- `action_open_editor()` posts `PromptInputBar.EditorRequested(current_text, cursor_row, cursor_col)`.
- `action_open_all_editor()` is prompt-mode-only and posts `PromptInputBar.AllEditorRequested()`.
- The app handler for `AllEditorRequested` already does the desired multi-pane behavior:
  - serialize live panes with `bar.xprompt_markdown_for_editor()`
  - open `$EDITOR`
  - reload the edited result through `bar.load_stack_from_xprompt_markdown()`
  - keep the bar mounted and refocus on empty editor return
- Existing tests intentionally assert the old split behavior: `Ctrl+G` edits only the active pane, while `Ctrl+Shift+G`
  edits the whole stack.

## Implementation

1. Change `PromptTextArea.BINDINGS` in `src/sase/ace/tui/widgets/prompt_text_area.py` so only `ctrl+g` is bound for
   editor handoff. Remove the `ctrl+shift+g` binding.

2. Change `PromptTextArea.action_open_editor()` to choose the editor scope from the mounted prompt bar:
   - If the bar is in prompt mode and `bar.is_stacked()` is true, clear transient completion / hint state and post
     `PromptInputBar.AllEditorRequested()`.
   - Otherwise, preserve the existing single-pane behavior by posting
     `PromptInputBar.EditorRequested(self.text, row, col)`.
   - Keep the key handler light: no serialization, parsing, file I/O, subprocess work, or heavy DOM scans on the
     keypress path. The existing app-level all-editor handler should remain responsible for serializing and opening the
     editor.

3. Remove `PromptTextArea.action_open_all_editor()` unless another source still calls it. If removing it creates too
   much churn, leave no binding to it and update comments/tests so it is clearly no longer user-addressable; the
   preferred implementation is to delete it.

4. Keep `PromptInputBar.AllEditorRequested` and `on_prompt_input_bar_all_editor_requested()` as the semantic whole-stack
   editor path. Update comments/docstrings that describe it as `Ctrl+Shift+G`; it will now be reached by `Ctrl+G` when
   multiple panes are visible.

5. Revisit `on_prompt_input_bar_editor_requested()` comments and tests. Since stacked `Ctrl+G` should no longer post
   `EditorRequested`, old active-pane-editor comments should be updated or removed. The handler can keep the defensive
   stacked-bar branch if it is useful for programmatic callers, but the keymap tests must assert that stacked `Ctrl+G`
   uses `AllEditorRequested`.

6. Update prompt UI copy:
   - Remove `[^⇧G] edit all` from the prompt placeholder in `PromptInputBar._compute_placeholder()`.
   - If helpful, adjust stacked insert-mode subtitle or surrounding text so `Ctrl+G` is understood as the editor key
     without advertising a second editor scope.

7. Update documentation:
   - `docs/ace.md` prompt input table: `Ctrl+G` opens the current prompt in single-pane mode and the whole stack when
     multiple panes are visible.
   - Prompt stacks section: replace the old statement that `Ctrl+G` edits only the selected pane with the new
     whole-stack behavior.
   - Remove any `Ctrl+Shift+G`, `^⇧G`, or "edit all" references that are no longer true in source comments, tests, and
     user docs.

## Tests

Update focused tests rather than broad rewrites:

- `tests/ace/tui/widgets/test_prompt_input_bar_stack.py`
  - Replace `test_ctrl_g_requests_active_pane_text_only` with a test that `action_open_editor()` or
    `pilot.press("ctrl+g")` on a stacked prompt posts exactly one `AllEditorRequested` and no `EditorRequested`.
  - Remove or rewrite the `ctrl+shift+g` action test.
  - Change the binding test to assert `ctrl+g` exists and `ctrl+shift+g` is absent.
  - Keep the global-shadowing test: focused prompt pane `Ctrl+G` must still beat the app-level `Ctrl+G` binding.

- `tests/ace/tui/test_prompt_bar_editor_stack.py`
  - Reframe the all-editor handler tests as the stacked `Ctrl+G` behavior.
  - Remove expectations that stacked `Ctrl+G` updates only the active pane, unless retained as explicit
    defensive/programmatic handler coverage.

## Verification

After implementation, run:

```bash
just install
pytest tests/ace/tui/widgets/test_prompt_input_bar_stack.py tests/ace/tui/test_prompt_bar_editor_stack.py
rg -n "ctrl\\+shift\\+g|Ctrl\\+Shift\\+G|\\^⇧G|edit all|open_all_editor" src tests docs README.md config --glob '!memory/**'
just check
```

If `just check` is too slow or fails for unrelated environment reasons, report the targeted pytest results and the
failure reason clearly.

## Risks And Guardrails

- `Ctrl+G` is also an app-level keymap for editing the last VCS xprompt. The focused prompt text area must continue to
  shadow that global binding while a prompt bar is active.
- The new stacked `Ctrl+G` path must use the existing `AllEditorRequested` handler so editor serialization and reload
  semantics stay identical to the old `Ctrl+Shift+G` behavior.
- Avoid adding work to the keypress path; the TUI performance guidance specifically warns against blocking while the
  user is typing or navigating prompt input.
- Do not change default keymap config unless investigation finds a configurable prompt-widget keymap source. The current
  prompt input bindings are widget-local, not entries in `src/sase/default_config.yml`.

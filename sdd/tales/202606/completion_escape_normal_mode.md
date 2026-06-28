---
create_time: 2026-06-28 14:45:55
status: done
prompt: sdd/prompts/202606/completion_escape_normal_mode.md
---
# Plan: Leave Prompt Completion Escape In Normal Mode

## Context

The prompt input widget is implemented by `PromptTextArea` and its key handling mixin. In insert mode, `Escape` normally
transitions to vim normal mode via `_enter_normal_mode()`. When a completion menu is active, however, the insert-mode
`Escape` branch currently clears completion state and returns before calling the mode transition helper. That dismisses
the completion panel but leaves `_vim_mode == "insert"`.

The desired behavior is: pressing `Escape` with prompt completion open should still dismiss transient completion UI, but
the user should land in normal mode, matching plain insert-mode `Escape`.

## Implementation Approach

1. Update the insert-mode `Escape` handling in `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py`.
   - Keep consuming the event with `stop()` and `prevent_default()`.
   - Remove the early return that only clears active completion state.
   - Route both active-completion and non-completion insert-mode `Escape` through `_enter_normal_mode()`.
   - Prefer `_enter_normal_mode()` over directly setting `_vim_mode`, because it already centralizes cleanup for
     completion, soft completion, xprompt hints, g-prefix state, prompt search, snippet tabstops, cursor classes, prompt
     bar title/subtitle, and insert-capture bookkeeping.

2. Preserve unrelated prompt behaviors.
   - `Ctrl+C` should remain the explicit prompt cancellation command.
   - `Enter`, `Ctrl+L`, arrow navigation, `Ctrl+N`/`Ctrl+P`, and `Ctrl+D` should keep their current completion
     acceptance/navigation behavior.
   - Normal-mode and visual-mode `Escape` handling should remain unchanged.
   - No new synchronous work should be added to key handlers.

3. Update regression coverage.
   - Change the existing completion regression in `tests/ace/tui/widgets/test_prompt_file_completion.py` so
     `test_escape_dismisses_completion_panel` asserts:
     - the completion panel is hidden,
     - completion state is inactive,
     - the prompt text is unchanged,
     - the prompt text area is now in normal mode.
   - Optionally add the same normal-mode assertion to one automatic completion path, such as VCS project or xprompt
     auto-completion, if the first test does not clearly cover the active `_file_completion_active` branch.

## Validation

After making code changes:

1. Run the focused prompt completion tests:
   `pytest tests/ace/tui/widgets/test_prompt_file_completion.py tests/ace/tui/widgets/test_prompt_escape_cancel.py`

2. Run any additional focused completion test touched for auto-completion coverage.

3. Because this repo requires it after file changes, run `just install` if the workspace is not already prepared, then
   run `just check` before finishing.

## Risks And Mitigations

- `_enter_normal_mode()` already clears file completion, so calling it after an active completion should not leave stale
  completion UI. The focused test should verify both state and panel visibility.
- The behavior intentionally changes an existing test expectation from insert mode to normal mode, so the test update
  should be framed as the regression guard for the requested UX.
- The change stays inside existing key dispatch and mode-transition helpers, so it should not affect TUI responsiveness.

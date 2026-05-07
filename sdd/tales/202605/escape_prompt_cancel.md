---
create_time: 2026-05-07 12:40:11
status: done
prompt: sdd/prompts/202605/escape_prompt_cancel.md
---
# Plan: Make Prompt Escape Non-Cancelling

## Context

The prompt input widget is `PromptInputBar`, with editing handled by `PromptTextArea`. `PromptTextArea` has Vim-style
insert and normal modes:

- In insert mode, `escape` currently enters normal mode, or dismisses an active completion panel.
- In normal mode, `escape` currently cancels the entire prompt by calling `PromptInputBar.action_cancel()` when no
  pending Vim operator exists.
- `ctrl+c` already cancels the prompt from `PromptTextArea._on_key`.

The accidental-cancel path is therefore: press `escape` once to leave insert mode, press `escape` again in normal mode,
and the prompt is posted as `PromptInputBar.Cancelled`.

## Desired Behavior

- `escape` must no longer cancel the prompt input bar.
- `ctrl+c` remains the explicit prompt cancellation command.
- Existing non-destructive Escape behavior should remain:
  - Dismiss active file/xprompt/directive completion while staying in insert mode.
  - Enter normal mode from insert mode.
  - Clear pending Vim operator/count state in normal mode.
- UI hints should not advertise Escape as prompt cancellation for this widget.

## Implementation

1. Update `VimNormalModeMixin._handle_normal_mode_key` so normal-mode `escape` only clears pending operator/count state
   and otherwise returns handled without calling `PromptInputBar.action_cancel()`.
2. Update prompt input subtitles in `PromptInputBar` and `PromptTextArea` to describe the new contract:
   - Insert mode: Enter submits, Escape enters normal mode, Ctrl+C cancels.
   - Normal mode: `i` returns to insert mode, Ctrl+C cancels, Escape clears pending normal-mode state.
3. Keep `PromptInputBar.action_cancel()` unchanged, because it is still the correct cancellation path for `ctrl+c` and
   programmatic cancellation.
4. Add focused Textual tests around `PromptInputBar`:
   - Pressing `escape` twice should not emit `PromptInputBar.Cancelled` and should leave the text intact in normal mode.
   - Pressing `ctrl+c` should still emit `PromptInputBar.Cancelled` with the stripped prompt text.
   - Pressing `escape` after a pending normal-mode operator should clear the operator without cancellation.

## Verification

Run targeted prompt-widget tests first:

```bash
just install
pytest tests/ace/tui/widgets/test_prompt_escape_cancel.py tests/test_prompt_normal_mode_change.py tests/ace/tui/widgets/test_prompt_file_completion.py tests/ace/tui/widgets/test_xprompt_arg_hints.py
```

Because this repo asks for full validation after code changes, finish with:

```bash
just check
```

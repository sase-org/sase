---
create_time: 2026-06-17 07:24:07
status: done
prompt: sdd/prompts/202606/remove_shift_enter_prompt_stack.md
---
# Plan: Remove Shift+Enter Prompt-Stack Submit Support

## Goal

Remove ACE prompt input support for using `Shift+Enter` to submit all prompt-stack panes as one multi-agent prompt.
`Ctrl+S` remains the only supported whole-stack submit keymap. The change should eliminate current user-facing
documentation and in-code/test documentation that advertises `Shift+Enter` as supported, while preserving the existing
multi-agent prompt-stack launch behavior through `Ctrl+S`.

## Current Understanding

- The live key handling is in `src/sase/ace/tui/widgets/prompt_text_area.py`.
  - Plain `Enter` submits the selected pane.
  - `event.key in ("shift+enter", "ctrl+s")` currently submits the whole stack.
- The whole-stack submit action itself should remain:
  - `PromptTextArea.action_submit_prompt_stack()` still delegates to `PromptInputBar._handle_whole_stack_submission()`.
  - `Ctrl+S` should continue to call that action and produce the same joined `---` multi-agent prompt.
- Current docs that advertise `Shift+Enter`:
  - `docs/ace.md`
  - `docs/xprompt.md`
  - Source docstrings/comments in the prompt input widget/bar modules.
  - Prompt-stack tests that describe or directly cover the old alias.
- `src/sase/default_config.yml` does not appear to define this prompt-input keymap, but the keymap memory note says to
  verify config defaults whenever changing keymaps.
- This touches ACE TUI input handling, so the TUI performance rule applies: avoid adding synchronous event-loop work.
  This removal should only simplify an existing key branch.

## Implementation Plan

1. Remove the `Shift+Enter` runtime alias from prompt input handling.
   - In `PromptTextArea._on_key`, change the whole-stack submit condition from accepting both `shift+enter` and `ctrl+s`
     to accepting only `ctrl+s`.
   - Keep `action_submit_prompt_stack()` and `PromptInputBar._handle_whole_stack_submission()` intact so `Ctrl+S`
     preserves current behavior.
   - Update nearby comments/docstrings so they describe `Ctrl+S` as the supported whole-stack submit key.

2. Update user-facing documentation.
   - In `docs/ace.md`, remove `Shift+Enter` from the INSERT mode and Prompt Stacks keybinding tables.
   - In `docs/xprompt.md`, describe `Ctrl+S` as the way to submit prompt-stack panes together.
   - Do not edit historical prompt transcript files under `sdd/prompts/`. For SDD design notes/tales that are not
     current product documentation, only update them if they are clearly presented as current behavior rather than a
     historical plan.

3. Update tests and test documentation.
   - Keep the `Ctrl+S` whole-stack submit test as the behavioral coverage.
   - Remove the direct `Shift+Enter` alias test, since that support is intentionally gone.
   - Update test module comments and section headers that currently say `Ctrl+S` and `Shift+Enter`.
   - Add or adjust a focused regression assertion if useful: pressing `shift+enter` should no longer emit a whole-stack
     submit. If Textual test delivery is unreliable for `shift+enter`, do not add a brittle synthetic test; rely on
     source-level removal plus the retained `Ctrl+S` behavior test.

4. Verify all references.
   - Run a focused `rg` for `shift+enter`, `Shift+Enter`, and related spellings in live source/docs/tests.
   - Accept remaining references only in clearly historical SDD prompt/spec artifacts, if any, and note them in the
     final response.

5. Run validation.
   - Run the focused prompt-stack tests, especially:
     - `tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py`
     - `tests/ace/tui/test_prompt_bar_stack_submit_handlers.py`
     - `tests/ace/tui/test_prompt_stack_launch_integration.py`
   - Because this repo requires it after code/doc changes, run `just install` if needed and then `just check`.

## Risks

- Some docs/spec files under `sdd/` may still mention the old key because they are historical planning artifacts. The
  implementation should distinguish those from current user-facing docs.
- Textual/terminal handling for `Shift+Enter` is the original source of the problem; tests should avoid depending on
  portable delivery of that key unless the existing test harness proves it can deliver it consistently.

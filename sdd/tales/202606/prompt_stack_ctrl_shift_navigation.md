---
create_time: 2026-06-17 09:41:50
status: done
prompt: sdd/prompts/202606/prompt_stack_ctrl_shift_navigation.md
---
# Migrate Prompt Stack Pane Navigation to Ctrl+Shift+J/K

## Goal

Move the prompt input stack's pane focus navigation from normal-mode-only `,j` and `,k` to `Ctrl+Shift+J` and
`Ctrl+Shift+K`, so users can move to the below or above prompt pane while either typing in insert mode or browsing in
normal mode.

## Current Behavior

- `PromptTextArea` owns vim-style prompt editing.
- In normal mode, `,` opens a prompt-stack comma leader in `_vim_normal_motions.py`.
- `_vim_normal_pending.py` dispatches `,j` and `,k` to `PromptInputBar.focus_relative(1/-1)`.
- `PromptInputBar.focus_relative()` always puts the newly focused pane into normal mode, which is appropriate for the
  old normal-mode leader but would be surprising for an insert-mode shortcut.
- Insert mode never reaches the normal-mode comma leader, so the existing pane navigation cannot work while the user is
  typing.
- The local prompt help surfaces mention these keys in `PromptInputBar.normal_mode_subtitle()` and the help modal's
  shared "Prompt Input" section.

## Design

1. Add a prompt-local, mode-independent key path for pane focus navigation.
   - Handle `event.key == "ctrl+shift+j"` and `event.key == "ctrl+shift+k"` in `PromptTextArea._on_key` before
     insert/normal/visual mode dispatch.
   - Scope this to insert and normal mode. Visual mode should keep its current selection semantics unless explicitly
     requested later.
   - Stop and prevent the event whether or not a movement is possible, so these shortcuts do not fall through to text
     insertion, newline behavior, or global bindings.

2. Preserve the user's current editing mode after navigation.
   - Extend `PromptInputBar.focus_relative()` to accept a target mode or preserve-mode flag.
   - Existing comma-leader callers should continue to request normal mode.
   - The new Ctrl+Shift callers should preserve insert mode when invoked from insert mode and preserve normal mode when
     invoked from normal mode.
   - Keep the existing lightweight behavior: clear transient completion state, move the stack selection, focus the
     target pane, update active classes, and schedule the height update. Do not add disk I/O, parsing, subprocesses, or
     refresh work on the keypress path.

3. Retire `,j` and `,k` for pane focus navigation.
   - Remove the `j` and `k` cases from `_handle_stack_leader_key`.
   - Leave the other comma-leader prompt-stack actions intact, including `,J`/`,K` pane reorder, `,s`/`,S` stash, `,P`
     restore, and `,f` frontmatter.
   - Update comments/docstrings that currently describe `,j`/`,k` as stack navigation.

4. Update user-facing prompt help.
   - Update multi-pane insert and normal prompt subtitles to advertise `Ctrl+Shift+J/K` for pane focus navigation.
   - Update the shared help modal "Prompt Input" section so `?` documents pane navigation accurately.
   - Avoid changing `src/sase/default_config.yml` unless implementation discovery shows these prompt-local keys are part
     of the configurable app keymap. Current evidence says they are hardcoded widget-local bindings, not default config
     entries.

5. Update and add tests.
   - Update existing prompt stack keymap tests so navigation uses `ctrl+shift+j` and `ctrl+shift+k`.
   - Add a regression test proving Ctrl+Shift navigation works from insert mode and leaves the target pane in insert
     mode.
   - Add or update a regression test proving Ctrl+Shift navigation works from normal mode and leaves the target pane in
     normal mode.
   - Add a regression test that `,j`/`,k` no longer move between panes, while `,J`/`,K` still reorder panes.
   - Update subtitle/help tests that assert `,j`/`,k` are advertised.
   - If `PromptTextArea.BINDINGS` is updated for discoverability, update the binding-list test alongside it.

## Verification

- Run targeted tests first:
  - `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps.py`
  - `pytest tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py`
  - `pytest tests/test_keymaps_display_help.py`
- Because implementation changes will modify repo files, run `just install` if needed and then `just check` before final
  response, per project instructions.

## Risks and Mitigations

- Terminal support for Ctrl+Shift letter chords can vary. This code should use Textual's existing key naming convention
  (`ctrl+shift+j/k`), matching the repo's existing `ctrl+shift+g` widget binding and `ctrl+shift+d` app binding.
- Ctrl+J is already newline in the prompt. The new handler must match only `ctrl+shift+j` so existing newline behavior
  remains unchanged.
- `Ctrl+K` is prompt history. The new handler must match only `ctrl+shift+k` so prompt history remains unchanged.
- Since TUI performance guidance calls out navigation hot paths, keep this as a pure in-memory focus change and reuse
  the existing height scheduling path.

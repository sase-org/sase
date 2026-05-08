---
create_time: 2026-05-08 17:40:21
status: done
prompt: sdd/prompts/202605/alt_word_keymaps.md
---
# Add Alt-B / Alt-F Readline Word Navigation

## Context

The prompt input widget is `PromptTextArea`, a Textual `TextArea` subclass in
`src/sase/ace/tui/widgets/prompt_text_area.py`. It already wires several readline-style shortcuts directly in
`BINDINGS`, including `ctrl+b` and `ctrl+f` for single-character backward/forward movement.

Textual 8.0.0 already provides `TextArea.action_cursor_word_left()` and `TextArea.action_cursor_word_right()`, and its
xterm parser maps an ESC-prefixed printable key sequence to `alt+<key>`. That matters for macOS: terminal apps use the
Option key as Meta by sending ESC-prefixed keys when "Option as Meta" / "Esc+" behavior is enabled, so Option-B and
Option-F arrive in Textual as `alt+b` and `alt+f`.

## Plan

1. Add `alt+b` and `alt+f` bindings to `PromptTextArea.BINDINGS`, mapping them to Textual's existing word-motion
   actions:
   - `alt+b` -> `cursor_word_left`
   - `alt+f` -> `cursor_word_right`

2. Add focused prompt widget tests that exercise the new keymaps in insert mode:
   - `alt+b` moves from the end of a multi-word prompt to the previous word.
   - `alt+f` moves from the start of a prompt to the next word.
   - An ESC-prefixed `b`/`f` path also produces the same effect, covering the macOS Option-as-Meta terminal behavior
     rather than only synthetic `pilot.press("alt+b")` events.

3. Keep the change scoped to prompt input behavior. No default config update is expected because `PromptTextArea` uses
   widget-local Textual bindings for these readline shortcuts, not the configurable app-level keymap registry.

4. Verify with the smallest relevant pytest target first, then run the repository check command required by project
   memory after changes:
   - `pytest tests/ace/tui/widgets/test_prompt_virtual_wrap.py`
   - `just install`
   - `just check`

---
create_time: 2026-05-07 15:12:00
status: done
prompt: sdd/prompts/202605/prompt_ctrl_e_actual_line.md
---
# Fix Prompt Ctrl+E Actual Line End

## Context

The ace prompt input uses `PromptTextArea`, a Textual `TextArea` subclass with soft wrapping enabled. Textual's built-in
`cursor_line_end` action is wrapping-aware: with soft wrap active, it moves to the end of the current rendered wrapped
section. The prompt input's expected readline-style `<ctrl+e>` behavior is different: it should move to the end of the
current actual document line.

The existing override in `src/sase/ace/tui/widgets/prompt_text_area.py` only handles the "already at physical line end,
advance to next line end" case. In the common case where the cursor is within a wrapped section, it delegates to
Textual, preserving virtual-line behavior. A targeted repro in a narrow app showed a 36-character one-line prompt moving
from column 5 to column 16 with wrap offsets `[17, 34]`, instead of to column 36.

## Plan

1. Update `PromptTextArea.action_cursor_line_end()` so the action always computes the current physical document line's
   end with `len(self.document.get_line(row))` and moves there directly.

2. Preserve the existing repeated-end behavior: if the cursor is already at or past the current physical line end and
   there is another physical document line, move to the end of the next physical line.

3. Preserve selection support by passing the existing `select` argument through to `move_cursor(...)`.

4. Keep the change scoped to the prompt input widget. Do not modify global keymap configuration because `<ctrl+e>` is
   inherited from Textual's `TextArea` binding and the project-specific behavior is implemented by overriding the
   action.

5. Add focused async widget tests in `tests/ace/tui/widgets/test_prompt_virtual_wrap.py`:
   - A long soft-wrapped physical line should move from the middle to the actual line end, not the wrap boundary.
   - Repeating the action at the end of one physical line should move to the end of the next physical line, preserving
     the existing behavior.

6. Verify with the focused prompt virtual-wrap test module, then run `just check` as required after changes in this
   repo.

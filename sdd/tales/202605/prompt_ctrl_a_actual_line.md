---
create_time: 2026-05-08 13:05:53
status: done
prompt: sdd/prompts/202605/prompt_ctrl_a_actual_line.md
---
# Plan: Prompt Ctrl+A Uses Actual Lines

## Context

The prompt input uses `PromptTextArea`, a multiline Textual `TextArea` configured with `soft_wrap=True`. Yesterday's
`Ctrl+E` fix changed `action_cursor_line_end()` so it moves to the physical document line end instead of delegating to
Textual's default soft-wrap-aware movement.

`Ctrl+A` is the symmetric line-start movement. `PromptTextArea.action_cursor_line_start()` already preserves the
existing repeat behavior of moving to the previous physical line when the cursor is already at column 0, but the normal
case still delegates to `super().action_cursor_line_start()`. With soft wrapping enabled, that fallback can target a
virtual wrap boundary rather than the actual document line start.

## Goal

Make `Ctrl+A` in the prompt input operate on actual document lines:

- From any nonzero column in a wrapped physical line, move to column 0 of that same physical line.
- From column 0 on any line after the first, keep the existing repeated-key behavior and move to column 0 of the
  previous physical line.
- Preserve selection behavior through the existing `select` argument.
- Avoid changing prompt wrapping, normal-mode motions, modal input widgets, or global keymap configuration.

## Implementation Approach

1. Update `PromptTextArea.action_cursor_line_start()`.
   - Keep the existing `col == 0 and row > 0` branch for repeated `Ctrl+A`.
   - Replace the `super().action_cursor_line_start(select=select)` fallback with an explicit
     `self.move_cursor((row, 0), select=select)`, mirroring the `Ctrl+E` physical-line fix.

2. Add regression tests beside the existing virtual-wrap prompt tests.
   - Add a test proving line-start movement on a narrow wrapped prompt goes to `(0, 0)`, not to a soft-wrap boundary.
   - Add a test proving repeated line-start movement from the start of a later physical line moves to the previous
     physical line start.

3. Verify narrowly first.
   - Run the prompt virtual-wrap test module.

4. Verify the repo per project instructions.
   - Run `just install` if needed for this workspace.
   - Run `just check` after implementation changes.

## Risk

This is low risk because it narrows only the prompt input's readline-style line-start action and mirrors the already
accepted `Ctrl+E` approach. The main behavioral risk is selection handling, so the implementation should continue
passing the existing `select` flag to `move_cursor()`.

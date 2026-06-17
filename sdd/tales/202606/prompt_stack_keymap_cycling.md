---
create_time: 2026-06-17 11:21:46
status: done
prompt: sdd/prompts/202606/prompt_stack_keymap_cycling.md
---
# Prompt Stack Keymap Cycling Plan

## Goal

Make all four prompt-stack pane keymaps cycle at stack edges:

- `Ctrl+H`: focus the previous/higher pane; from the top pane, wrap to the bottom pane.
- `Ctrl+L`: focus the next/lower pane; from the bottom pane, wrap to the top pane.
- `Ctrl+Shift+H`: move the active pane higher/earlier; from the top pane, move it to the bottom of the stack.
- `Ctrl+Shift+L`: move the active pane lower/later; from the bottom pane, move it to the top of the stack.

The active pane should remain active after reordering, and focus/reorder should preserve the current vim mode exactly as
the existing keymaps do today.

## Current Behavior

`PromptTextArea._on_key()` already routes the four relevant chords through `PromptInputBar.focus_relative()` and
`PromptInputBar.move_active_pane()`:

- `Ctrl+H` / `Ctrl+L` call `focus_relative(-1/+1)`.
- `Ctrl+Shift+H` / `Ctrl+Shift+L` call `move_active_pane(-1/+1)`.

Those methods delegate to `PromptStackState.move_focus()` and `PromptStackState.move_selected()`. The stack model
currently clamps target indexes with `_clamp()`, so edge actions become no-ops. Because the widget layer already
consumes these chords in the right modes and preserves insert/normal mode around the operation, cycling should be
implemented in the model operations rather than by adding edge-specific widget logic.

## Design

Change the deterministic stack model so relative focus and reorder wrap with modulo arithmetic when there is more than
one pane:

- `move_focus(delta)` should compute `(selected_index + delta) % len(items)`.
- `move_selected(delta)` should compute the wrapped target the same way, pop the selected item, insert it at the target
  index, and keep `selected_index` on the moved item.
- Single-pane behavior should remain a no-op that returns `False`; there is no meaningful movement and the existing
  widget consumption policy should not change.

This keeps behavior centralized for tests and future callers. It also avoids adding any slow work to Textual key
handlers, consistent with the TUI performance guidance.

## Implementation Steps

1. Update `PromptStackState.move_focus()`.
   - Preserve the existing boolean contract.
   - Use wraparound only when `len(items) > 1`.
   - Refresh the docstring from clamped movement to cycling movement.

2. Update `PromptStackState.move_selected()`.
   - Preserve live item identity and selected item semantics.
   - From top with `delta=-1`, produce bottom placement.
   - From bottom with `delta=+1`, produce top placement.
   - Refresh the docstring to describe cycling reorder.

3. Update prompt-stack action docstrings/comments where they currently imply edge clamping.
   - `focus_relative()` should mention cycling at stack edges.
   - `move_active_pane()` should mention cycling reorder at stack edges.
   - `PromptTextArea._on_key()` comments should stop saying focus clamps at the bottom edge.

4. Update model tests in `tests/ace/tui/widgets/test_prompt_stack.py`.
   - Replace the edge no-op reorder test with explicit wrap tests.
   - Add or update focus tests so top `move_focus(-1)` selects bottom and bottom `move_focus(1)` selects top.
   - Keep single-pane no-op coverage if it already exists or add a narrow assertion.

5. Update widget keymap tests in `tests/ace/tui/widgets/test_prompt_stack_keymaps.py`.
   - Change the existing `Ctrl+L` bottom-edge focus test to assert bottom-to-top cycling.
   - Add `Ctrl+H` top-to-bottom focus coverage if not already implied.
   - Add reorder edge coverage:
     - `Ctrl+Shift+H` on the top pane moves that pane to the bottom and keeps it active.
     - `Ctrl+Shift+L` on the bottom pane moves that pane to the top and keeps it active.
   - Preserve insert/normal mode assertions so cycling does not regress mode preservation.

6. Run focused verification first, then full validation.
   - `just install`
   - `pytest tests/ace/tui/widgets/test_prompt_stack.py tests/ace/tui/widgets/test_prompt_stack_keymaps.py`
   - `just check`

## Risks and Checks

- `Ctrl+L` still has completion precedence in insert mode. The existing completion-before-focus ordering should remain
  unchanged; cycling should only happen when focus fallback is reached.
- `Ctrl+H` should still match only exact `ctrl+h`, never `backspace`, and should still be consumed only for multi-pane
  stacks.
- Reorder wraparound must be tested with item identity/state, not only text order, because panes carry
  cursor/mode/height state.
- No Rust core boundary work is expected; this remains presentation-side TUI stack behavior.

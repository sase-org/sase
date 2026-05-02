---
bead_id: sase-1
status: done
prompt: sdd/prompts/202603/prompt_widget_improvements.md
---

# Plan: Prompt Widget Improvements (TextArea)

## Context

The prompt input bar was recently replaced with a Textual `TextArea` widget (commit `9febfa4`). Two improvements are
needed:

1. **Height expansion**: The widget is hard-capped at 15 rows (`_MAX_HEIGHT = 15`). When content grows beyond that, it
   should expand up to the full screen height instead of stopping at 15 rows.
2. **Vim mode**: Pressing `Escape` should enter a vim-like NORMAL mode with relative line numbers and navigation
   keybindings, rather than cancelling the prompt bar.

### Current state

- **Widget**: `_PromptTextArea(TextArea)` inside `PromptInputBar(Static)` in
  `src/sase/ace/tui/widgets/prompt_input_bar.py`
- **CSS**: `styles.tcss` lines 506-525 — `height: 3; max-height: 15; dock: bottom;`
- **Height logic**: `_update_height()` uses `min(max(visual_lines + 2, 3), self._MAX_HEIGHT)` — capped at 15
- **Escape**: Currently bound on `PromptInputBar` to `action_cancel` which dismisses the bar
- **Line numbers**: Shown when `line_count > 1`, using Textual's built-in absolute line numbers

### Key files

- `src/sase/ace/tui/widgets/prompt_input_bar.py` — main widget
- `src/sase/ace/tui/styles.tcss` — CSS styling
- `src/sase/ace/tui/app.py` — mounts/unmounts the prompt bar

---

## Phase 1: Dynamic height expansion (remove 15-row cap)

**Goal**: Let the prompt widget grow up to the full terminal height when content warrants it.

### Changes

**`src/sase/ace/tui/widgets/prompt_input_bar.py`**:

- Remove `_MAX_HEIGHT = 15` constant
- Change `_update_height()` to compute max height dynamically from the terminal/screen height:
  ```python
  def _update_height(self) -> None:
      visual_lines = self._get_visual_line_count()
      # Reserve a few rows for the header/tabs at minimum
      screen_height = self.screen.size.height if self.screen else 50
      max_height = screen_height - 2  # leave room for header
      new_height = min(max(visual_lines + 2, 3), max_height)
      self.styles.height = new_height
  ```
- Also call `_update_height()` on resize events so the cap adjusts when the terminal is resized

**`src/sase/ace/tui/styles.tcss`**:

- Remove `max-height: 15;` from `PromptInputBar` (or set it to `100%`) since height is now managed programmatically

### Testing

- Verify with `sase ace --agent` that the prompt doesn't show excessive empty line numbers
- Verify that with many lines of content, the widget grows beyond 15 rows
- Verify resize behavior

---

## Phase 2: Vim NORMAL mode with relative line numbers

**Goal**: Pressing `Escape` enters vim NORMAL mode. In NORMAL mode, line numbers become relative (showing distance from
cursor line, with the cursor line showing its absolute number). Pressing `i` returns to INSERT mode.

### Changes

**`src/sase/ace/tui/widgets/prompt_input_bar.py`**:

1. **Add mode state** to `_PromptTextArea`:
   - Add `_vim_mode: str` attribute (`"insert"` or `"normal"`)
   - Default to `"insert"` mode on creation

2. **Remap Escape**:
   - Remove `("escape", "cancel", "Cancel")` from `PromptInputBar.BINDINGS`
   - In `_PromptTextArea._on_key()`, intercept `escape`:
     - If in INSERT mode → switch to NORMAL mode
     - If in NORMAL mode → cancel the prompt bar (post `Cancelled` message)
   - When entering NORMAL mode: set `read_only = True`, enable line numbers, enable cursor line highlight, update border
     subtitle to show `NORMAL`
   - When entering INSERT mode: set `read_only = False`, restore normal line numbers, update border subtitle

3. **Relative line numbers**:
   - Textual's `TextArea` uses a `render_line_gutter()` method that can be overridden to customize the gutter content
   - Override `render_line_gutter(row_index)` in `_PromptTextArea`:
     - In INSERT mode: return the default (absolute line number, 1-indexed)
     - In NORMAL mode: return `abs(row_index - cursor_row)` for non-cursor lines, and the absolute line number for the
       cursor line (the current row)
   - Force a gutter re-render when the cursor moves in NORMAL mode

4. **Visual indicator**: Update `border_title` to show mode (e.g., `"Prompt [NORMAL]"` vs `"Prompt"`)

### Testing

- Verify Escape switches to NORMAL mode and shows relative line numbers
- Verify second Escape cancels the prompt bar
- Verify `i` returns to INSERT mode with absolute line numbers
- Snapshot test with `sase ace --agent`

---

## Phase 3: Vim navigation keybindings in NORMAL mode

**Goal**: In NORMAL mode, support standard vim navigation keybindings.

### Keybindings to implement

**Basic movement**:

- `h` — cursor left
- `j` — cursor down
- `k` — cursor up
- `l` — cursor right

**Word movement**:

- `w` — next word start (word = alphanumeric + underscore)
- `W` — next WORD start (WORD = non-whitespace)
- `b` — previous word start
- `B` — previous WORD start
- `e` — next word end
- `E` — next WORD end

**Line movement**:

- `0` — start of line
- `$` — end of line
- `^` — first non-whitespace character

**Document movement**:

- `gg` — go to first line
- `G` — go to last line

**Mode switching**:

- `i` — enter INSERT mode at cursor
- `a` — enter INSERT mode after cursor
- `A` — enter INSERT mode at end of line
- `I` — enter INSERT mode at first non-whitespace of line
- `o` — open new line below and enter INSERT mode
- `O` — open new line above and enter INSERT mode

### Changes

**`src/sase/ace/tui/widgets/prompt_input_bar.py`**:

1. **Add `_handle_normal_mode_key()`** method to `_PromptTextArea`:
   - Route key events through this handler when in NORMAL mode
   - Implement each navigation command
   - For multi-key sequences like `gg`: track a `_pending_key` buffer

2. **Modify `_on_key()`** to dispatch to normal mode handler:

   ```python
   async def _on_key(self, event: Key) -> None:
       if event.key == "enter":
           event.stop()
           event.prevent_default()
           self.action_submit_prompt()
           return
       if self._vim_mode == "normal":
           event.stop()
           event.prevent_default()
           self._handle_normal_mode_key(event)
           return
       await super()._on_key(event)
   ```

3. **Word boundary helpers**:
   - `_find_next_word_start(row, col)` — for `w`
   - `_find_next_WORD_start(row, col)` — for `W`
   - `_find_prev_word_start(row, col)` — for `b`
   - `_find_prev_WORD_start(row, col)` — for `B`
   - `_find_next_word_end(row, col)` — for `e`
   - `_find_next_WORD_end(row, col)` — for `E`
   - These follow vim's definition: word = `[a-zA-Z0-9_]+`, WORD = `[^\s]+`

### Testing

- Test each navigation key moves cursor correctly
- Test `gg`, `G`, `0`, `$`, `^` work at document boundaries
- Test mode-switching keys (`i`, `a`, `A`, `I`, `o`, `O`) properly enter INSERT mode
- Test that multi-key sequences (`gg`) work with timeout/reset

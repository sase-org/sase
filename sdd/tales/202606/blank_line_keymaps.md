---
create_time: 2026-06-24 08:48:06
status: done
prompt: sdd/prompts/202606/blank_line_keymaps.md
---
# Plan: `[<space>` / `]<space>` blank-line keymaps for the prompt input

## Goal & product context

Add two vim-unimpaired-style NORMAL-mode keymaps to the `sase ace` prompt input widget (`PromptTextArea`):

- **`[<space>`** — insert a blank line **above** the currently selected line.
- **`]<space>`** — insert a blank line **below** the currently selected line.

These mirror Tim Pope's `vim-unimpaired` mappings. They let the user open spacing around the current line without
leaving NORMAL mode and without disturbing the cursor's logical position on its content line (unlike `o`/`O`, which
enter INSERT mode and move the cursor onto the new line).

### Behavior specification

Given the cursor on a line with content (cursor stays in NORMAL mode throughout):

- `]<space>`: a new empty line is inserted immediately **after** the current line. The cursor stays on the original line
  at its original column.
- `[<space>`: a new empty line is inserted immediately **before** the current line. The original line (and the cursor
  with it) shifts down by one row; the cursor stays on the same content at its original column.
- **Count support**: a numeric prefix inserts that many blank lines, matching `v:count1` semantics in vim-unimpaired.
  E.g. `3]<space>` inserts three blank lines below; `2[<space>` inserts two blank lines above.
- **Single undo**: each invocation is one undoable edit (`u` restores the prior text in one step).
- **Dot-repeat**: `.` repeats the last `[<space>` / `]<space>`, consistent with how the existing line edits (`o`, `O`,
  `J`, `dd`) are dot-repeatable.
- Only `<space>` is a recognized continuation. Any other key after `[` / `]` (e.g. `[x`) is a graceful no-op that leaves
  the buffer unchanged and returns to the normal command state — we are intentionally **not** implementing the rest of
  the unimpaired bracket family.

## Design & boundary analysis

**This stays entirely in Python TUI code — it does not cross the Rust core backend boundary.** All existing vim
NORMAL-mode editing for the prompt (`o`, `O`, `J`, `dd`, `x`, surround, text objects, …) is implemented in the
`_vim_normal*.py` mixins on top of Textual's `TextArea`. The sibling `sase-core` `editor/` module is read-only analysis
(completions, diagnostics, hovers) with no buffer-mutation or modal-editing concept, and exposes no editor mutation
bindings to Python. Blank-line insertion is presentation-layer modal editing with no shared-backend equivalent, so it
belongs with its sibling vim commands in this repo, following the established pattern. No Rust, no `sase_core_rs`
binding, and no `default_config.yml` change are involved (the prompt's vim keymaps are hardcoded in the mixins, not
config-driven).

### Where the keys are handled

The widget already has a multi-key "pending prefix" state machine used by `g`, `r`, `f`/`F`/`t`/`T`, and the surround
prefixes:

- A first key sets `self._pending_keys = <prefix>` (and optionally `self._pending_count`), then returns handled.
- The next key is routed through `_handle_normal_pending_key(...)` in `src/sase/ace/tui/widgets/_vim_normal_pending.py`,
  which dispatches on the stored prefix.

We add `[` and `]` as two new pending prefixes following this exact pattern.

### Implementation outline

1. **Recognize the bracket prefix** in the NORMAL edit dispatcher `_handle_normal_edit_key`
   (`src/sase/ace/tui/widgets/_vim_normal_editing.py`), following the existing `r` precedent:
   - On `[` or `]` (when no operator is pending), set `self._pending_keys = key`, store the count
     (`self._pending_count = count if has_count else None`), refresh the count display, and return handled. This
     guarantees the bracket is consumed by the widget (so it never falls through to insert a literal `[`/`]` nor bubbles
     up to the app-level `toggle_thinking` binding bound to the bracket keys).

2. **Dispatch the continuation** in `_handle_normal_pending_key` (`_vim_normal_pending.py`): add a branch for
   `pending in "[]"`.
   - If the continuation key is `<space>` (detect robustly via both `event.key == "space"` and `event.character == " "`,
     so dot-repeat replay — which re-issues buffered keys — also matches), perform the blank-line insertion with the
     resolved count.
   - Otherwise clear the mutation key buffer and no-op (matching the existing "unknown continuation" handling for text
     objects).

3. **Insertion helper(s)** (small new method(s) on the operator/editing mixin, mirroring `_join_lines` in
   `src/sase/ace/tui/widgets/_vim_normal_operator_exec.py`). Both use the established NORMAL-mode mutation recipe:
   capture cursor, flip `read_only` off, insert via `_replace_via_keyboard("\n" * count, …)`, restore `read_only`, set
   the final cursor, set `_mutation_count`, then call `_record_mutation()` for dot-repeat:
   - **Below (`]<space>`)**: insert `"\n" * count` at the **end** of the current line (`(row, len(line))`); restore the
     cursor to its original `(row, col)`.
   - **Above (`[<space>`)**: insert `"\n" * count` at the **start** of the current line (`(row, 0)`); move the cursor to
     `(row + count, col)` so it tracks the original content that shifted down.

### Edge cases to cover

- Empty document / single empty line: both commands insert blank line(s) and keep NORMAL mode without error.
- First line with `[<space>` and last line with `]<space>`: blank lines are added at the very top / very bottom.
- Cursor column preserved (clamped by the TextArea where needed) since the content line is unchanged.
- Count of 1 (no prefix) inserts exactly one blank line.
- Unknown continuation after `[`/`]` is an inert no-op (no text change, count display cleared, back to normal command
  state).
- `read_only` is correctly restored to its prior value after the edit.

## Testing

Add a new `tests/test_prompt_normal_mode_blank_lines.py` using the `PromptPage` harness (same style as
`tests/test_prompt_normal_mode_join.py`), asserting `page.text`, `page.cursor`, and `page.mode` for:

- `]<space>` inserts a blank line below; cursor unchanged; mode stays normal.
- `[<space>` inserts a blank line above; cursor follows content down one row.
- Counted variants (`3]<space>`, `2[<space>`).
- First-line / last-line / empty-buffer edge cases.
- `u` undoes the insertion in a single step.
- `.` repeats the last blank-line command.
- An unknown continuation (`[x`) makes no change and leaves a usable normal state.

## Out of scope / non-goals

- The rest of the `vim-unimpaired` bracket family (`[e`/`]e`, `[<C-...>`, paste variants, etc.).
- Any change to the Rust `sase-core` editor module or its Python bindings.
- Any `default_config.yml` keymap entry (these vim keys are not config-driven).
- INSERT-mode or VISUAL-mode bracket behavior (unchanged).

## Documentation & verification

- Search for any user-facing cheatsheet/help listing the prompt's vim NORMAL-mode keys (e.g. the `o`/`O`/`J` commands).
  If such a list exists, add `[<space>` / `]<space>` there; if none exists, no doc change is required.
- Confirm focus/eventing: with the prompt focused in NORMAL mode, `[`/`]` are consumed by the widget and do **not**
  trigger the app-level thinking-panel toggle bound to the bracket keys.
- Run `just install` (ephemeral workspace) then `just check` before completing.

---
create_time: 2026-06-23 18:24:50
status: done
prompt: sdd/prompts/202606/prompt_number_increment.md
---
# Plan: Vim-style `<ctrl+a>` / `<ctrl+x>` number increment/decrement in the prompt input

## Goal & product context

Add Vim's `<ctrl+a>` (increment) and `<ctrl+x>` (decrement) number commands to the `sase ace` prompt input widget
(`PromptTextArea`), available in **NORMAL mode only**.

The prompt input is a modal (Vim-style) `TextArea`. Today `<ctrl+a>` is a readline "jump to start of line" binding that
is provided by the underlying Textual `TextArea` and only reachable in INSERT mode (NORMAL mode intercepts keys before
the default handler runs). This plan repurposes `<ctrl+a>`/`<ctrl+x>` in NORMAL mode to manipulate numbers while leaving
the INSERT-mode readline behavior completely untouched.

Behavior is a faithful slice of Vim, extended slightly so that when the cursor is **not** on a number, the command finds
and operates on a number elsewhere in the prompt (vim only searches the rest of the current line).

## Behavior specification (confirmed via Q&A)

1. **Mode split.** In INSERT mode, `<ctrl+a>` keeps its current "move to start of line" behavior (no change). In NORMAL
   mode, `<ctrl+a>` increments and `<ctrl+x>` decrements a number.

2. **Target selection — forward, wrap to top (Q1).** Vim-style search over the _current prompt_ (the whole document of
   the focused `PromptTextArea`, which may be multiple lines):
   - Operate on the number **at or after** the cursor — i.e. the first number whose end is past the cursor. This covers
     the cursor being inside a number (operate on that whole number) and a number later on the line or on a later line.
   - If no number is at/after the cursor, **wrap to the top** of the prompt and operate on the first number found
     (covers earlier-on-line and previous-line numbers).
   - If the prompt contains no number at all, do nothing (no-op, like Vim's "no number" beep, but silent).

3. **Number formats — decimal + sign + leading-zero width (Q2).**
   - A number is a maximal run of decimal digits `[0-9]+`, optionally with a directly-preceding `-` treated as a
     negative sign (e.g. `5<ctrl+x>` on `-3` → `-8`; on `foo-5` → `foo-6`).
   - Leading-zero width is preserved like Vim (`007` + 1 → `008`; `009` with `10<ctrl+x>` → `-001`).
   - No hex/octal/binary recognition in v1.

4. **Count + dot-repeat (Q3).**
   - A count prefix multiplies the delta: `5<ctrl+a>` adds 5, `3<ctrl+x>` subtracts 3.
   - `.` repeats the last increment/decrement (including its count), matching the existing `~`/`x`/`dd` dot-repeat
     behavior in this widget.

5. **Cursor placement.** After the change, the cursor lands on the **last digit** of the resulting number (Vim
   behavior), so a sequence of `<ctrl+a>` presses keeps acting on the same number.

## Architecture decision: Python-only (no Rust core change)

Per the Rust-core backend boundary, shared backend/domain behavior belongs in `sase-core` and is mirrored in Python with
golden vectors. This feature is intentionally **Python-only**, for three reasons:

- Every existing Vim NORMAL-mode operator in this widget (`d`, `c`, `y`, `~`, `x`, `dd`, surround, indent, case ops, …)
  is implemented purely in Python under `src/sase/ace/tui/widgets/_vim_normal*.py`. There is no Vim/motion/text-editing
  logic in `sase-core`'s `editor` module — that module is _language intelligence_ (completion, hover, definition,
  diagnostics), not text-editing operators.
- The litmus test asks whether another frontend would need to _match_ the TUI. The relevant other frontend is the Neovim
  integration, which has **native** `<ctrl+a>`/`<ctrl+x>` and would never call into `sase-core` for this. So there is no
  cross-frontend parity requirement.
- Keeping it Python-only is consistent and avoids speculative generality (YAGNI).

The pure number-manipulation algorithm will still be factored into a **dependency-free helper function** so it is
unit-testable in isolation and could be promoted to `sase-core` later if a second consumer ever appears.

## Design / implementation approach

The widget's NORMAL-mode dispatch already gives us count parsing and dot-repeat "for free" as long as we hook in at the
right place and record the mutation. Concretely:

- `_on_key` (`_prompt_text_area_key_handling.py`) routes all NORMAL-mode keys through `_handle_normal_mode_key` and
  stops the event when it returns `True`. INSERT-mode keys (including `<ctrl+a>`) fall through to Textual's default
  handler unchanged — so the INSERT-mode readline behavior needs no code.
- `_handle_normal_mode_key` (`_vim_normal.py`) parses the count prefix into `count`/`has_count`, manages the
  `_mutation_key_buffer` used for dot-repeat, and finally delegates edit commands to
  `_handle_normal_edit_key(key, event, count, has_count)`.
- Dot-repeat (`_replay_dot` / `_record_mutation` in `_vim_normal_state.py`) replays the recorded key buffer. It already
  supports multi-character key names: the buffer stores `event.character or event.key` (so `"ctrl+a"`), and replay
  reconstructs `Key("ctrl+a", "ctrl+a")`, which re-enters the same dispatch path.

### Step 1 — Pure helper module

Add `src/sase/ace/tui/widgets/_vim_number.py` containing a pure function (no Textual imports), e.g.:

```
def compute_number_change(text: str, cursor: int, delta: int) -> NumberChange | None
```

- `text` is the full prompt document text; `cursor` is the absolute character offset; `delta` is `+count` for increment
  or `-count` for decrement.
- Returns a small immutable result (`NamedTuple`/dataclass) `NumberChange(start, end, new_text, new_cursor)` giving the
  absolute span `[start, end)` of the matched number, its replacement string, and the absolute offset of the last digit
  of the new number; or `None` when the prompt has no number.

Algorithm:

1. Find all non-overlapping number spans matching `-?\d+` over `text` (left to right).
2. **Target:** the first span whose `end > cursor`; if none, the first span overall (wrap-to-top); if there are no
   spans, return `None`.
3. **Compute:** parse the signed integer from the span; `new_value = value + delta`.
4. **Format:** `sign = "-" if new_value < 0 else ""`; `digits = str(abs(new_value))`. If the original digit run
   (excluding sign) has a leading zero (`len(orig_digits) > 1 and orig_digits[0] == "0"`), zero-pad `digits` to at least
   the original width. `new_text = sign + digits`.
5. **Cursor:** `new_cursor = start + len(new_text) - 1` (last char of the new number).

This function is the single source of truth for the increment semantics and is covered by a golden-style unit table (see
Tests).

### Step 2 — Apply helper on the widget

Add `_apply_number_change(self, delta: int) -> None` alongside `_toggle_case` in `_vim_normal_operator_exec.py`
(`VimNormalOperatorExecutionMixin`), following the exact `_toggle_case` template:

- Compute `cursor = self._absolute_offset(self.cursor_location)` and call
  `compute_number_change(self.text, cursor, delta)`.
- If `None`, return (silent no-op).
- Otherwise convert `start`/`end` to `(row, col)` via `self._location_from_absolute`, then: save/clear `read_only`,
  `self.delete(start_loc, end_loc)`, `self._replace_via_keyboard(new_text, start_loc, start_loc)`, restore `read_only`,
  set `self.cursor_location = self._location_from_absolute(new_cursor)`, and call `self._record_mutation()` (this is
  what makes `.` repeat work).

### Step 3 — Wire into NORMAL-mode dispatch

In `_handle_normal_edit_key` (`_vim_normal_editing.py`), add a branch near the other single-key edit commands:

```
if event.key in ("ctrl+a", "ctrl+x"):
    self._apply_number_change(count if event.key == "ctrl+a" else -count)
    return True
```

Dispatch on `event.key` (not `key`) for robustness, mirroring how `Ctrl+R` redo is matched. This branch is reached only
in NORMAL mode (INSERT-mode `<ctrl+a>` never enters `_handle_normal_mode_key`), so the INSERT readline binding is
preserved with zero changes. The motion handler runs before the edit handler and does not claim `ctrl+a`/`ctrl+x`, so
there is no ordering conflict. Count and dot-repeat work automatically through the existing machinery.

## Files to change

- **New:** `src/sase/ace/tui/widgets/_vim_number.py` — pure `compute_number_change` helper + result type.
- `src/sase/ace/tui/widgets/_vim_normal_operator_exec.py` — add `_apply_number_change`.
- `src/sase/ace/tui/widgets/_vim_normal_editing.py` — add the `ctrl+a`/`ctrl+x` dispatch branch.
- `docs/ace.md` — add `Ctrl+A` / `Ctrl+X` rows to the NORMAL-mode **Other Commands** table (~lines 1929–1950), noting
  count + dot-repeat and the at/after-cursor-then-wrap target rule. (The INSERT-mode table's existing `Ctrl+A` "move to
  start of line" row stays as-is.) Optionally refresh the NORMAL-mode summary in
  `docs/blog/posts/prompt-widget-and-nvim.md`.
- **New test file** (see below).

No change expected to `src/sase/default_config.yml`: these are hardwired widget keys, not configurable keymaps. No
`sase` CLI subcommand/option changes, so no `?` help-popup or footer/keybinding updates are required (the prompt-widget
docs live in `docs/ace.md`, which we update).

## Tests

Add `tests/test_prompt_normal_mode_number.py` using the existing `PromptPage` harness (same pattern as
`tests/test_prompt_normal_mode_toggle_case.py` / `_dot.py`). Cover:

- Increment/decrement of the number under the cursor; cursor ends on the last digit of the result.
- Cursor not on a number → jumps to and modifies the next number on the same line.
- No number after cursor on the current line → jumps to a number on a later line.
- No number at/after cursor anywhere forward → wraps to the first number at the top of the prompt.
- No number anywhere → text unchanged (no-op).
- Negative sign: `5<ctrl+x>` on `-3` → `-8`; decrement crossing zero (e.g. `0` → `-1`).
- Leading-zero width preserved: `007` → `008`; `009` with `10<ctrl+x>` → `-001`; plain `9` → `10` (no padding).
- Count: `5<ctrl+a>` adds 5.
- Dot-repeat: `<ctrl+a>` then `.` increments again; `3<ctrl+a>` then `.` repeats `+3`.
- **Mode preservation:** in INSERT mode, `<ctrl+a>` moves the cursor to the start of the line and does **not** change
  any digits.

Also add a focused unit test (in the same file or `tests/test_vim_number.py`) exercising `compute_number_change`
directly with a small golden table of `(text, cursor, delta) -> NumberChange | None` vectors, including the wrap and
leading-zero cases.

## Validation

Per `memory/build_and_run.md` (ephemeral workspace): run `just install`, then `just check`. Also run the focused tests
during development:

```
just install
just test  # or: pytest tests/test_prompt_normal_mode_number.py tests/test_vim_number.py
just check
```

## Edge cases & non-goals

- **Pending operator:** an exotic sequence like `d<ctrl+a>` is not a meaningful Vim command; the existing edit commands
  (`~`, `x`, …) don't special-case a dangling operator either, so we follow the same convention and don't add guards.
- **Multiple `-`:** `--5` increments the inner `-5` (regex treats the directly-preceding `-` as the sign), leaving the
  outer `-`; acceptable Vim-ish behavior.
- **Scope:** the search is limited to the focused pane's own document ("the current prompt"); it does not reach into
  sibling panes of a prompt stack.
- **Non-goals (v1):** hex/octal/binary number formats, alphabetic increment (Vim's `nrformats=alpha`), visual-mode block
  increment (`g<ctrl+a>`), and any Rust-core mirroring.

## Risks

- Low. The change is additive and isolated to NORMAL-mode dispatch plus a pure helper. The main correctness surface is
  the number-finding/formatting algorithm, which is fully covered by the unit golden table, and the offset↔(row,col)
  conversions, which reuse the widget's existing `_absolute_offset` / `_location_from_absolute` and the well-worn
  `_toggle_case` mutation template.

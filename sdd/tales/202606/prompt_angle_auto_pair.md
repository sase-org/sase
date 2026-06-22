---
create_time: 2026-06-22 09:32:16
status: done
prompt: sdd/prompts/202606/prompt_angle_auto_pair.md
---
# Plan: Add Prompt Auto-Pair Support for Angle Brackets

## Context

The prompt input widget already has generic insert-mode auto-pairing for `()`, `[]`, `{}`, and same-character quote
pairs in `src/sase/ace/tui/widgets/_paired_text_editing.py`. The key path in
`src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` applies those pure `TextEdit` plans before Textual's
default character insertion, and `src/sase/ace/tui/widgets/_prompt_text_area_actions.py` uses the same helper module for
paired Backspace/Delete behavior.

The implementation is intentionally lightweight: no I/O, no subprocess calls, no parser work, and no event-loop blocking
on keypress. That matches the TUI performance guidance. Jinja delimiter special-casing is separate and should remain
unchanged.

## Desired Behavior

Treat `<` and `>` like the existing bracket pairs:

- Typing `<` with a collapsed selection inserts `<>` and leaves the cursor between the characters when the following
  character is safe.
- Safe following positions should remain the existing conservative set: end of text, whitespace, or an existing closing
  delimiter. Adding `>` to the generic closer set means `<` before `>` is also safe.
- Typing `>` while the cursor is directly before an existing `>` should move over it instead of inserting a duplicate
  when there is an unmatched `<` before the cursor.
- Backspace/Delete should remove both characters for an empty `<>` pair.
- Non-empty pairs, active selections, and unsafe token-continuation positions should continue to fall through to
  Textual's literal edit behavior.

## Implementation Steps

1. Update `src/sase/ace/tui/widgets/_paired_text_editing.py`.
   - Add `"<": ">"` to `_OPEN_TO_CLOSE`.
   - Let `_CLOSE_TO_OPEN`, `_CLOSE_CHARS`, `_is_matching_pair`, close-skip, and delete behavior pick up `>` through the
     existing derived structures.
   - Refresh the module docstring/comments so the supported bracket list includes `<>`.

2. Expand `tests/ace/tui/widgets/test_prompt_pair_editing.py`.
   - Include `("<", ">")` in pure planner insertion tests for EOF and whitespace.
   - Include angle brackets in close-skip tests.
   - Include `<>` in paired Backspace/Delete empty-pair tests.
   - Include `("<", "<>")` in Textual integration for typing an opener.
   - Include `("<", ">")` in Textual integration for typing a closer and moving over the generated closer.
   - Add or extend a rejection test proving `<` before token-continuation characters stays literal/falls through.
   - Add `>` to the non-opener insert test so `plan_pair_insert` itself does not treat closers as openers.

3. Do not change prompt key dispatch.
   - `_try_prompt_text_pair_edit()` already calls `plan_pair_close_skip(...) or plan_pair_insert(...)` for single
     printable characters, so adding the pair to the helper map should be enough.
   - `_try_paired_delete()` already calls the generic delete planners after Jinja-specific deletion, so no
     action-handler changes should be needed.

4. Keep other prompt features intact.
   - Leave Jinja auto-pairing unchanged; it only handles `{`, `%`, and `#` after an existing `{`.
   - Leave alternation separator handling (`|`) unchanged.
   - Do not update help modal/keymap documentation, because this adds no command, keybinding, or option.

## Verification

After implementation:

1. Run the focused test file first:

   ```bash
   just test tests/ace/tui/widgets/test_prompt_pair_editing.py
   ```

2. Because implementation file changes in this repo require full validation, run:
   ```bash
   just check
   ```

## Risks

- Angle brackets are also common prose/math/comparison characters. The current safe-position rule limits automatic
  pairing to contexts where a bracket-like pair is least surprising; before letters, digits, underscores, punctuation,
  quotes, or another opener, `<` should remain a literal insertion.
- If Textual's test pilot treats `<` or `>` specially, the pure planner tests still cover the logic, and the integration
  tests can use the repository's existing event/test helper pattern for literal character input.

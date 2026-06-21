---
create_time: 2026-06-21 08:37:46
status: done
prompt: sdd/prompts/202606/prompt_autopairs.md
---
# Prompt Autopairs Plan

## Context

The current prompt input support is intentionally narrow:

- `src/sase/ace/tui/widgets/_alt_syntax_editing.py` provides pure offset-based edit planners for `%{...}`:
  auto-inserting `{}` after a directive `%`, paired-deleting an empty `%{}`, and normalizing `|` separators inside an
  alternation span.
- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` intercepts insert-mode keys before Textual inserts them,
  applies planned edits through `_replace_via_keyboard`, then clears transient completion state.
- `src/sase/ace/tui/widgets/_prompt_text_area_actions.py` intercepts backspace/delete actions for paired deletion before
  falling back to Textual.
- `tests/ace/tui/widgets/test_prompt_alt_syntax_editing.py` covers both the pure planners and Textual integration.
- `tests/ace/tui/widgets/test_prompt_jinja.py` pins existing Jinja auto-pair behavior for `{{  }}` and `{%  %}`.

This is presentation/editor behavior for `PromptTextArea`, so it should stay in the Python TUI layer rather than moving
to `sase-core`. The TUI performance rule is to keep keypress handling pure, bounded, and free of I/O.

The external reference, `windwp/nvim-autopairs`, supports rule-based pairing, deletion, and moving over existing closing
characters. We only need a small fixed-rule subset for the prompt input.

## Goals

Add generalized insert-mode auto-pair support for:

- same-character quotes: `'`, `"`, and `` ` ``
- bracket pairs: `()`, `[]`, and `{}`

The behavior should be conservative and only apply when it is safe:

- Insert an auto-close when typing an opener at a safe cursor position.
- Remove both sides when backspace/delete targets an empty pair.
- Move over an existing matching closer instead of duplicating it when the cursor is immediately before that closer and
  the surrounding context indicates the closer belongs to the current pair.
- Preserve existing `%{...}` separator normalization.
- Preserve existing Jinja pairing outcomes: typing `{` then `{` still yields `{{  }}`, typing `{` then `%` still yields
  `{%  %}`, and `{#  #}` should continue to work if currently supported by the same code path.

## Non-Goals

- No user-facing configuration or per-filetype rule system.
- No tree-sitter/parser awareness.
- No auto-wrapping selected text. Current prompt behavior lets typed characters replace selections; keep that unless a
  separate request asks for surround-style insert behavior.
- No automatic newline indentation inside pairs.
- No new keybindings such as `ctrl+h`; keep existing Textual delete bindings and prompt-local keymaps intact.

## Design

1. Introduce a generic pure helper module, likely `src/sase/ace/tui/widgets/_paired_text_editing.py`.

   Define a neutral edit dataclass, for example `TextEdit(start: int, end: int, text: str, cursor: int)`, plus a fixed
   table of supported pair rules:
   - `' -> '`
   - `" -> "`
   - `` ` -> ` ``
   - `( -> )`
   - `[ -> ]`
   - `{ -> }`

   Provide pure planners:
   - `plan_pair_insert(text, offset, char) -> TextEdit | None`
   - `plan_pair_close_skip(text, offset, char) -> TextEdit | None`
   - `plan_pair_delete_left(text, offset) -> TextEdit | None`
   - `plan_pair_delete_right(text, offset) -> TextEdit | None`

   Keep these helpers independent from Textual widgets and from completion state.

2. Make the safety rules explicit and conservative.

   Pair insertion should require a collapsed selection at the caller and should return `None` unless the cursor context
   is safe:
   - For bracket openers, pair at EOF, before whitespace, or before an existing supported closer. Do not pair before a
     word character or obvious token-continuation characters such as `.`, `$`, `%`, another opener, or quote/backtick
     characters.
   - For quote/backtick characters, pair only when the quote is not escaped, the previous and next characters are not
     word characters, and the next character is EOF, whitespace, or a supported closer. This avoids common prose cases
     like contractions and possessives.
   - For repeated quote/backtick characters, do not insert a fresh pair when the previous character is the same
     delimiter; this keeps Markdown/code-fence entry possible after the first auto-pair.

   Paired deletion should only apply to empty pairs:
   - Backspace: cursor between opener and closer, deleting the opener removes both.
   - Delete/forward delete: cursor before an empty pair removes both.
   - Non-empty pairs and selections fall back to Textual's default delete behavior.

   Close-skip should only apply when the typed character is exactly the next character and context indicates the closer
   belongs to a current pair:
   - For brackets, scan the current text up to the cursor for an unmatched opener of the same pair.
   - For quote/backtick pairs, require an odd count of unescaped matching delimiters before the cursor.
   - The edit is a zero-text replacement that moves the cursor one character right.

3. Refactor `%{...}` support to use the generic edit shape without losing alt-specific logic.

   Keep the alternation-only functions in `_alt_syntax_editing.py`:
   - directive-valid `%{...}` span detection
   - matching-brace scanning for alt spans
   - branch start detection
   - `|` separator normalization

   Remove or de-emphasize the alt-specific `{}` insert/delete planners after generic pair planners cover the same user
   behavior. If keeping compatibility wrappers makes the test migration smaller, have them delegate to the generic
   helpers where possible.

4. Update `PromptTextArea` key handling.

   In `PromptTextAreaKeyHandlingMixin._on_key`, keep the existing precedence:
   - prompt search
   - insert `Ctrl+G`
   - submit/cancel/history/editor/completion keys
   - active xprompt argument hint handling, especially the current `(` hint behavior
   - visual/normal-mode handling

   Then handle insert-mode text pairing in this order:
   - Jinja auto-pair special case
   - alternation `|` separator normalization
   - generic close-skip
   - generic pair insertion
   - default Textual insertion

   Rename `_try_alt_syntax_edit` / `_apply_alt_edit` to names that reflect the broader role, such as
   `_try_prompt_text_pair_edit` and `_apply_planned_text_edit`, while keeping the completion-clearing behavior
   unchanged.

5. Preserve Jinja behavior with generic `{}` pairing.

   Generic `{}` pairing changes the state after the first `{`: the buffer becomes `{}` with the cursor between the
   braces. Update `_try_jinja_auto_pair` so the second `{`, `%`, or `#` can consume that auto-inserted `}` and still
   produce the existing final strings:
   - `{` then `{` -> `{{  }}`
   - `{` then `%` -> `{%  %}`
   - `{` then `#` -> `{#  #}`

   The planner should support both the old literal-first-`{` context and the new `{|}` context so manually-authored
   buffers and undo/redo edge cases remain natural.

6. Update delete actions.

   Replace `_try_alt_paired_delete` in `PromptTextAreaActionsMixin` with a generic `_try_paired_delete(forward: bool)`.
   It should:
   - skip selections
   - compute the absolute cursor offset
   - call the generic left/right delete planner
   - apply the edit via `_replace_via_keyboard`
   - refresh completion and xprompt hint surfaces exactly as the current delete hook does

7. Test the pure planner thoroughly.

   Add a focused test module, likely `tests/ace/tui/widgets/test_prompt_pair_editing.py`, covering:
   - pair insertion for all supported pairs at EOF and before whitespace
   - rejection before unsafe next characters
   - quote rejection in contractions/possessives and after escapes
   - close-skip for brackets and quote/backtick pairs
   - paired backspace/delete for every supported pair
   - non-empty pair deletion falling back by returning `None`
   - multiline absolute-offset behavior

8. Update Textual integration tests.

   Extend the prompt widget tests to cover:
   - typing each opener inserts the expected pair and leaves the cursor between delimiters
   - typing the closer while before the auto-inserted closer moves over it rather than duplicating it
   - backspace/delete remove empty pairs for brackets and quotes
   - selections still receive literal replacement behavior
   - `%{}` still works and `|` separator normalization is unchanged
   - Jinja tests still pass for `{{  }}`, `{%  %}`, and `{#  #}`
   - Markdown backtick ergonomics: first backtick creates an inline pair, a second backtick moves over the closer, and a
     third backtick can still produce a triple-backtick fence prefix

9. Verification plan for implementation.

   During implementation, run focused tests first:

   ```bash
   pytest tests/ace/tui/widgets/test_prompt_pair_editing.py \
     tests/ace/tui/widgets/test_prompt_alt_syntax_editing.py \
     tests/ace/tui/widgets/test_prompt_jinja.py
   ```

   Before handing off completed code changes in this repo, run:

   ```bash
   just install
   just check
   ```

## Risks and Mitigations

- Quote pairing can be intrusive in prose prompts. Keep quote rules more restrictive than bracket rules and add tests
  for contractions, possessives, and escaped quotes.
- Generic `{}` pairing can break Jinja if handled naively. Explicitly support the `{|}` intermediate state in the Jinja
  auto-pair path.
- Backtick pairing can interfere with Markdown fences. The repeated-delimiter and close-skip rules should keep fence
  typing possible.
- Per-keystroke logic must stay cheap. Use bounded scans over the current in-memory text only; no I/O, subprocesses,
  async work, or parser calls.

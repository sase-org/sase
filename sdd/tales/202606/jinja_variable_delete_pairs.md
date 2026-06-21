---
create_time: 2026-06-21 09:13:50
status: done
prompt: sdd/prompts/202606/jinja_variable_delete_pairs.md
---
# Plan: Jinja Variable Paired Deletion

## Context

The prompt input already has a small editor-specific auto-pair layer:

- `src/sase/ace/tui/widgets/_paired_text_editing.py` owns pure, Textual-independent `TextEdit` planners for generic
  bracket/quote insert, close-skip, and empty-pair deletion.
- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` owns Jinja insertion special-casing. Typing `{` then `{`
  now produces `{{  }}` with the cursor between the two inserted spaces.
- `src/sase/ace/tui/widgets/_prompt_text_area_actions.py` intercepts Backspace/Delete and currently delegates only to
  generic empty-pair deletion before falling back to Textual's default delete behavior.

The missing behavior is the Jinja-variable counterpart to insertion: when the user deletes one of the opening `{`
characters in a `{{ ... }}` delimiter, the corresponding closing `}` should be removed too. The two auto-inserted
padding spaces should behave as a pair as well: deleting the space immediately after the second `{` should remove the
space immediately before the first `}`.

This remains presentation-only `PromptTextArea` behavior. It should stay pure, bounded, and free of I/O or parser work
on the keypress path.

## Scope

Implement paired deletion for Jinja variable delimiters:

- In `{{ ... }}`, deleting the first opening `{` removes the last closing `}`.
- In `{{ ... }}`, deleting the second opening `{` removes the first closing `}`.
- In `{{ ... }}`, deleting either boundary padding space removes the other boundary padding space, so the generated
  `{{  }}` can collapse to `{{}}`.
- Support both Backspace (`action_delete_left`) and forward Delete (`action_delete_right`).
- Preserve existing generic `{}` behavior, `%{...}` alternation behavior, and Jinja insertion behavior for `{{  }}`,
  `{%  %}`, and `{#  #}`.

Do not introduce a Jinja parser call, async work, disk I/O, or user-facing configuration. Do not broaden this pass into
full `{% ... %}` / `{# ... #}` paired deletion unless implementation exposes a very small, clearly safe shared helper;
the requested `}}` behavior is specifically for variable delimiters.

## Design

Add a focused pure helper module, likely `src/sase/ace/tui/widgets/_jinja_pair_editing.py`, importing the existing
`TextEdit` dataclass.

Expose planners:

- `plan_jinja_delete_left(text: str, offset: int) -> TextEdit | None`
- `plan_jinja_delete_right(text: str, offset: int) -> TextEdit | None`

Both planners should:

- Treat selections as the caller's responsibility, matching the generic pair planners.
- Compute the character Textual would delete: `offset - 1` for Backspace, `offset` for Delete.
- Return `None` for out-of-range offsets, malformed delimiters, missing `}}`, or non-boundary characters.
- Return a single contiguous `TextEdit` even though two logical characters are being removed, by replacing the span from
  the earlier removed character through the later removed character with the original substring minus those two
  characters.

Delimiter-character deletion:

- Detect whether the target `{` is the first or second character of a `{{` opener.
- Find the nearest following `}}` closer for that opener.
- Map opener-to-closer positions by delimiter symmetry:
  - opening index `open_start` maps to `close_start + 1`
  - opening index `open_start + 1` maps to `close_start`
- Preserve all inner content exactly.

Padding-space deletion:

- For a well-formed `{{ ... }}` tag, identify:
  - left boundary padding: `open_start + 2`
  - right boundary padding: `close_start - 1`
- If both boundary characters are spaces and the delete target is either one, remove both.
- This covers the generated empty state `{{  }}` and non-empty spacing cleanup such as `{{ name }}` -> `{{name}}`.
- Do not delete arbitrary interior spaces; only the two boundary spaces adjacent to the delimiters are paired.

Wire the new planners into `PromptTextAreaActionsMixin._try_paired_delete` before the generic
`plan_pair_delete_left/right` call. Applying the edit should reuse the existing `_replace_via_keyboard`,
`_location_from_absolute`, cursor assignment, and `_refresh_completion_after_text_delete()` flow so completion, Jinja
hints, and diagnostics continue to refresh exactly as they do after other deletes.

## User Flows

The generated empty variable pair should feel reversible:

1. Type `{`, `{` -> `{{ | }}`.
2. Press Backspace -> `{{|}}` by removing both padding spaces.
3. Press Backspace -> `{|}` by removing the second opening `{` and the first closing `}`.
4. Press Backspace -> empty string via the existing generic empty `{}` deletion.

Direct delimiter deletion should also be balanced:

- `|{{ name }}` + Delete -> cursor before `{ name }`, with the last `}` removed.
- `{|{ name }}` + Delete or `{{| name }}` + Backspace -> `{ name }`, with the first `}` removed.

## Tests

Add focused pure-helper coverage, probably in a new `tests/ace/tui/widgets/test_prompt_jinja_pair_editing.py`:

- Backspace/Delete of the first opening `{` in `{{}}`, `{{  }}`, and `{{ name }}` removes the last `}`.
- Backspace/Delete of the second opening `{` removes the first `}`.
- Backspace/Delete of the left boundary padding space in `{{  }}` produces `{{}}`.
- Backspace/Delete of boundary padding in `{{ name }}` produces `{{name}}`.
- Non-boundary spaces, malformed `{{ name }`, lone `{`, and non-Jinja `{ name }` return `None`.
- Multiline absolute offsets are handled correctly.

Extend Textual integration tests in `tests/ace/tui/widgets/test_prompt_jinja.py` or the new pair-editing test module:

- Type `{`, `{`, then Backspace three times and assert the sequence `{{}}` -> `{}` -> empty string.
- Load `{{ name }}`, delete the second opening `{`, and assert the matching first `}` is removed.
- Load `{{ name }}`, delete the left boundary padding, and assert both boundary spaces are removed.
- Cover forward Delete variants for at least one delimiter case and one padding case.
- Keep existing assertions for `{{  }}`, `{%  %}`, and `{#  #}` insertion behavior.

## Verification

Run focused tests first:

```bash
.venv/bin/python -m pytest \
  tests/ace/tui/widgets/test_prompt_jinja.py \
  tests/ace/tui/widgets/test_prompt_pair_editing.py \
  tests/ace/tui/widgets/test_prompt_alt_syntax_editing.py
```

Then run the normal repo gate:

```bash
just check
```

## Risks

- Over-broad whitespace deletion could surprise users editing prose or literal braces. Restrict paired whitespace
  deletion to well-formed `{{ ... }}` boundary spaces only.
- A full Jinja parse on every Backspace/Delete would violate the TUI performance rules and could behave poorly on
  invalid intermediate buffers. Use fixed token scans over in-memory text instead.
- Removing two non-contiguous characters through one replacement can misplace the cursor if the cursor math is vague.
  Pin cursor offsets in pure-helper tests before adding widget integration coverage.

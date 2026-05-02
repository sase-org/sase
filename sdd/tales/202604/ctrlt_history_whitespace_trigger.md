---
create_time: 2026-04-23 15:00:55
status: done
prompt: sdd/prompts/202604/ctrlt_history_whitespace_trigger.md
---

# Plan: Loosen Ctrl+T File-History Trigger to Any Whitespace Cursor Context

## Problem / Goal

The `<ctrl+t>` file-history completion added in commit `72231478` only fires when the entire portion of the current line
before the cursor is whitespace-only. In practice the user triggers it from three natural positions:

1. **Beginning of a blank line** — works today. ✅
2. **End of a line that already has text** (e.g. `"look at "|`, trailing space) — silently does nothing. ❌
3. **Middle of a sentence with whitespace on both sides of the cursor** (e.g. `"foo | bar"`, cursor between two spaces)
   — silently does nothing. ❌

The user wants Ctrl+T to work in all three cases.

## Root Cause

The trigger lives in `src/sase/ace/tui/widgets/_file_completion.py`:

```python
def _cursor_at_empty_prefix(self) -> bool:
    row, col = self.cursor_location
    line = self.document.get_line(row)
    return line[:col].strip() == ""   # entire prefix must be whitespace
```

and is gated in `_try_file_completion_tab`:

```python
if token_info is None:
    if self._cursor_at_empty_prefix():          # <-- too strict
        return self._try_file_history_completion()
    self._clear_file_completion()
    return False
```

For cases (2) and (3), `extract_token_around_cursor` correctly returns `None` (the cursor sits in whitespace), but the
line prefix contains other text, so `_cursor_at_empty_prefix()` is `False` and the history path is skipped. The mixin
falls through to `_clear_file_completion()` and the keypress appears to do nothing.

A symmetric over-restriction exists in `_refresh_file_completion_from_cursor`: once a `file_history` panel is open,
moving the cursor onto a non-empty line prefix dismisses it even if the cursor is still in whitespace.

## Proposed Fix

**Trigger rule (new):** show file-history whenever Ctrl+T is pressed and the cursor is not sitting on any token — i.e.
whenever `_extract_token_around_cursor()` returns `None`. The rest of the line is irrelevant.

That rule naturally covers all three desired cases:

| Scenario                           | `extract_token_around_cursor` | Behavior                          |
| ---------------------------------- | ----------------------------- | --------------------------------- | --------------- |
| Blank line, col 0                  | `None`                        | history ✓                         |
| `"look at "` trailing space, col 8 | `None`                        | history ✓ (new)                   |
| `"foo                              | bar"` between two spaces      | `None`                            | history ✓ (new) |
| `"~/foo"` on a path token          | non-None, path-like           | file completion (unchanged)       |
| `"#prompt"` on an xprompt token    | non-None, xprompt-like        | xprompt completion (unchanged)    |
| `"hello"` on a non-path word       | non-None, neither kind        | clears (unchanged — out of scope) |

The last row (cursor at the end of a word with no trailing space) intentionally keeps the current "clear" behavior.
Inserting a file path there would produce `"hello/path/to/file"` with no separator, which is almost never desired. A
user who wants history at that position can type a space first. Flag this in the Open Questions section for explicit
user sign-off.

## Scope

### In scope

1. **Drop the empty-prefix gate** from `_try_file_completion_tab`: call `_try_file_history_completion()` whenever
   `token_info is None`.
2. **Loosen refresh dismissal**: in `_refresh_file_completion_from_cursor`, dismiss a `file_history` panel only when
   `_extract_token_around_cursor()` returns a non-None token. Cursor movement into whitespace adjacent to other text
   must not dismiss.
3. **Remove `_cursor_at_empty_prefix`** (no remaining callers) to avoid dead code.
4. **Tests**:
   - Cursor at end of line with trailing space triggers history.
   - Cursor between two spaces in a non-empty line triggers history.
   - Cursor on a non-path-like word (e.g. "hello") still clears (documents intentional non-change).
   - Opening history then moving the cursor to another whitespace position keeps the panel open.
   - Opening history then typing a character (creating a token at the cursor) dismisses as before.

### Out of scope

- Triggering history when the cursor is on a non-path, non-xprompt word token (case "hello|" without trailing space).
  Pending user decision in Open Questions.
- Auto-inserting a leading space when accepting a history candidate. With the whitespace-cursor rule, the cursor is
  already in whitespace at accept time, so separators are user-controlled.
- Changes to the existing path- or xprompt-completion code paths.
- Any changes to history storage, extraction, or the Ctrl+D delete flow.

## Files Touched

| Kind | Path                                                   | Reason                                                                                                                                                        |
| ---- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Edit | `src/sase/ace/tui/widgets/_file_completion.py`         | Drop `_cursor_at_empty_prefix`; simplify trigger and refresh branches                                                                                         |
| Edit | `tests/ace/tui/widgets/test_prompt_file_completion.py` | Add end-of-line-trailing-space, mid-line-between-spaces, and refresh-preserves-panel cases; keep existing whitespace-prefix test (still valid under new rule) |

No production changes outside `_file_completion.py`. The existing `_try_file_history_completion`,
`_accept_file_completion`, and panel-display code all work unchanged: accept inserts at the cursor, panel already
handles the `file_history` kind.

## Testing Strategy

Extend `TestFileHistoryCompletion` in `tests/ace/tui/widgets/test_prompt_file_completion.py`:

1. `test_trailing_space_at_end_of_line_triggers_history`
   - `load_text("look at ")`, cursor at `(0, 8)`, press Ctrl+T → `_completion_kind == "file_history"`.

2. `test_cursor_between_two_spaces_triggers_history`
   - `load_text("foo  bar")`, cursor at `(0, 4)`, press Ctrl+T → history activates.

3. `test_cursor_on_plain_word_still_clears`
   - `load_text("hello")`, cursor at `(0, 5)`, press Ctrl+T → `_file_completion_active is False`. Documents the
     intentional non-change so a future regression is obvious.

4. `test_history_panel_survives_cursor_move_within_whitespace`
   - Seed history, trigger from an empty text area, then programmatically move the cursor to another whitespace
     position; assert `_file_completion_active` is still True and `_completion_kind == "file_history"`. Exercises the
     refresh path.

5. `test_typing_dismisses_history_panel` (if not already covered)
   - Trigger history, simulate typing a character so a token appears at the cursor, assert the panel clears.

Keep the existing `test_whitespace_prefix_triggers_history` — it remains a valid (narrower) case under the new rule.

Run `just check` before reporting done, per the repo convention.

## Open Questions

1. **Non-path word at cursor (e.g. `"hello|"` with no trailing space)** — should Ctrl+T show history there too? Current
   plan: no (preserves current clear behavior; avoids inserting a path with no separator). Confirm with user. If yes,
   the fix expands to also trigger when the token is neither path-like nor xprompt-like, and we should consider
   auto-prepending a space on accept.

2. **Single-line vs multi-line buffers** — the rule reads only the current line via `document.get_line(row)`
   (unchanged). Should cursor at col 0 of line N>0 behave like "beginning of line"? Under the new rule it still works:
   `extract_token_around_cursor` returns None for a blank line head, and a non-blank line head returns a token (so
   clears, matching existing behavior). No change needed.

## Risks / Non-Risks

- **Low risk — additive trigger loosening.** The only paths that change behavior are ones where today Ctrl+T silently
  does nothing. Any case that previously triggered path or xprompt completion still does.
- **No storage, persistence, or extraction changes.** The history file format, recording on prompt submission, and
  Ctrl+D deletion are untouched.
- **Test coverage scales linearly.** The new rule is simpler than the one it replaces, so the test surface shrinks
  rather than grows.

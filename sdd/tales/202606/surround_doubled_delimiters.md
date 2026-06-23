---
create_time: 2026-06-23 17:57:28
status: done
prompt: sdd/prompts/202606/surround_doubled_delimiters.md
---
# Fix doubled same-character surround delimiters

## Context

The prompt input widget supports Vim-surround-inspired normal-mode commands such as `ds"` and `cs"'`. These commands
work for a simple same-character surround, for example `"foobar"`, but fail when the surrounding delimiter appears
doubled on both sides, for example `""foobar""`.

The current same-character surround locator gathers every unescaped delimiter on the cursor line and pairs them
left-to-right:

- positions `[0, 1, 8, 9]` become pairs `(0, 1)` and `(8, 9)`.
- with the cursor inside `foobar`, neither pair encloses the cursor.
- `_surround_locations()` returns `None`, so `ds"` and `cs"` clear the pending mutation and become no-ops.

This is specific to same-character delimiters (`"`, `'`, backtick, and custom single-character surrounds). Bracket-like
surrounds already use nesting-aware text object logic.

## Plan

1. Add focused regression coverage in `tests/test_prompt_normal_mode_surround.py` for doubled same-character surrounds:
   - `ds"` inside `""foobar""` removes the nearest enclosing quote pair and leaves `"foobar"`.
   - `cs"'` inside `""foobar""` changes the nearest enclosing quote pair and leaves `"'foobar'"`.
   - cover at least one custom same-character delimiter such as `**foobar**` so the fix is not quote-specific.

2. Replace the left-to-right pairing algorithm used by `_same_char_surround_locations()` with cursor-centered matching:
   - find unescaped delimiter positions before and after the cursor.
   - pair the nearest valid delimiter before the cursor with the nearest valid delimiter after the cursor.
   - support the existing no-op behavior when either side is missing.
   - preserve escaping behavior by continuing to ignore backslash-escaped delimiters.

3. Thread the existing surround count through same-character surrounds if the implementation stays simple:
   - count `1` selects the nearest enclosing delimiter pair.
   - count `2` selects the next outer same-character pair, which naturally covers the outer quotes in `""foobar""`.
   - if this materially complicates the fix, keep the behavior unchanged for counts and limit the change to the
     regression case.

4. Keep the change local to prompt input normal-mode surround helpers. This is presentation/keybinding behavior, so it
   belongs in the Python TUI widget layer and does not require changes in the Rust core backend.

5. Verify with targeted tests first, then the required repository checks:
   - run `just install` before tests if the workspace venv is not current.
   - run `just test tests/test_prompt_normal_mode_surround.py`.
   - after source changes, run `just check` before reporting completion.

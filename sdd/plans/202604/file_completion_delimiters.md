---
create_time: 2026-04-12 18:34:55
status: done
prompt: sdd/prompts/202604/file_completion_delimiters.md
---

# Plan: Fix file completion token extraction near special characters

## Problem

When the user presses `<ctrl+t>` to trigger file completion, it fails if the cursor is directly to the left of a `?`
character (and likely other punctuation). For example, with text `~/foo?` and cursor at position 5 (between `o` and
`?`), the extracted token is `~/foo?` instead of `~/foo`, causing `build_completion_candidates` to fail because no file
named `foo?` exists.

## Root Cause

`_is_token_delimiter()` in `src/sase/ace/tui/widgets/file_completion.py:22-24` only treats whitespace and quote
characters as delimiters:

```python
def _is_token_delimiter(char: str) -> bool:
    return char.isspace() or char in {"'", '"', "`"}
```

The right-scan in `extract_token_around_cursor()` walks past `?` and other punctuation because they aren't recognized as
delimiters, absorbing them into the token.

## Fix

Expand `_is_token_delimiter()` to include common punctuation characters that are not valid parts of file path tokens.
Characters that ARE valid in paths and must NOT be delimiters: letters, digits, `-`, `_`, `.`, `/`, `~`, `@`, `#`.
Characters that should be delimiters (in addition to whitespace and quotes):

`?`, `!`, `;`, `,`, `(`, `)`, `[`, `]`, `{`, `}`, `<`, `>`, `|`, `&`, `=`, `+`, `*`, `^`, `%`, `$`, `:`, `\`

## Files to Change

1. **`src/sase/ace/tui/widgets/file_completion.py`** — Update `_is_token_delimiter()` to include the additional
   delimiter characters.

2. **`tests/ace/tui/widgets/test_prompt_file_completion.py`** — Add test cases for `extract_token_around_cursor` with
   special characters adjacent to path tokens (e.g., `~/foo?`, `check: ~/Downloads`, `(~/src/)`).

---
create_time: 2026-04-01 14:12:22
status: done
prompt: sdd/prompts/202604/at_prefix_file_completion.md
---

# Plan: Fix file completion for @-prefixed file paths

## Problem

The prompt input widget's file completion feature doesn't work when the file path is prefixed with `@` (e.g.,
`@~/foo<tab>`). The `@` prefix is used throughout the codebase as a file reference syntax (see
`gemini_wrapper/file_references.py`, `xprompt/_step_input_loader.py`), so users naturally type `@~/path` and expect Tab
completion to work.

## Root Cause

The issue is in `src/sase/ace/tui/widgets/file_completion.py`:

1. **`is_path_like_token`**: Happens to return `True` for most `@`-prefixed paths (because they contain `/`), but
   doesn't explicitly handle `@` — so edge cases like `@.sase` (no slash) would fail.

2. **`build_completion_candidates`**: The real blocker. When given `@~/foo`, it passes `@~/foo` to
   `os.path.expanduser()`, which does NOT expand `@~/` because expanduser only recognizes tokens starting with `~`, not
   `@~`. This causes `os.scandir` to fail on the unexpanded path, returning zero candidates.

## Design

The fix is contained entirely in the pure-logic `file_completion.py` module — no widget-level changes needed.

### Approach: Strip-and-restore `@` prefix

Both `is_path_like_token` and `build_completion_candidates` will strip a leading `@` before their core logic, and
`build_completion_candidates` will prepend it back onto `insertion` strings in the returned candidates.

This is clean because:

- Token extraction (`extract_token_around_cursor`) already treats `@` as a non-delimiter, so `@~/foo` is extracted as a
  single token.
- The widget methods (`_try_file_completion_tab`, `_accept_file_completion`, `_refresh_file_completion_from_cursor`) all
  pass tokens through to these functions and use the returned `insertion` values — so the `@` prefix flows through
  transparently.
- Shared extension calculation is unaffected (it's based on `name`, not `insertion`).

### Changes

**`file_completion.py`**:

- `is_path_like_token`: Strip single leading `@` before checking path patterns.
- `build_completion_candidates`: Strip single leading `@` at entry, run all existing logic on the bare path, then
  prepend `@` back onto each candidate's `insertion` field before returning.

**`test_prompt_file_completion.py`**:

- Add `@`-prefix cases to `test_is_path_like_token` (unit tests for the detection function).
- Add integration test: `@~/` triggers completion, candidates have `@`-prefixed insertions.
- Add integration test: `@~/al<tab>` single-match inserts `@~/alpha/`.
- Add integration test: `@`-prefixed directory drill-down works (accept `@~/alpha/` re-triggers completion).

---
create_time: 2026-04-12 20:25:23
status: done
prompt: sdd/prompts/202604/alt_shorthand.md
---

# Plan: `%(...)` shorthand for `%alt(...)`

## Goal

Add `%(<arg1>, <arg2>, ...)` as syntactic sugar that is equivalent to `%alt(<arg1>, <arg2>, ...)`. This gives users a
terse way to split prompts into alternatives without typing the `alt` keyword.

## Design

**Approach: extend the existing regex to match both `%alt(` and `%(`.**

The `%(` pattern is unambiguous — no existing directive uses `%` immediately followed by `(` (all directives have a name
between `%` and `(`). The positional lookbehind already prevents false positives from prose like "50% (margin)" since
`%` must follow start-of-line, whitespace, or `([{"'`.

The end-to-end pipeline (launcher, TUI, daemon routing) all funnel through `split_prompt_for_models()` →
`_split_prompt_for_alternatives()`, so changes are confined to the regex/detection layer in `directives.py` plus tests.

## Changes

### Phase 1: Update `_ALT_DIRECTIVE_RE` regex (`directives.py`)

Change the capture group from `(%alt)` to `(%(?:alt)?)` so it matches both `%alt(` and `%(`. The rest of
`_split_prompt_for_alternatives` works unchanged — `match.start(1)` still gives the start of the directive text, and the
replacement logic replaces from there through the closing `)`.

### Phase 2: Update `has_alt_directive()` (`directives.py`)

Extend its quick-check regex from `%alt\(` to `%(?:alt)?\(` so CLI auto-daemon routing also detects the shorthand.

### Phase 3: Update error messages and docstrings (`directives.py`)

- Error for multiple directives: mention both `%alt(...)` and `%(...)`
- Docstrings for `_split_prompt_for_alternatives`, `has_alt_directive`, `split_prompt_for_models`: mention the shorthand

### Phase 4: Tests (`test_directives_helpers.py`)

Add tests covering the shorthand syntax:

- `%(a,b)` two-arg split (mirrors existing `%alt(a,b)` test)
- `%(only_one)` single-arg implicit empty variant
- `%(a,b)` combined with `%alt(c,d)` raises multiple-alt error
- `has_alt_directive` detects `%(`
- `has_alt_directive` returns False for `%` without `(` (no regression)

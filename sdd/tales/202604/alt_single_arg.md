---
create_time: 2026-04-12 20:17:41
status: done
prompt: sdd/prompts/202604/alt_single_arg.md
---

# Plan: `%alt` single-arg as implicit split with empty variant

## Problem

Currently, `%alt(foo)` with a single argument returns `None` (no split) — the directive is effectively ignored. This is
unintuitive. A more useful behavior: treat `%alt(foo)` the same as `%alt(foo,)`, producing two prompts — one where
`%alt(foo)` is replaced with `foo`, and one where the directive is removed entirely (the empty-string variant).

This enables a natural "with/without" pattern: `%alt(%m:opus) Review this code` spawns one agent with the opus model
override and one with the default model.

## Design

**Semantics**: A single-arg `%alt` means "run one variant _with_ this text and one _without_." The explicit arg comes
first, the empty (removal) variant comes second. This is equivalent to appending an implicit empty arg.

**Scope boundary**: This change is limited to `_split_prompt_for_alternatives()`. The `%m(single_model)` path in
`split_prompt_for_models()` is unaffected — it gates on `len(positional_args) > 1` _before_ rewriting to `%alt(...)`, so
`%m(opus)` continues to return `None` (single model, no split).

**Zero-arg edge case**: `%alt()` should remain a no-op (return `None`). Only exactly-one-arg triggers the implicit
empty.

## Changes

### Phase 1: Core logic (`src/sase/xprompt/directives.py`)

In `_split_prompt_for_alternatives()` (~line 212):

- Change the guard from `if len(positional_args) <= 1: return None` to:
  - `== 0` → return `None`
  - `== 1` → append `""` to `positional_args`, then fall through to the existing replacement loop
- Update the docstring to document the new single-arg behavior

### Phase 2: Tests (`tests/test_directives_helpers.py`)

- **Modify** `test_split_prompt_for_alternatives_single_arg_returns_none` — rename it and update to assert the new
  two-prompt output instead of `None`
- **Add** test: single arg with directive on its own line (verify leading newline in the removal variant is acceptable)
- **Add** test: single arg with nested directive (`%alt(%m:opus)` produces one prompt with `%m:opus` and one without)
- **Add** test: `%alt()` (zero args) still returns `None`
- **Add** test: `split_prompt_for_models` with `%m(opus)` still returns `None` (regression guard)

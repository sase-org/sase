---
create_time: 2026-04-13 12:22:40
status: done
prompt: sdd/prompts/202604/multi_alt.md
---

# Plan: Multiple `%alt` / `%(...)` Directives via Cartesian Product

## Problem

Currently, `_split_prompt_for_alternatives()` raises `DirectiveError` when a prompt contains more than one `%alt(...)` /
`%(...)` directive. Users want to combine multiple alternation points in a single prompt, producing one agent per
combination.

Example: `%(Focus on security, Focus on perf) %m(opus, sonnet) Review this code` should launch 4 agents (2 focus areas x
2 models).

## Design

Replace the "multiple `%alt` is an error" logic with Cartesian product expansion. Given N `%alt`/`%(` directives with
argument counts `a₁, a₂, ..., aₙ`, produce `a₁ × a₂ × ... × aₙ` prompts.

### Algorithm

1. Find all `%alt(` / `%(` matches (already collected via `_ALT_DIRECTIVE_RE.finditer`)
2. For each match, find matching close-paren and parse arguments (existing helpers)
3. Apply single-arg implicit-empty-variant expansion to each directive independently
4. Compute the Cartesian product using `itertools.product`
5. For each combination, build a prompt by replacing directive spans — process replacements **right-to-left** so earlier
   character positions aren't shifted by later substitutions

### `%model(a,b)` Interaction

`split_prompt_for_models()` rewrites `%model(opus,sonnet)` → `%alt(%model:opus,%model:sonnet)` before calling
`_split_prompt_for_alternatives()`. If the user also wrote their own `%(...)`, the rewritten prompt now has two `%alt`
directives — which the new Cartesian product logic handles naturally. No changes needed to `split_prompt_for_models()`.

## Phases

### Phase 1: Update `_split_prompt_for_alternatives()` in `directives.py`

**File: `src/sase/xprompt/directives.py`**

- Remove the `len(matches) > 1` error
- Collect all directive spans: for each match, use `find_matching_paren_for_args()` + `parse_args()` to get the argument
  list and the full span (start of `%alt`/`%(` through closing `)`)
- Apply single-arg implicit-empty-variant to each directive's args independently
- Use `itertools.product(*all_arg_lists)` to get all combinations
- For each combination, substitute all directive spans in reverse position order
- Update the docstring to document the Cartesian product behavior

### Phase 2: Update tests

**File: `tests/test_directives_helpers.py`**

- Change `test_split_prompt_for_alternatives_multiple_alt_raises` → test that two `%alt` directives produce the
  Cartesian product (2×2 = 4 prompts)
- Change `test_split_prompt_for_alternatives_shorthand_mixed_with_alt_raises` → test that `%(a,b) %alt(c,d)` produces 4
  prompts
- Add test: three directives (2×2×3 = 12 prompts)
- Add test: one directive with single-arg (implicit empty) combined with another (2×2 = 4 prompts)
- Add test: `%model(opus,sonnet)` combined with user `%(x,y)` produces 4 prompts via `split_prompt_for_models()`

### Phase 3: Update documentation

**File: `docs/xprompt.md`**

- Replace the "Only one `%alt`/`%(` directive is allowed per prompt" sentence
- Add a short section showing multiple directives and the Cartesian product behavior with an example

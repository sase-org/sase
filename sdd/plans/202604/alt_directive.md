---
create_time: 2026-04-12 19:55:43
status: done
prompt: sdd/prompts/202604/alt_directive.md
---

# Plan: `%alt` Directive for Prompt Splitting

## Problem

Currently, `%m(opus,sonnet)` is a special-cased directive that spawns multiple agents (one per model). This is the only
way to fan out a prompt into multiple agents with variations. Users need a general mechanism to run the same prompt with
arbitrary text variations — not just model names.

## Design

### New `%alt(<text1>,<text2>,...)` Directive

`%alt` is a **splitting directive** — it operates at the prompt-splitting level (like `%m(a,b)` today), not at the
directive-extraction level (it does NOT become a field on `PromptDirectives`). When the launcher encounters `%alt`, it
produces N prompts by replacing the `%alt(...)` span with each argument text in turn.

Example:

```
%alt(%m:opus, %m:sonnet)
Review this code
```

Produces two prompts:

- `%m:opus\nReview this code`
- `%m:sonnet\nReview this code`

The arguments can be arbitrary text — directives, xprompt references, plain instructions:

```
%alt([[Focus on security]], [[Focus on performance]])
Review this code
```

### `%m(a,b)` Becomes Shorthand

`%m(opus,sonnet)` is rewritten to `%alt(%m:opus,%m:sonnet)` internally, then the `%alt` splitter handles it. This
preserves full backward compatibility while eliminating the special-cased model splitting logic.

### Error on Multiple `%alt` Directives

A prompt with more than one `%alt(...)` is an error (no cartesian product). This matches the single-value semantics of
most other directives.

## Phases

### Phase 1: Core splitting function in `directives.py`

**File: `src/sase/xprompt/directives.py`**

Add `split_prompt_for_alternatives()`:

- Use a regex to find `%alt(` (matching start-of-string, whitespace, or `([{"'` before it — same boundary rules as other
  directives).
- Use `find_matching_paren_for_args()` to find the closing `)` (handles nested parens, quotes, text blocks).
- Use `parse_args()` to extract the comma-separated arguments.
- If only 1 argument, return `None` (not a split).
- If multiple `%alt(...)` matches exist, raise `DirectiveError`.
- For each arg, produce a new prompt by replacing the `%alt(...)` span with the arg text.
- Return `list[str] | None`.

Rewrite `split_prompt_for_models()`:

- Keep detecting `%m(a,b,...)` / `%model(a,b,...)` with the existing `_MULTI_MODEL_RE`.
- If found with >1 model: rewrite to `%alt(%m:a,%m:b,...)` in-place, then delegate to `split_prompt_for_alternatives()`.
- If no multi-model found: delegate to `split_prompt_for_alternatives()` anyway (to catch direct `%alt` usage).
- This makes `split_prompt_for_models` the single entry point for all prompt splitting — callers don't change.

Add a `has_alt_directive()` quick-check function (following the `has_wait_directive` / `has_model_directive` pattern)
for use in the CLI auto-daemon routing.

### Phase 2: Update CLI auto-daemon routing

**File: `src/sase/main/query_handler/special_cases.py`**

In `_run_query()`, after the existing `is_multi_prompt()` check, add a check for `%alt` / multi-model prompts. If
`split_prompt_for_models()` returns non-None (meaning the prompt will split), auto-route to daemon mode — just like
multi-prompts already do. This ensures `sase run "%alt(...) do work"` spawns multiple agents without requiring `-d`.

**File: `src/sase/agent/launcher.py`**

In `launch_agent_from_cwd()`, after the multi-prompt detection block, add alt-splitting support: call
`split_prompt_for_models()`, and if it returns multiple prompts, spawn each one (similar to how multi-prompt segments
are launched, but without naming-wait between them since alt-splits are independent).

### Phase 3: Tests

**File: `tests/test_directives_helpers.py`**

New tests for `split_prompt_for_alternatives`:

- Two/three alternatives produce correct prompts
- Single alternative returns None
- No `%alt` returns None
- Preserves other directives
- Handles text-block args `[[...]]`
- Handles nested directives in args (e.g., `%m:opus`)
- Multiple `%alt` directives raises `DirectiveError`

Update existing `split_prompt_for_models` tests:

- `%m(opus,sonnet)` still produces correct output (backward compat)
- Direct `%alt(%m:opus,%m:sonnet)` produces the same output as `%m(opus,sonnet)`

Add `has_alt_directive` tests (following existing `has_wait_directive` / `has_model_directive` patterns).

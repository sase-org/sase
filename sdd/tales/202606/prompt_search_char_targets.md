---
create_time: 2026-06-21 09:45:13
status: done
prompt: sdd/prompts/202606/prompt_search_char_targets.md
---
# Fix prompt Vim char-target search key regression

## Problem

The prompt input widget recently added Vim-style `/` and `?` search entry from NORMAL mode. Bare `/` and `?` work, but
the new dispatch path now intercepts those characters before pending Vim state is resolved. As a result, character
target motions that need `/` or `?` as literal target characters are broken. For example, `dt/` should delete from the
cursor up to the next `/`, but the final `/` opens the prompt search command line instead.

Inline repro using the existing isolated `PromptPage` fixture shows:

- `dt/` on `foo/bar baz` at column 3 leaves text unchanged and activates prompt search.
- `dt?` on `foo?bar baz` at column 3 leaves text unchanged and activates prompt search.
- Bare `/` still activates prompt search, which is the behavior to preserve.

The likely root cause is in `PromptTextArea` NORMAL-mode dispatch: the `/` / `?` prompt-search check runs before pending
normal-mode sequences are handled. This makes `/` and `?` global NORMAL-mode triggers even when a pending `f`, `F`, `t`,
or `T` sequence is waiting for its target character.

## Plan

1. Tighten prompt-search trigger eligibility

   Adjust the NORMAL-mode `/` / `?` search entry check so it only opens prompt search when the key is a top-level NORMAL
   command. It should not fire when any pending Vim state needs the next key, especially:
   - `_pending_keys` is set to a motion prefix such as `f`, `F`, `t`, or `T`.
   - `_pending_operator` is set and the next key may start an operator motion.
   - `_count_prefix` is present in a way that still needs motion resolution.

   The practical shape should be small and local: either move the search-entry branch after pending-key handling, or
   guard it with a helper like `_can_start_prompt_search_from_normal_key()`. The guard/helper is preferable if it makes
   the intent explicit and keeps future prompt-local key additions from repeating this bug.

2. Preserve bare prompt search semantics

   Keep bare `/` and bare `?` in NORMAL mode opening the existing incremental search command line. Ensure the search
   path still clears pending state when it legitimately starts search, and keep `n` / `N` repeat behavior unchanged.

3. Add regression tests around literal `/` and `?` char targets

   Extend the existing focused char-search tests rather than introducing a new broad integration suite. Cover the
   affected combinations directly:
   - `t/` moves to the character before `/`.
   - `f/` moves onto `/`.
   - `dt/` deletes up to but not including `/`.
   - `df/` deletes through `/`.
   - Equivalent `?` target coverage for at least `t?` and `dt?`.

   Also include one assertion that bare `/` still activates prompt search, so the regression test protects both sides of
   the conflict.

4. Verify narrowly, then run repository checks

   First run the targeted prompt normal-mode char-search tests. If file changes are made, follow project instructions:
   run `just install` if the workspace may need dependency refresh, then `just check` before final response.

## Risks and notes

- This should remain presentation/input-widget code only; it does not cross into the Rust core backend boundary.
- No default keymap configuration changes are expected because the behavior is dispatch precedence within the prompt
  widget, not a configurable app keymap.
- The main risk is accidentally disabling legitimate bare `/` / `?` search after counts or other prefixes. Tests should
  focus on the user-facing conflict while avoiding overfitting to private state names.

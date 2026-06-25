---
create_time: 2026-06-25 14:23:53
status: done
prompt: sdd/prompts/202606/bare_percent_directive_completion.md
---
# Plan: Bare Percent Directive Completion

## Goal

Let the ACE prompt input open the xprompt directive completion menu as soon as the user types a directive-valid bare
`%`, instead of waiting for a following directive identifier character. Keep the existing behavior for xprompt
references (`#`) and slash skills (`/`) unchanged for now.

## Current Behavior

Prompt completion is handled in the ACE TUI prompt widgets:

- `PromptTextAreaKeyHandlingMixin._open_auto_reference_completion_after_change()` runs after printable character
  insertion when automatic xprompt or directive menus are enabled.
- `FileCompletionOpenMixin._try_auto_prompt_reference_completion()` gives directive completion precedence over xprompt
  and slash-skill completion.
- `_try_auto_directive_completion()` already knows how to build candidates for `%`, but it explicitly returns early for
  bare `%`.
- Explicit completion already works at bare `%`: `Ctrl+T` at `%` opens the directive panel.
- Tests currently lock in the old auto-open behavior with `test_bare_percent_does_not_auto_open()`.

This is a small behavior change in the existing fast path. It should not add synchronous disk I/O or catalog loading to
the keystroke path; directive completion candidates are local/static metadata.

## Implementation Approach

1. Update directive auto-open policy in `src/sase/ace/tui/widgets/_file_completion_open.py`.
   - Remove or relax the `len(token) < 2` guard in `_try_auto_directive_completion()`.
   - Continue requiring `_get_directive_token_context()` and `is_directive_like_token(token)` so invalid contexts like
     `word%` and `50%` stay quiet.
   - Continue returning `False` when no candidates exist, preserving the existing unknown-directive behavior.

2. Preserve current non-goals.
   - Do not auto-open bare `#` or bare `/` in this change.
   - Do not change explicit `Ctrl+T` behavior.
   - Do not change the completion settings shape; the existing `auto_directive_menu` gate should control the new bare
     `%` behavior too.

3. Add/update focused tests.
   - Replace `test_bare_percent_does_not_auto_open()` with a test that typing `%` opens the directive menu immediately,
     leaves the text as `%`, sets `_completion_kind == "directive"`, and renders the `directives` panel.
   - Keep or add coverage that `auto_directive_menu=False` still prevents bare `%` auto-open.
   - Keep existing invalid-context coverage (`word%m`) and unknown-directive coverage (`%z`) passing.
   - Add a regression around `%` then `{` in prompt mode if needed: the directive menu should be cleared by existing
     paired-alt editing, and the resulting text should still be `%{  }`.

4. Verify targeted behavior first, then run the repo check required after source changes.
   - Run focused tests for directive interactions and auto xprompt completion:
     `pytest tests/ace/tui/widgets/test_directive_completion_interactions.py tests/ace/tui/widgets/test_auto_xprompt_completion.py`.
   - Run any added alt-syntax regression test if it lands outside those files.
   - Run `just check` after implementation, following project instructions for source changes.

## Risks And Mitigations

- Opening the menu on `%` could interfere with `%{...}` alt shorthand. Mitigation: rely on existing paired-edit code to
  clear active completion state, and add a regression test if the behavior is not already covered.
- The directive panel may be more visually eager than xprompt/slash menus. This is intentional for `%` only and remains
  behind the existing `auto_directive_menu` setting.
- Keystroke performance should stay stable because directive candidates are built from static in-process metadata; no
  file, subprocess, or catalog work is introduced.

---
create_time: 2026-06-25 08:19:30
status: done
prompt: sdd/prompts/202606/fork_spacer_colon_completion.md
---
# Plan: Trigger agent-name completion after the `#fork` optional-spacer `:` rewrite

## Problem / Product Context

We recently added agent-name completion to the `#fork` xprompt argument: typing `#fork:` (or `#fork(`) pops an inline
menu of the currently-visible agents so the user can pick one to resume.

We also added a convenience for optional-only xprompts: when the user accepts `#fork` from the xprompt completion menu,
it expands to `#fork ` (with a deliberate trailing space). If the user then types `:`, we delete that trailing space in
place so the prompt becomes `#fork:` — saving the user a manual `<backspace>` before they can start typing the colon
argument.

**The bug:** the two features do not compose. When the trailing space is auto-deleted by typing `:`, the agent-name
completion menu does **not** open. The user currently has to type `<backspace>` and then `:` again to get the menu to
appear. We want the menu to open immediately after the space is deleted — i.e. `#fork ` + `:` should behave exactly like
a manually typed `#fork:`.

This affects any optional-only xprompt whose next argument has value completions (today: `#fork`'s `agent` argument; the
same path also covers `path`/`bool` arguments), so the fix should be general rather than `#fork`-specific.

## Root Cause

The prompt input widget is `PromptTextArea`. Its key handler intercepts the typed `:` **before** the normal
text-insertion path:

- `PromptTextArea._on_key` (`src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py`): at the top of the handler,
  when a `_pending_optional_spacer` is set and the typed character is `:`, it calls
  `_consume_optional_spacer_colon(...)`. On success it immediately calls `event.stop()`, `event.prevent_default()`, and
  `return`s.
- `_consume_optional_spacer_colon` (`src/sase/ace/tui/widgets/_xprompt_arg_hints.py`) rewrites the trailing space to `:`
  in place and refreshes the inline argument hint.

Because the handler returns early, it never reaches the **normal post-insert tail** at the bottom of `_on_key` (after
`await super()._on_key(event)`), which is what opens completion menus while typing. That tail calls
`_try_auto_prompt_reference_completion()` (gated on INSERT mode, no menu already active, the relevant auto-menu setting,
and the typed char being a printable non-whitespace "reference" character). For a normally-typed `#fork:`, that tail
runs and routes through `_try_auto_xprompt_arg_completion()` → the agent-name menu. For the consumed `:`, the tail is
skipped, so the menu never opens.

This is why `<backspace>:` works (it goes through the normal insertion + tail) but the in-place rewrite does not.

### Ordering subtlety (must be preserved)

`_refresh_xprompt_arg_hint_from_cursor` early-returns when a completion menu is already active. The normal tail
therefore opens the menu **first**, then refreshes the inline hint (so the inline hint is suppressed while the menu is
showing). The current consume path refreshes the hint _before_ any menu exists. The fix must open the menu and then
settle the hint in the same order as the normal path, so we don't end up with a stale inline hint rendered underneath
the menu.

## High-Level Design

Make the optional-spacer `:` rewrite run the **same** "after a text change, maybe open the argument-completion menu"
logic that a normally-typed character runs. Concretely:

1. **Factor out the post-insert completion tail** of `_on_key` into a single small private helper on the key-handling
   mixin (e.g. `_open_auto_reference_completion_after_change(character)`). It should encapsulate the existing behavior
   currently inlined at the end of `_on_key`:
   - the INSERT-mode / not-already-active / auto-menu-setting / "is auto-menu character" gate,
   - the call to `_try_auto_prompt_reference_completion()`,
   - followed by refreshing the inline xprompt-arg hint and notifying that the completion context changed.

   The end of `_on_key` then just calls this helper, so its observable behavior is unchanged.

2. **Call the same helper from the consume branch.** After `_consume_optional_spacer_colon` succeeds (the text is now
   `#fork:` with the cursor right after the colon), call the helper before `event.stop()/prevent_default()/return`. This
   opens the agent-name menu exactly as the normal path would.

3. **Keep hint ordering correct.** Because the helper opens the menu first and then refreshes the hint (which no-ops
   while a menu is active), the inline hint will be correctly suppressed when the menu opens. To avoid the hint being
   shown _before_ the menu (and then left stale), the redundant inline-hint refresh currently performed inside
   `_consume_optional_spacer_colon` should be dropped in favor of the helper's refresh —
   `_consume_optional_spacer_colon` is only called from this one place, so the caller can own the post-rewrite refresh.
   The net effect matches a typed `:`:
   - menu opens → inline hint suppressed;
   - menu does not open (setting disabled, or no candidates) → inline hint shown for `#fork:`.

This keeps the change tiny and routes both the typed-`:` and the rewritten-`:` cases through one code path, so they
cannot drift.

### Why this is the right layer

This is presentation-only Textual key-handling glue: it changes _when_ an existing completion trigger runs, not the
grammar that recognizes `#fork:` argument tokens (which already lives in this repo's Python xprompt-arg machinery and
correctly detects the agent argument). No Rust core / `sase-core` changes are required.

### Scope notes

- The optional-spacer mechanism is specific to xprompt accepts; `%wait` is a directive and never gets a trailing spacer,
  so this fix is naturally scoped to the xprompt path. No `%wait` change is needed.
- The fix is general: it reuses `_try_auto_prompt_reference_completion()`, so an optional-only xprompt whose next
  argument is a `path` or `bool` (not just `agent`) will also correctly open its value menu after the spacer rewrite —
  matching typed-`:` behavior.

## Testing

Existing coverage to lean on:

- `tests/ace/tui/widgets/test_xprompt_optional_spacer.py` — the optional-spacer `:` rewrite (accept-from-menu,
  soft-completion, selector insertion, no-input-not-rewritten, intervening-keystroke-clears). These assert text +
  `_pending_optional_spacer` and must still pass.
- `tests/ace/tui/widgets/test_xprompt_arg_value_completion.py` — the `#fork:` agent menu, including the
  auto-menu-opens-on-typed-`:` and respects-disabled-gate tests. The helper refactor must not change these.

New regression test (the core of this change): after accepting an optional-only `#fork`-style entry (single optional
`agent` input) and typing `:`, assert that **in addition** to `text == "#fork:"` and `_pending_optional_spacer is None`,
the agent-name menu is now open:

- `_file_completion_active is True`,
- `_completion_kind == "xprompt_arg_agent"`,
- the candidate list matches the seeded visible agents.

This belongs alongside the other optional-spacer tests (using the existing `CompletionTestApp`, `_ENTRY_PATCH`, and
`ctrl+t`-then-`:` pattern), with the visible agent candidates supplied via `app.visible_agent_completion_candidates` and
an entry whose single input is an optional `agent` argument — mirroring the real `fork.yml`
(`name: {type: agent, default: null}`) and the `_agent_candidate` helper already used in
`test_xprompt_arg_value_completion.py`.

Optionally, a companion test that the disabled `auto_xprompt_menu` gate keeps the menu closed after the rewrite (text
becomes `#fork:`, no menu) — confirming the rewrite path honors the same setting as the typed path.

## Verification

- `just install` then `just check` (lint + mypy + tests) in the workspace.
- Manual smoke in `sase ace`: open the prompt, type `#fork`, accept it from the completion menu (leaving `#fork `), type
  `:`, and confirm the fork-agent menu opens immediately (no `<backspace>` needed), with the inline hint suppressed
  while the menu is showing.

## Files Expected to Change

- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` — extract the post-insert completion tail into a helper;
  call it from the optional-spacer `:` consume branch.
- `src/sase/ace/tui/widgets/_xprompt_arg_hints.py` — drop the now-redundant inline-hint refresh inside
  `_consume_optional_spacer_colon` (the caller's helper refreshes in the correct order).
- `tests/ace/tui/widgets/test_xprompt_optional_spacer.py` — add the regression test(s) above.

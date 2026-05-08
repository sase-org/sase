---
create_time: 2026-05-08 11:08:47
status: done
prompt: sdd/prompts/202605/hash_at_smart_args.md
---
# Plan: Smart xprompt arguments for #@

## Context

The prompt input already has smart argument support for `<ctrl+t>` xprompt completion. That path accepts xprompt
candidates through `xprompt_completion_skeleton()`, which uses the selected entry metadata to choose the inserted form:

- no required inputs: insert the reference plus a trailing space;
- one required input: insert colon syntax, using `::` for `text` and `:` for other types;
- multiple required inputs: insert a parenthesized snippet with tabstop support.

The `#@` flow is separate. Typing `#@` posts `PromptInputBar.SnippetRequested`, opens `XPromptSelectModal`, and returns
only the selected reference suffix. `PromptInputBar.insert_snippet()` inserts that suffix after the already-present `#`,
then shows post-accept argument hints. This gives hints and manual `:` / `(` actions, but it does not apply the same
smart skeleton or tabstop behavior that `<ctrl+t>` now has.

## Goals

Add equivalent smart argument insertion for xprompts selected through `#@`.

The intended user-visible behavior:

- selecting an xprompt with no required inputs inserts the full reference in a ready-to-continue form, matching
  `<ctrl+t>`;
- selecting an xprompt with one required input inserts colon syntax immediately, with `::` for text inputs;
- selecting an xprompt with multiple required inputs inserts the named/parenthesized smart skeleton with tabstops;
- existing standalone markers stay correct: selecting a `#!` workflow after typing `#@` must still produce `#!name...`;
- the argument hint panel remains consistent after insertion, especially for colon syntax;
- project-local xprompt selection via leading VCS tag continues to work.

## Proposed Design

Reuse the existing pure assist model and skeleton builder rather than creating a second set of rules in the modal.

1. Extend the `#@` insertion path to accept selected xprompt metadata, not just a string suffix.

   `XPromptSelectModal` already has the selected `Workflow` object and already computes the display prefix/suffix. It
   can build or expose an insertion payload that includes:
   - the suffix to insert after the already-typed `#`;
   - an `XPromptAssistEntry`-equivalent or enough workflow metadata for `PromptInputBar` to resolve the same entry from
     its cached assist catalog.

2. Keep smart insertion in `PromptInputBar` / `PromptTextArea`, where snippet expansion, cursor movement, active hints,
   and tabstops already live.

   Add a new prompt-bar method, or extend `insert_snippet()`, that can:
   - replace the selected range after the already-typed `#`;
   - when metadata is available, build the same smart skeleton used by `<ctrl+t>`;
   - adapt the skeleton for `#@` by removing the initial `#` because the trigger’s `#` is already present;
   - call `_expand_snippet_template_at_range()` when the skeleton contains tabstops;
   - otherwise use `_replace_via_keyboard()` and refresh the xprompt arg hint state.

3. Preserve existing fallback behavior.

   If metadata resolution fails, keep the current literal suffix insertion plus
   `_maybe_show_inserted_xprompt_arg_hint()` path. This prevents the modal from becoming fragile if a prompt is present
   in the modal catalog but missing from the assist catalog for any reason.

4. Prefer one canonical skeleton helper.

   Continue to use `xprompt_completion_skeleton()` from `xprompt_arg_assist.py` as the source of truth. If the helper
   needs a tiny companion for “suffix after an existing hash”, add it next to the existing helper and cover it with pure
   tests.

## Test Plan

Add focused TUI widget/modal tests:

- `#@` inserting an xprompt with no required inputs adds the same trailing space behavior as `<ctrl+t>`.
- `#@` inserting one required path input yields `#review:` and shows the xprompt args hint.
- `#@` inserting one required text input yields `#ask::`.
- `#@` inserting multiple required inputs yields a parenthesized snippet and tabstop navigation works.
- `#@` inserting a standalone workflow still yields `#!workflow` with the smart suffix applied when relevant.
- Existing `XPromptSelectModal._insertion_suffix()` behavior remains covered or is replaced by equivalent payload tests.

Run targeted tests first:

```bash
just install
pytest tests/ace/tui/widgets/test_xprompt_arg_hints.py tests/ace/tui/modals/test_xprompt_select_modal.py tests/ace/tui/widgets/test_xprompt_arg_value_completion.py
```

Then run the repository check required by local instructions:

```bash
just check
```

## Risks and Mitigations

- The modal currently returns `str | None`; changing the result type can affect callers. Keep the public callback
  handling narrow and update the only known caller, or return a string-compatible payload only if Textual typing makes
  that easier.
- `#@` selection begins with an existing `#`, so blindly inserting a full skeleton would duplicate the marker. Strip
  exactly one leading `#` from `#...` / `#!...` skeletons before insertion.
- Post-insertion hint state can be lost if snippet expansion clears it. For colon syntax, explicitly refresh hint
  detection after insertion. For parenthesized snippets, rely on snippet tabstops, matching the existing named-argument
  action behavior.

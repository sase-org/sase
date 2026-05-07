---
create_time: 2026-05-07 14:54:58
status: done
prompt: sdd/prompts/202605/tui_xprompt_completion_expansion.md
---
# TUI XPrompt Completion Expansion Plan

## Goal

Bring the ACE TUI prompt input widget in line with the xprompt LSP completion behavior implemented in `sase-core`: when
a user accepts an xprompt completion, the widget should insert the appropriate required-input skeleton directly instead
of only inserting the bare reference and relying on the follow-up argument hint.

The target expansion rules are:

- No required user-facing inputs, including optional-only prompts: `#foo `
- One required non-`text` input: `#foo:`
- One required `text` input: `#foo::`
- Multiple required inputs: `#foo($0)`, which renders as `#foo()` with the cursor inside the parentheses

The same rules should apply to normal `#foo` xprompts and `#!foo` standalone workflow references. Slash-skill
completions (`/sase_plan`) should remain canonical slash references and should not receive xprompt argument skeletons.

## Current Behavior

The TUI path is split across a few small pieces:

- `src/sase/ace/tui/widgets/xprompt_completion.py` builds xprompt completion candidates from
  `build_xprompt_assist_entries()`.
- `src/sase/ace/tui/widgets/_file_completion.py` owns Ctrl+T completion, completion-panel navigation, and candidate
  acceptance.
- `src/sase/ace/tui/widgets/xprompt_arg_assist.py` already contains required-input helpers and named/colon skeleton
  helpers.
- `src/sase/ace/tui/widgets/_snippets.py` already supports `$0`, `$1`, etc. expansion at an explicit range.

Today, accepted xprompt candidates insert `selected.insertion` directly, e.g. `#foo`, then
`_maybe_show_accepted_xprompt_arg_hint()` displays a hint that lets the user type `:` or `(`. This means Ctrl+T
completion does not match the LSP snippet behavior and no-input/optional-only xprompts do not get the trailing space.

## Design

1. Add a pure helper near the existing xprompt argument helpers, likely
   `xprompt_completion_skeleton(entry: XPromptAssistEntry) -> str`.
   - It should compute required inputs with the existing `required_inputs(entry)` helper.
   - It should mirror the Rust LSP helper exactly for visible user-facing inputs.
   - It should leave existing `named_args_skeleton()` and `colon_args_skeleton()` intact because they support the
     interactive post-accept hint actions.

2. Add a small xprompt-specific acceptance path in `FileCompletionMixin`.
   - Keep `CompletionCandidate.insertion` as the canonical reference (`#foo`, `#!foo`, `/skill`) so display, sorting,
     shared-prefix behavior, and selection preservation stay stable.
   - When accepting an xprompt completion whose metadata is an `XPromptAssistEntry` and whose insertion starts with `#`,
     expand `xprompt_completion_skeleton(entry)` over the current token range using
     `_expand_snippet_template_at_range()`.
   - After expansion, clear or refresh xprompt argument hints based on the resulting cursor position:
     - no-required and optional-only skeletons should end with a space and no active hint;
     - `#foo:`, `#foo::`, and `#foo()` should be eligible for the existing typed-argument hint refresh.
   - For slash-skill completions and fallback/non-metadata candidates, keep the existing canonical replacement behavior.

3. Route every xprompt acceptance entry point through that helper.
   - Single-candidate Ctrl+T acceptance.
   - Completion-panel acceptance via Enter/Ctrl+L.
   - Shared-prefix refinement should remain unchanged until a final candidate is accepted.

4. Preserve existing behavior outside xprompt completion.
   - File/path completion, file history completion, directive completion, xprompt argument value completion,
     snippet-registry Tab expansion, and manual `#foo` typing should not change.
   - The `#@` xprompt browser/snippet insertion path can continue inserting the selected reference and showing the
     current argument hint; this request is about completion expansion in the prompt input widget.

## Tests

Add focused tests under `tests/ace/tui/widgets/`.

1. Pure skeleton coverage:
   - no inputs -> `#none `
   - optional-only -> `#optional `
   - one required path/word/etc. -> `#path:`
   - one required text -> `#text::`
   - multiple required inputs -> `#many($0)`
   - `#!` entries use their `entry.insertion` prefix.

2. PromptTextArea acceptance coverage:
   - single-candidate Ctrl+T accepts each skeleton shape and leaves the cursor in the expected place.
   - multiple-required expansion stores no stray literal `$0` and places the cursor inside `#many()`.
   - slash-skill single-candidate completion still inserts `/sase_plan` with no active xprompt argument hint.

3. Panel acceptance coverage:
   - accepting a highlighted xprompt candidate from an open completion panel uses the same skeleton helper as
     single-candidate Ctrl+T.

## Verification

After implementation:

```bash
just install
pytest tests/ace/tui/widgets/test_xprompt_arg_assist.py tests/ace/tui/widgets/test_xprompt_completion.py tests/ace/tui/widgets/test_prompt_snippet_expansion.py
just check
git diff --check
```

If `just check` exposes unrelated pre-existing failures, capture the failing command and the relevant error summary
before reporting back.

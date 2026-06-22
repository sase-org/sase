---
create_time: 2026-06-22 07:38:05
status: done
prompt: sdd/prompts/202606/xprompt_double_colon_space.md
---
# Plan: Append Space After End-of-Line Xprompt Double-Colon Skeletons

## Problem

When an xprompt has exactly one required input and that input is type `text`, the smart completion skeleton currently
inserts `::` immediately after the xprompt reference. That leaves prompts like `#ask::` when accepted at the end of a
line.

The xprompt shorthand parsers in both Python and Rust intentionally recognize free-form double-colon text as `:: `
followed by text. Bare `::` at line end is only a starting point; the next likely user action is to type the free-form
text after a separating space. The product behavior should therefore insert `#ask:: ` when the auto-inserted `::` lands
at end-of-line.

The important constraint is conditionality: if completion happens before existing line content, the existing following
space may already be the delimiter. For example, completing `#a` in `#a existing text` should continue to produce
`#ask:: existing text`, not `#ask::  existing text`.

## Scope

Implement the behavior in both places that auto-generate required-text xprompt completion skeletons:

- `sase` ACE/Textual prompt completions:
  - `src/sase/ace/tui/widgets/xprompt_arg_assist.py`
  - accept paths in `_file_completion_accept.py`, `_prompt_soft_completion.py`, and `_prompt_input_bar_actions.py`
- `sase-core` xprompt LSP snippet completions:
  - `crates/sase_xprompt_lsp/src/server.rs`

Do not change xprompt parsing semantics. The grammar should keep treating `:: ` as the double-colon text shorthand. This
is an insertion ergonomics change, not a parser loosening.

No `sase-nvim` code change should be needed: native Neovim behavior receives this through the LSP snippet completion
item once `sase-core` is updated.

## Design

Add a small context flag to the skeleton builders, rather than changing the context-free skeleton unconditionally.

In Python, extend the existing skeleton helper shape along these lines:

- `xprompt_completion_skeleton(entry, *, append_text_arg_space: bool = False)`
- `xprompt_completion_suffix_skeleton(entry, *, append_text_arg_space: bool = False)`

For exactly one required `text` input:

- `append_text_arg_space=False` keeps current output: `#name::`
- `append_text_arg_space=True` returns `#name:: `

All other cases stay unchanged:

- no required inputs: `#name `
- one required non-text input: `#name:`
- multiple required inputs: `#name($0)`
- standalone `#!name` variants preserve their marker

At each ACE accept path, compute the flag from the replacement range before expanding the snippet:

- `Ctrl+T` single-candidate and panel accept: the replacement token range is `(row, start, end)`, so append the space
  only when `end == len(document.get_line(row))`.
- soft completion: use `suggestion.replacement_end` to derive the replacement end location, then append only when that
  location is at the end of its line.
- `#@` selector smart insertion: use the insertion range passed into `_insert_xprompt_smart_snippet`; append only when
  the range end is at end-of-line in the target text area.

Keep this as a cheap synchronous string/line-length check, with no catalog rebuilds or I/O on the Textual event loop.

In Rust LSP, thread the same boolean into `xprompt_snippet_items()` / `xprompt_completion_skeleton()`:

- Compute whether `context.replacement_range.end.character` equals the UTF-16 length of
  `document.line_text(context.replacement_range.end.line)`.
- Pass that into the xprompt snippet item builder.
- Return `format!("{}:: ", entry.insertion)` for one required `text` input only when the flag is true.

This keeps LSP completion before existing text from adding a duplicate delimiter space, while end-of-line snippet
completion inserts the ergonomic `:: ` form.

## Tests

Add focused Python coverage before implementation:

- Update `tests/ace/tui/widgets/test_xprompt_arg_assist.py` so the default context-free helper still returns `#text::`,
  and add an explicit `append_text_arg_space=True` assertion for `#text:: `.
- Update or extend `tests/ace/tui/widgets/test_xprompt_arg_hints.py` for `#@` smart insertion:
  - end-of-line required text insertion yields `#ask:: ` and leaves the cursor after the space.
  - insertion before existing text yields a single delimiter from existing text, not a doubled space.
- Add ACE acceptance coverage for at least one completion path, preferably Ctrl+T single-candidate or panel accept,
  showing `#ask:: ` at line end.
- Add soft completion coverage if the existing test helpers make it cheap; otherwise rely on the shared helper plus one
  soft-accept assertion if practical.
- Preserve negative expectations for path, optional-only, no-input, and multiple-required inputs.

Add Rust LSP coverage in `crates/sase_xprompt_lsp/src/server.rs` tests:

- Update the existing xprompt snippet skeleton test so `#text` at line end yields `#text:: `.
- Add a completion test where there is text after the replacement range, asserting the same required-text item still
  yields `#text::` without the extra space.

## Validation

Run the targeted test sets first:

- In `sase`:
  `.venv/bin/pytest tests/ace/tui/widgets/test_xprompt_arg_assist.py tests/ace/tui/widgets/test_xprompt_arg_hints.py tests/ace/tui/widgets/test_xprompt_completion.py tests/ace/tui/widgets/test_prompt_live_completion.py`
- In `sase-core`: `cargo test -p sase_xprompt_lsp xprompt_snippet`

Then run the repo-appropriate broader checks:

- In `sase`: `just lint` and, time permitting, `just check`
- In `sase-core`: `cargo test -p sase_xprompt_lsp` and any local formatting/lint command advertised by that repo

Manual smoke after implementation:

- In ACE, accept a required-text xprompt at line end via Ctrl+T, soft completion, and `#@`; verify the prompt becomes
  `#name:: ` and typing immediately appends the free-form text.
- In ACE, accept the same completion before existing text; verify there is no doubled space.
- In Neovim/native LSP, accept a required-text xprompt snippet completion at line end and verify the inserted text is
  `#name:: `.

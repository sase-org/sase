---
create_time: 2026-05-05 18:02:02
status: done
prompt: sdd/prompts/202605/xprompt_double_colon_parentheses.md
---
# Plan: Fix xprompt double-colon text containing parentheses

## Context

`#research_swarm` is a built-in Markdown xprompt whose body contains `---` segment separators, so dispatch-time
multi-agent xprompt expansion handles it before normal inline xprompt expansion. The normal xprompt processor already
preprocesses `#name:: text` into a text-block argument and preserves parentheses in that text. The multi-agent path uses
`iter_xprompt_references()` and then parses the captured `XPromptReference` directly.

## Diagnosis

The bug is in the multi-agent argument extraction path:

- `iter_xprompt_references("#research_swarm:: find foo (bar)")` correctly returns one reference with
  `arg_kind=DOUBLE_COLON_SHORTHAND` and `argument_source=":: find foo (bar)"`.
- `extract_top_level_xprompt_reference()` then calls `_parse_xprompt_reference_arguments()`.
- For shorthand references, `_parse_xprompt_reference_arguments()` falls through to `ref.parse_arguments()`.
- `XPromptReference.parse_arguments()` delegates to `parse_workflow_reference(self.reference_body)`.
- `parse_workflow_reference()` checks `if "(" in workflow_ref` before it checks colon shorthand, so a parenthesis inside
  the `::` text is treated as the beginning of parenthesized xprompt arguments. The text before `(` is discarded as part
  of a bogus workflow name and only the text inside the parentheses is passed as the positional argument.

This explains the observed behavior where only the text after or inside the `(` appeared to reach
`src/sase/default_xprompts/research_swarm.md`.

## Implementation Plan

1. Add focused regression coverage in `tests/test_multi_agent_xprompt.py` for multi-agent xprompt calls using
   double-colon shorthand with parentheses in the text, including the `research_swarm` style input shape.
2. Add lower-level parser coverage in `tests/test_xprompt_references.py` for `XPromptReference.parse_arguments()` on
   `DOUBLE_COLON_SHORTHAND` and `COLON_SHORTHAND` references whose text contains parentheses.
3. Fix `XPromptReference.parse_arguments()` so shorthand references parse according to their already-detected `arg_kind`
   instead of re-feeding the entire reference body through the generic workflow reference parser.
   - `#name:: text` should return `["text"]`.
   - `#name: text` should return `["text"]`.
   - Existing paren, simple colon, plus, and no-arg forms should keep the current behavior.
4. Run the targeted xprompt tests first:
   - `just test -- tests/test_xprompt_references.py tests/test_multi_agent_xprompt.py tests/test_xprompt_parsing.py tests/test_xprompt_processor_shorthand.py`
5. Because this repo requires it after file changes, run `just check` before reporting completion.

## Risks

The main risk is changing shared parsing semantics used by workflow validators and dispatch code. Keeping the fix inside
`XPromptReference.parse_arguments()` and only special-casing the explicit shorthand `arg_kind` values avoids disturbing
the older generic `parse_workflow_reference()` behavior for non-shorthand references.

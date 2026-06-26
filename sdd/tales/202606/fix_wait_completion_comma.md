---
create_time: 2026-06-26 11:29:59
status: done
prompt: sdd/prompts/202606/fix_wait_completion_comma.md
---
# Fix Wait-Agent Completion After Prose Commas

## Root Cause

The ACE prompt input's agent-name completion for `%wait` / `%w` is driven by
`extract_directive_arg_token_around_cursor()` in `src/sase/ace/tui/widgets/directive_completion.py`.

For colon-form wait directives, `_extract_wait_colon_arg_token()` finds the last comma between the directive colon and
cursor, then validates only the text after that comma. If a prompt line starts with a valid wait directive and then
continues with normal prose, a later prose comma can be mistaken for a new comma-separated wait argument. In the
screenshot case, a line shaped like:

```text
%w:sase-59 Can you help me get rid of the `,`
```

can make the extractor treat the empty text after the comma as the active wait argument fragment, so the "wait agents"
menu opens even though the cursor is in normal prompt prose.

## Implementation Plan

1. Tighten wait-argument context detection in the pure completion engine.
   - Add a small helper in `directive_completion.py` that validates the entire wait argument prefix between the
     directive marker and the cursor, not only the active fragment after the last comma.
   - Keep valid comma-list flows working, including `%wait:planner, co`, `%wait:planner,`, and
     `%wait(planner, co, time=5m)`.
   - Reject contexts where prose or unquoted whitespace appears before the last comma, such as `%w:sase-59 Can you...,`.

2. Apply the same prefix-validation rule to both supported wait syntaxes.
   - Colon form: `%wait:agent, next`
   - Parenthesized form: `%wait(agent, next, time=5m)`
   - Preserve the existing behavior where `time=...` extracts as a wait argument fragment but produces no agent-name
     candidates because fragments containing `=` are intentionally ignored by agent completion.

3. Add focused regression coverage.
   - Pure extraction tests in `tests/ace/tui/widgets/test_directive_arg_extraction.py` for the screenshot shape and for
     valid comma-separated wait fragments.
   - Interaction-level coverage in `tests/ace/tui/widgets/test_directive_completion_interactions.py` proving that typing
     a comma later in prompt prose after `%w:agent` does not reopen the wait-agent completion panel.

4. Verify with targeted tests first, then the repo check.
   - Run the directive completion tests that cover extraction and prompt-input interaction.
   - Because source/test files will change, run `just install` if needed and then `just check` before finalizing, per
     project instructions.

## Expected Outcome

Commas typed inside normal prompt prose will no longer trigger the agent-name completion menu merely because the same
line contains an earlier `%wait` or `%w` directive. Commas typed while actively editing a `%wait` argument list will
continue to support multi-agent wait completion.

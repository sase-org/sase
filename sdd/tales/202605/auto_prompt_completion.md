---
create_time: 2026-05-07 12:45:41
status: wip
prompt: sdd/prompts/202605/auto_prompt_completion.md
---
# Auto-Start Prompt Completion Plan

## Context

The prompt input widget already supports manual completion through `ctrl+t`. That path is implemented in
`PromptTextArea` and `FileCompletionMixin`, using pure candidate builders for directive, xprompt, xprompt argument, file
path, and file-history completions.

The requested behavior is narrower than changing the completion model:

- When the user types `%` in a valid directive position, start directive completion automatically.
- When the user types an xprompt reference, do not start completion on the bare `#`; wait until the first xprompt name
  character is present.
- Keep the performance impact minimal, especially because xprompt candidates can require catalog/assist-entry work.

## Approach

1. Add a lightweight auto-trigger hook in insert-mode key handling after Textual has inserted the typed character.
   - This keeps cursor and document state consistent with the existing completion code.
   - The hook will run only for `%` and identifier characters, so normal typing pays only a small character check.

2. Add a non-mutating completion opener for automatic triggers.
   - Reuse the existing directive/xprompt token extraction and candidate builders.
   - Set `_completion_kind`, `_file_completion_active`, candidates, and selected index, then render the existing panel.
   - Do not apply shared-prefix expansion and do not accept a single candidate. Automatic completion should open
     suggestions, not rewrite more text than the user typed.

3. Directive trigger rules:
   - On a typed `%`, use the existing directive-token extractor, including its context checks.
   - This avoids triggering in text such as `50%` or `word%`.

4. Xprompt trigger rules:
   - On a typed identifier character, inspect the current xprompt-like token.
   - Trigger only when the partial name has length one.
   - Support both `#x` and standalone-marker `#!x` while still avoiding any work on bare `#` or `#!`.

5. Preserve existing manual behavior.
   - `ctrl+t` should continue to do shared-prefix expansion, single-candidate insertion, file completion, file-history
     completion, and xprompt argument completion exactly as it does today.
   - Active completion refresh should continue to update candidates as the user types more characters.

6. Add focused tests.
   - Directive: typing `%` at the start opens the directive panel automatically.
   - Directive: typing `%` after a digit does not open completion.
   - Xprompt: typing `#` alone does not build/open xprompt completion.
   - Xprompt: typing the first letter after `#` opens the xprompt panel.
   - Xprompt: if that first-letter filter has a single candidate, automatic completion leaves the typed token intact and
     shows the candidate instead of accepting it.

## Verification

Run focused widget tests first:

```bash
just install
pytest tests/ace/tui/widgets/test_directive_completion.py tests/ace/tui/widgets/test_xprompt_completion.py
```

Because this repo requires it after code changes, finish with:

```bash
just check
```

---
create_time: 2026-05-07 11:01:05
status: done
prompt: sdd/prompts/202605/directive_completion.md
---
# Plan: Prompt Directive Completion

## Goal

Add `%` directive completion to the prompt input widget's existing `<ctrl+t>` completion flow. The behavior should feel
like current xprompt and file completion:

- Typing `%` then `<ctrl+t>` shows known SASE prompt directives.
- Typing a partial directive such as `%mo` then `<ctrl+t>` completes to `%model`.
- Shared-prefix completion, multi-candidate panels, navigation, and `ctrl+l` acceptance continue to work through the
  existing completion UI.
- Existing file, file-history, xprompt, slash-skill, and xprompt-argument completion behavior does not regress.

## Current State

`PromptTextArea` binds `ctrl+t` directly in insert mode and delegates to
`FileCompletionMixin._try_file_completion_tab()`.

That path currently checks, in order:

1. xprompt argument completion context
2. token around the cursor
3. xprompt-like tokens (`#...`, `#!...`, `/skill`)
4. path-like tokens
5. file-reference history when there is no token

The completion UI is generic and already works with `CompletionCandidate`; only the detection/building/rendering
branches need to learn a new directive kind.

The existing token extractor treats `%` as a delimiter, so `%mo` currently extracts `mo`, not `%mo`. Directive support
should use a directive-specific token extractor rather than weakening generic path-token delimiter behavior.

Directive parsing lives in `sase.xprompt._directive_types`:

- `_KNOWN_DIRECTIVES`: `approve`, `edit`, `epic`, `hide`, `model`, `name`, `plan`, `repeat`, `tag`, `wait`
- `_DIRECTIVE_ALIASES`: `a`, `e`, `h`, `m`, `n`, `r`, `p`, `t`, `w`

Fan-out alternatives are handled separately in `sase.xprompt._directive_alt`, so completion should also include the
user-facing `%alt` directive even though it is not in `_KNOWN_DIRECTIVES`. The internal `%xprompts_enabled` markers
should not be completed.

## Design

Add a small pure-logic directive completion module beside the existing completion engines:

- New module: `src/sase/ace/tui/widgets/directive_completion.py`
- Export:
  - `is_directive_like_token(token: str) -> bool`
  - `extract_directive_token_around_cursor(line: str, col: int) -> tuple[int, int, str] | None`
  - `build_directive_completion_candidates(token: str) -> tuple[list[CompletionCandidate], str]`

Candidate construction:

- Build canonical insertion candidates for known user-facing directives: `_KNOWN_DIRECTIVES | {"alt"}`.
- Match either canonical names or aliases, so `%m` finds `%model`, `%r` finds `%repeat`, and `%w` finds `%wait`.
- Insert canonical directive names (`%model`, `%repeat`, `%wait`) rather than aliases. Aliases remain valid when typed
  manually, but completion should favor discoverable canonical names.
- Carry metadata with aliases and a short argument style hint so the panel can display useful context without
  hard-coding row text in the mixin.
- Compute shared extensions from candidate insertion text after the leading `%`, matching xprompt completion behavior.

Token extraction:

- Recognize `%` at start of line, after whitespace, or after one of the same opening punctuation contexts the directive
  parser accepts.
- Recognize a cursor after `%` as the empty directive token `%`, so `<ctrl+t>` can list all directives.
- Continue through directive identifier characters only (`[A-Za-z0-9_]`) and stop before `:`, `(`, `+`, whitespace, and
  punctuation.
- Do not treat normal text such as `50%` as directive-like.

Wire the new kind into `FileCompletionMixin`:

- Add `_get_directive_token_context()`.
- Teach `_get_token_context()` and `_refresh_file_completion_from_cursor()` about `completion_kind == "directive"`.
- In `_try_file_completion_tab()`, check the directive-specific extractor before the generic token extractor, so `%` and
  `%mo` work despite `%` being a generic delimiter.
- Keep the existing acceptance path, shared-prefix path, and active-completion navigation unchanged.

Render the panel in `PromptInputBar.show_file_completions()`:

- Treat `completion_kind == "directive"` as a first-class kind.
- Use a distinct title such as `directives`.
- Render directive rows with the directive token plus dim metadata, similar to xprompt rows.

No default keymap config change is expected because `<ctrl+t>` is already hard-bound in `PromptTextArea`; this change
expands what that existing keymap completes.

## Tests

Add focused pure-logic tests for the new directive completion module:

- `%` lists canonical directive names, including `%alt`.
- `%mo` returns only `%model`.
- Alias partials match canonical names: `%m -> %model`, `%r -> %repeat`, `%w -> %wait`.
- `50%` and non-directive `%` positions do not produce directive tokens.
- Shared-prefix behavior works for partials with multiple matches.

Add prompt-widget integration tests under `tests/ace/tui/widgets/`:

- Pressing `<ctrl+t>` at `%` opens an active completion panel titled `directives`.
- Pressing `<ctrl+t>` at `%mo` inserts `%model` when it is the only candidate.
- Pressing `<ctrl+t>` at `%m` inserts `%model` via alias matching.
- Multi-candidate directive completion supports navigation and `ctrl+l` acceptance through the existing completion
  machinery.
- Existing file/xprompt completion tests remain unchanged.

Verification:

1. Run the targeted widget/directive tests first.
2. Run `just install` if this workspace has not been prepared.
3. Run `just check` before final handoff because this repo requires it after code changes.

## Implementation Order

1. Add the pure directive completion module and tests.
2. Wire directive completion into `FileCompletionMixin`.
3. Add directive row rendering in `PromptInputBar`.
4. Add integration tests for the prompt widget.
5. Run targeted tests, then `just check`.

## Risks

- The parser’s directive registry is split between `_directive_types` and `_directive_alt`; completion must explicitly
  include `%alt` or it will omit a real directive.
- Generic token extraction must not be loosened for `%`, or path/file completion behavior around punctuation could
  change.
- `%` is also used by TUI copy-mode at the app level, but this work is scoped to `PromptTextArea` while the prompt bar
  is focused, so app-level copy keymaps should not be affected.

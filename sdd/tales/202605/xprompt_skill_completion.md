---
create_time: 2026-05-07 01:13:36
status: done
prompt: sdd/prompts/202605/xprompt_skill_completion.md
---
# Add Prompt Input Ctrl+T Completion for XPrompt Skills

## Context

The ace prompt input bar already uses `<ctrl+t>` as a shared completion trigger. In insert mode,
`PromptTextArea._on_key()` delegates to `FileCompletionMixin._try_file_completion_tab()`, which currently chooses among:

- xprompt reference completion for tokens beginning with `#` / `#!`
- path completion for path-like tokens
- xprompt argument completion inside `#xprompt(...)` or `#xprompt:...`
- recent file history when there is no token at the cursor

XPrompt catalog data already identifies xprompts that are exposed as runtime skills via
`StructuredCatalogEntry.is_skill`, but the TUI-side `XPromptAssistEntry` projection drops that field. The completion
engine therefore has no way to filter only skills, and `is_xprompt_like_token()` only recognizes `#` references.
Generated skill source files such as `src/sase/xprompts/skills/sase_plan.md` are normal xprompt catalog entries with
`skill: true`, and runtime users invoke them with a slash form such as `/sase_plan`.

## Goal

Make `<ctrl+t>` in the prompt input widget complete slash-prefixed xprompt skills:

- Typing `/sas` then `<ctrl+t>` should offer skill candidates like `/sase_plan`.
- Accepting a skill candidate should insert `/sase_plan`, not `#sase_plan`.
- Only entries marked as skills should appear for slash completion.
- Existing `#` / `#!` xprompt completion, file completion, xprompt argument completion, and recent-file completion
  should keep their current behavior.

## Non-Goals

- Do not change xprompt expansion syntax or make slash skills expand through the sase xprompt processor.
- Do not change generated skill content or the `sase init-skills` deployment pipeline.
- Do not add runtime-specific skill behavior; all runtimes should be treated uniformly.
- Do not broaden slash completion into arbitrary command/path completion.

## Design

1. Preserve the catalog as the source of truth.
   - Extend `XPromptAssistEntry` with an `is_skill: bool` field populated from `StructuredCatalogEntry.is_skill`.
   - Keep existing fields and callers intact, with a default value if needed for test fixtures.

2. Generalize xprompt completion token recognition to include slash skill tokens.
   - Add a narrow token predicate for `/`-started skill references, or extend the existing predicate with explicit slash
     handling.
   - Avoid stealing path completion for `/absolute/path` tokens. A slash token should be treated as skill completion
     only when it looks like a bare skill name prefix, e.g. `/`, `/s`, `/sase_plan`, with no additional slash after the
     leading marker.
   - Because xprompt skill names currently use identifier-like names such as `sase_plan`, allow letters, digits, and
     underscores after the leading slash. Keep this intentionally conservative.

3. Build slash-skill candidates from the same assist entries.
   - Add a helper path in `build_xprompt_completion_candidates()` for slash tokens.
   - Filter to `entry.is_skill`.
   - Match against `entry.name`, not the normal `entry.insertion`.
   - Display and insert `/{entry.name}`.
   - Carry the same `XPromptAssistEntry` in candidate metadata so the completion panel can render
     descriptions/kind/input hints consistently if applicable.

4. Keep the existing completion state machine unchanged where possible.
   - Continue using `_completion_kind == "xprompt"` for slash skill candidates unless a small clearer enum value is
     needed.
   - If slash candidates use the xprompt completion row renderer, show them in the same panel and title. A label such as
     `skill` can be displayed when the metadata says `is_skill`.
   - Do not show xprompt argument hints after accepting slash skills, because `/skill` is runtime skill syntax, not a
     `#xprompt` reference that accepts xprompt arguments in the prompt processor.

5. Update prompt input copy only if it stays concise.
   - The existing placeholder says `[^T] path complete`; this is now incomplete because `<ctrl+t>` already completes
     more than paths. Change it to a compact phrase such as `[^T] complete`.

## Tests

Add focused tests under the existing prompt completion suites:

- Unit tests for slash skill token recognition:
  - `/` and `/sase_plan` are recognized as skill-completion tokens.
  - `/tmp/foo` remains path-like/file completion, not xprompt-skill completion.
  - `foo` remains non-xprompt.

- Unit tests for candidate building:
  - Slash completion returns only `is_skill=True` entries.
  - Candidate display and insertion are slash-prefixed.
  - Non-skill xprompts with matching names are excluded.
  - Shared-prefix behavior still works for multiple matching skills.

- TUI-level completion tests:
  - Typing `/sase_p` and pressing `<ctrl+t>` with one matching skill inserts `/sase_plan`.
  - Typing `/s` with multiple skills opens the completion panel.
  - Accepting a slash skill does not activate xprompt argument hint state.
  - Existing `#` / `#!` completion tests continue to pass.

## Verification

Run the focused tests first:

```bash
pytest tests/ace/tui/widgets/test_xprompt_completion.py tests/ace/tui/widgets/test_prompt_file_completion.py tests/ace/tui/widgets/test_prompt_file_history_completion.py tests/ace/tui/widgets/test_xprompt_arg_value_completion.py
```

Because this workspace may have stale dependencies, run:

```bash
just install
just check
```

## Risks and Mitigations

- Risk: slash-prefixed absolute paths could accidentally open skill completion.
  - Mitigation: only treat slash tokens with no second slash and identifier-safe characters as skill tokens; path-like
    tokens keep the existing file completion path.

- Risk: accepting `/skill` could incorrectly trigger xprompt argument hints.
  - Mitigation: only run post-accept xprompt argument hint logic for `#`/`#!` xprompt references, not slash skill
    completions.

- Risk: catalog fixture updates could be broad because `XPromptAssistEntry` gains a field.
  - Mitigation: give the dataclass field a default or update the small local `_entry()` test helper so existing fixtures
    remain easy to read.

## Implementation Steps

1. Add `is_skill` to `XPromptAssistEntry` and populate it from the structured xprompt catalog.
2. Update the xprompt completion engine to recognize bare slash skill tokens and build slash-prefixed candidates
   filtered to skill entries.
3. Adjust the prompt completion accept path so slash skill completions insert normally without xprompt argument hints.
4. Make the prompt placeholder text generic enough for the broader `<ctrl+t>` behavior.
5. Add and run the focused tests, then run `just install` and `just check`.

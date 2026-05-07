---
create_time: 2026-05-07 11:15:14
status: done
prompt: sdd/prompts/202605/slash_skill_completion.md
---
# Plan: restore slash-skill completion in the prompt widget

## Problem

Slash-skill completion was added at the prompt-widget layer, but it does not work with the real catalog. Pure and widget
tests currently pass because they mock `XPromptAssistEntry` values with `is_skill=True`, while the runtime catalog
reports zero skills.

The diagnosed root cause is that the shipped skill xprompts live in `src/sase/xprompts/skills/*.md`, but
`sase.xprompt.loader._load_xprompts_from_internal()` only scans direct `*.md` children of `src/sase/xprompts/`. As a
result:

- `build_xprompt_completion_candidates("/")` returns no candidates.
- `build_xprompt_assist_entries()` contains no `is_skill=True` entries.
- The prompt widget has no real slash-skill candidates to show or insert.

## Implementation Approach

1. Update internal package xprompt discovery so it includes markdown files in the built-in `skills/` subdirectory while
   preserving existing top-level built-in xprompt names and priority behavior.
2. Keep user/project/home xprompt search semantics unchanged unless tests reveal this should be generalized; this bug is
   specifically about packaged SASE skills.
3. Add regression coverage at the loader/catalog layer proving that built-in skill files are loaded and marked as
   skills.
4. Add or strengthen prompt completion coverage that uses the real catalog rather than only mocked entries, proving
   `/sase_` offers built-in skill completions through `build_xprompt_completion_candidates()`.
5. Run focused tests for xprompt loading/catalog/completion, then run `just check` because this repo requires it after
   code changes.

## Expected Outcome

Typing `/sase_` in the prompt input widget and pressing Ctrl+T should show real SASE skill candidates such as
`/sase_plan` and `/sase_questions`, and accepting a single slash-skill candidate should insert the slash reference
without showing xprompt argument hints.

## Risks and Constraints

- Recursive internal discovery must not accidentally load non-xprompt support markdown if such files are added under
  `src/sase/xprompts/` later. The current built-in subtree only contains intended skill markdown, so recursive `*.md`
  loading is acceptable if kept scoped to the package xprompt directory.
- Preserve override priority: config/user/project/file xprompts should still override internal built-ins by name.
- Avoid changing workflow YAML discovery unless needed; this fix is limited to markdown xprompt skills.

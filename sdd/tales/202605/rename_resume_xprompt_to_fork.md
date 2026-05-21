---
create_time: 2026-05-21 13:37:40
status: done
prompt: sdd/prompts/202605/rename_resume_xprompt_to_fork.md
---
# Plan: Rename the `#resume` XPrompt Workflow to `#fork`

## Goal

Make `#fork` the current user-facing xprompt workflow for continuing from an existing agent/chat, replacing generated,
documented, and tested uses of `#resume`.

## Scope Boundaries

- Rename the built-in workflow file `src/sase/xprompts/resume.yml` to `fork.yml`.
- Rename the direct chat-path helper workflow `src/sase/xprompts/resume_by_chat.yml` to `fork_by_chat.yml`, since it is
  part of the same user-facing workflow family.
- Update current source, package xprompts, project xprompts, docs, skills, and tests that refer to the old xprompt
  names.
- Keep non-xprompt uses of the English verb "resume" unchanged where they are separate product surfaces:
  `sase run --resume`, `sase commit --resume`, chat display format `-f resume`, TUI action labels like `r resume`,
  mobile operation names like `resume-options`, and commit-conflict recovery.
- Do not edit memory files without explicit approval.

## Compatibility Strategy

Historical chat transcripts and persisted agent metadata can contain old `#resume` / `#resume_by_chat` references. The
new public surface should generate `#fork`, but low-level parsers that recursively expand old chat content or rewrite
old persisted agent names should continue to understand legacy `#resume` references. That keeps existing history and
revival flows from breaking while preventing new prompts from advertising the old workflow.

## Implementation Steps

1. Rename built-in workflow files and update their inline references:
   - `src/sase/xprompts/resume.yml` -> `src/sase/xprompts/fork.yml`
   - `src/sase/xprompts/resume_by_chat.yml` -> `src/sase/xprompts/fork_by_chat.yml`
   - Keep the same behavior: resolve the target chat, load prior history, inject it under `%xprompts_enabled:false`,
     then reopen xprompt expansion for the new query.

2. Update generators and UI prompt construction:
   - TUI wait/resume actions should prefill `#fork:<name>`.
   - Mobile resume prompt payloads should emit `#fork:<name>`.
   - Retry/follow-up/coder handoff prompt construction should use `#fork`.
   - Default/project xprompts such as `research_swarm.md` and `xprompts/refresh_docs.yml` should use `#fork`.
   - Multi-prompt bare-reference rewriting should treat bare `#fork` as the current form.

3. Update parser helpers for the new name while preserving legacy reads:
   - Recursive chat expansion should recognize `#fork` and `#fork_by_chat` as the canonical forms, plus legacy `#resume`
     and `#resume_by_chat` for old transcripts.
   - Agent-name derivation should use the current `#fork` trigger for new prompts, and still accept legacy `#resume`
     when scanning old prompts.
   - Agent name migration should rewrite both `#fork` and legacy `#resume` references when renaming persisted agents.

4. Update documentation and skills:
   - Replace user-facing `#resume` workflow documentation with `#fork`.
   - Update the chats skill to recommend `#fork:<name>` / `#fork_by_chat:<basename>`.
   - Leave unrelated `--resume`, `/resume`, "resume action", and conflict-resume documentation intact.

5. Update tests and fixtures:
   - Rename `tests/test_resume_workflow.py` to a fork-oriented test name and update expected workflow names.
   - Update tests asserting generated prompt text from TUI/mobile/multi-prompt/directive/follow-up flows.
   - Add or retain focused legacy-compatibility assertions for old `#resume` references in recursive chat expansion and
     name parsing.

6. Verify:
   - Run focused tests for workflow loading, chat expansion, agent naming, TUI prompt construction, mobile payloads, and
     multi-prompt rewriting.
   - Run `just install` if needed, then `just check` before final response, per repo instructions.
   - Run targeted `rg` checks so remaining `#resume` occurrences are either legacy-compatibility coverage/comments or
     unrelated historical material, not current generated/documented xprompt usage.

---
create_time: 2026-05-23 13:44:21
status: done
prompt: sdd/prompts/202605/fast_init.md
---
# Make `sase init` Faster Without Behavior Changes

## Context

Bare `sase init` is slow even when everything is already initialized. In this workspace, `sase init --check` with the
current home config takes about 7.8s and exits cleanly. Breaking the path down shows that `memory` and `sdd` planning
are already cheap, while `skills` planning takes about 7.2s.

The expensive part is not xprompt discovery or provider lookup. Rendering raw skill files takes about 0.05s. The delay
comes from formatting generated skill Markdown: the current skills planner calls `prettier` once for every generated
skill target. With the current config that is 62 Prettier subprocesses. The raw generated contents collapse to 23 unique
Markdown bodies, and a prototype batch Prettier run over those unique bodies matched the existing per-body formatter
output while taking about 0.38s instead of about 3.1s for the unique-body path, and much less than the current 62-call
path.

## Goal

Make bare `sase init` and `sase init --check` substantially faster while preserving:

- the same planned actions and summaries,
- the same generated `SKILL.md` bytes when Prettier is available,
- the same warning behavior when Prettier is unavailable,
- the same fallback behavior if formatting fails,
- the same target paths, provider filtering, chezmoi behavior, and apply semantics.

## Implementation Plan

1. Add a small batch formatting layer to `src/sase/main/init_skills_handler.py`.

   It will accept a sequence of raw generated skill Markdown strings, deduplicate them in stable order, write the unique
   strings to temporary `.md` files, run one `prettier --write --prose-wrap=always --print-width=120 --parser=markdown`
   command over those files, read the formatted files back, and apply the same underscore unescaping used by
   `format_with_prettier`.

2. Preserve existing fallback semantics.

   If Prettier is unavailable, return raw strings unchanged as today. If the batch Prettier command fails or cannot be
   started, fall back to the existing single-string `format_with_prettier` path per unique raw string, so unusual
   formatter failures keep the current behavior.

3. Change skill target rendering to format once per unique rendered body.

   `_render_skill_targets` should continue to select xprompts, providers, contexts, and target paths exactly as it does
   now. The only structural change is to render raw output first, ask the batch formatter for formatted content, then
   attach the formatted content to every target that uses the same raw body.

4. Update focused tests for the new behavior.

   Add or adjust tests under `tests/main/test_init_skills_plan.py` to cover:
   - plan/apply bytes still match when Prettier is available,
   - duplicate raw outputs are formatted once and reused across multiple targets,
   - batch formatter failure falls back to the existing single-output formatter,
   - missing Prettier still reports the existing warning path.

5. Verify performance and correctness.

   Run targeted tests for init onboarding and skills planning first, then run `just check` because source files changed.
   Re-measure `sase init --check` with both the current home config and an isolated temporary home to confirm the change
   materially reduces the observed latency without changing command output.

## Risks

The main risk is a subtle difference between formatting via Prettier stdin and formatting temporary Markdown files. The
prototype batch command matched the existing formatter output for the current generated skill bodies, and the fallback
keeps the old formatter available if the batch path fails. Tests should pin this equivalence for representative
generated skills.

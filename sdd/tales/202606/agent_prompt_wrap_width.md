---
create_time: 2026-06-25 15:01:58
status: done
prompt: sdd/prompts/202606/agent_prompt_wrap_width.md
---
# Plan: Agent prompt wrap width 80

## Context

Agent prompts are currently wrapped through `src/sase/llm_provider/preprocessing.py::preprocess_prompt_late()`, which
calls `sase.file_references.format_with_prettier()`. That helper invokes Prettier with
`--prose-wrap=always --print-width=120`, so the active launch-time prompt width is 120 today.

The nearby 100-column uses I found are Rich console/test display widths and prompt previews, not the prompt Markdown
formatter. Generated skills also have a separate 120-column Prettier path and a 118-column YAML-description wrap, but
that is a generated-skill artifact surface rather than the normal agent prompt pipeline.

## Goal

Use an 80-column wrap width for long Markdown prose in agent prompts sent through the normal preprocessing pipeline,
without changing the repo-wide Markdown artifact formatting behavior for plans, SDD files, generated skills, or other
saved Markdown documents.

## Design

1. Parameterize the shared Markdown formatter.
   - Add named constants in `src/sase/file_references.py`, likely `DEFAULT_MARKDOWN_WRAP_WIDTH = 120` and
     `AGENT_PROMPT_WRAP_WIDTH = 80`.
   - Change `format_with_prettier(text)` to accept an optional keyword-only `print_width` defaulting to
     `DEFAULT_MARKDOWN_WRAP_WIDTH`.
   - Keep the existing one-argument call shape valid so non-prompt callers continue to get 120-column output by default.
   - Update the docstring so it no longer claims the helper always uses 120.

2. Route launch-time prompt preprocessing through width 80.
   - In `preprocess_prompt_late()`, call `format_with_prettier(prompt, print_width=AGENT_PROMPT_WRAP_WIDTH)`.
   - This covers direct `invoke_agent()` calls because `preprocess_prompt()` delegates to `preprocess_prompt_late()`.
   - This also covers workflow prompt steps because `workflow_executor_steps_prompt.py` preprocesses expanded step
     prompts via `preprocess_prompt_late()`.
   - `sase xprompt expand` will also show the same processed prompt shape, which is useful because it is a
     prompt-expansion/debugging command.

3. Preserve non-prompt Markdown formatting at 120.
   - Leave existing callers in `plan_propose_handler.py`, `plan_approval_actions.py`, `sdd/_write.py`,
     `commit/precommit_hooks.py`, notification Markdown formatting, and `init_skills_handler.py` on the default
     120-column behavior.
   - Do not edit generated `SKILL.md` outputs directly. The generated-skills memory confirms those files are generated
     from `src/sase/xprompts/skills/`.
   - Do not change `Justfile` Markdown formatting width in this task; that is a repo formatting policy, not the runtime
     agent prompt width.

4. Keep protected prompt regions protected.
   - Fenced code blocks and `%xprompts_enabled:false/true` disabled regions are already protected before Prettier runs.
     The width change should preserve that order and not wrap code fences, copied diffs, previous-chat disabled regions,
     or other protected content.
   - Workflow output-format instructions are currently appended after late preprocessing. They are short structured
     instructions plus a JSON code fence, so I would not reflow them in this change unless a failing test or real
     example shows they are the source of the long prose lines.

## Tests

1. Add focused tests for `format_with_prettier()`.
   - Monkeypatch `shutil.which()` so the helper takes the Prettier path.
   - Monkeypatch `subprocess.run()` and assert the default call includes `--print-width=120`.
   - Assert an override call includes `--print-width=80`.
   - Keep the fallback behavior unchanged when Prettier is missing or fails.

2. Add or update preprocessing tests.
   - Add a focused test that patches `sase.file_references.format_with_prettier` and asserts `preprocess_prompt_late()`
     passes `print_width=80`.
   - Update existing preprocessing mocks that currently use single-argument lambdas so they accept `**kwargs`; their
     behavioral assertions should remain the same.

3. Run focused verification.
   - `uv run pytest tests/test_preprocessing_code_blocks.py tests/test_disabled_regions.py`
   - The new formatter test module.
   - Any changed plan/skill tests if the formatter signature affects their mocks, especially
     `tests/main/test_init_skills_plan.py` and `tests/test_plan_command_handler.py`.

## Rollout notes

This should be a small behavior change with a visible effect on prompt text saved to agent artifacts and sent to
providers. It should not change stored SDD plans, repo Markdown formatting, generated skills, or command output
formatting unless those paths explicitly opt into the new 80-column prompt width later.

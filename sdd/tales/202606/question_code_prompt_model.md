---
create_time: 2026-06-15 17:37:43
status: done
prompt: sdd/prompts/202606/question_code_prompt_model.md
---
# Fix Question Continuations for Code-Agent Prompts

## Problem

When an agent is interrupted by `/sase_questions`, the runner handles the answer inside the same execution loop and
constructs a follow-up prompt for the next agent phase. Today that question follow-up is rebuilt from
`LoopState.original_prompt`, which is the initial planner prompt. That is correct for questions asked by the original
planner, but wrong when the interrupted agent is the code/coder phase after a plan approval.

For a code agent, the base prompt should be the exact code-agent prompt that was already constructed for the approved
plan, before adding the merged Questions and Answers section. That prompt includes the approved plan reference,
"implement it now" instruction, optional custom coder instructions, any VCS/embedded workflow refs, and the resolved
model directive. Replacing it with the original planner prompt causes the answered-question continuation to relaunch as
if it were the planner, not the coder.

The same bug can also make metadata drift. Accepted-plan handoff resolves the worker lane from `worker_models` and
writes the code follow-up metadata to match the concrete model/provider. Question follow-up currently creates its next
artifact from `ctx.agent_meta`, which is the initial runner metadata, so a question continuation from the code phase can
inherit planner metadata instead of the interrupted code phase's worker model.

## Current Flow

- `run_execution_loop()` initializes `LoopState.original_prompt` to the initial prompt and repeatedly executes
  `state.current_prompt`.
- `handle_plan_marker()` keeps `original_prompt` available for feedback replanning, then `handle_accepted_plan()`
  constructs the approved code-agent prompt in `state.current_prompt`.
- `handle_accepted_plan()` resolves the worker lane with `resolve_worker_provider_model_for_primary()` and writes
  follow-up `agent_meta.json` model/provider for the code/epic/legend artifact.
- `handle_questions_marker()` appends the answered Q&A by setting
  `state.current_prompt = state.original_prompt + merged_qa_text`.
- That final step discards the code-agent prompt and its model directive when the question came from the code phase.

## Plan

1. Add an explicit prompt base for question continuations to `LoopState`.
   - Initialize it to the initial prompt at loop start.
   - Treat it as "the prompt for the currently executing phase before merged Q&A is appended."
   - Keep `original_prompt` unchanged for plan feedback, because feedback still needs the user's original request plus
     accumulated requirements.

2. Update phase transitions to refresh that question base.
   - In `handle_accepted_plan()`, after constructing the code/epic/legend follow-up prompt, store that exact prompt as
     the question base.
   - In plan-feedback handling, after constructing the replanner prompt with accumulated feedback, store that prompt as
     the question base.
   - Do not overwrite the base when a question follow-up is created; repeated question rounds should rebuild from the
     same phase base plus the newly merged Q&A block.

3. Make question prompt rebuilds use the current phase base, not the initial planner prompt.
   - Before adding the new Q&A round, derive the base from the stored question base.
   - Preserve existing deduplication semantics: multiple question rounds should still render as one merged Q&A section
     with continuous numbering.
   - Keep the existing SDD prompt Q&A update behavior.

4. Preserve the interrupted phase's model metadata for question follow-ups.
   - When creating question follow-up artifacts, use the interrupted phase's current `agent_meta.json` as the base
     metadata when available, falling back to `ctx.agent_meta` only if the file cannot be read.
   - This lets code-question continuations inherit the same concrete worker-model provider/model that
     `handle_accepted_plan()` already wrote.
   - The prompt itself will also retain the same concrete `%model:<provider>/<model>` directive from the code-agent
     base, so runtime launch behavior and artifact metadata agree.

5. Add regression coverage.
   - Add a test that approves a plan with a configured `worker_models` resolution, then simulates `/sase_questions` from
     the code phase and verifies the follow-up prompt is still the code prompt plus Q&A, not the original planner
     prompt.
   - Verify the follow-up prompt retains the concrete worker `%model` prefix used for the code agent.
   - Verify repeated question rounds still produce exactly one merged Q&A section.
   - Add or extend metadata assertions so a question continuation from a worker-model code phase creates follow-up
     metadata with the code phase's model/provider.

6. Validate with focused tests first, then repo checks.
   - Run the focused plan/question follow-up tests that cover prompt construction and metadata.
   - Because code files will change, run `just install` if needed and then `just check` before reporting completion.

## Risks and Guardrails

- Do not change the meaning of `original_prompt`; it remains the immutable planner/user prompt for feedback flows and
  SDD spec generation.
- Do not introduce runtime-specific behavior. Model preservation should flow through existing prompt directives and
  metadata, uniformly across providers.
- Avoid parsing or rewriting the Q&A markdown to find a base prompt. Keeping an explicit per-phase base is less brittle
  and matches the runner's state-machine structure.

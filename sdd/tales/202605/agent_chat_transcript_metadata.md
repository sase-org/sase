---
create_time: 2026-05-23 12:03:02
status: done
prompt: sdd/prompts/202605/agent_chat_transcript_metadata.md
---
# Plan: Agent Chat Transcript Metadata

## Goal

Add two readable metadata fields near the top of newly-created SASE agent chat transcripts under `~/.sase/chats/`:

```markdown
**Timestamp:** 2026-05-23 12:34:56 EDT **MODEL:** <llm-provider>/<model> **AGENT:** <sase-agent-name>
```

The fields should be added for agent-completion transcripts without changing existing chat filenames, sharding, resume
parsing, linked-chat behavior, or artifact `response_path` contracts.

## Current Findings

- `src/sase/history/chat.py::save_chat_history()` is the central markdown writer. It currently writes the H1 header and
  `**Timestamp:**` line, then optional extra sections, previous conversation, prompt, and response.
- The existing `agent` parameter is part of the filename/header shape for workflow sub-roles. It is not always the
  claimed SASE agent name, and the main ace-run final transcript currently does not pass it.
- `src/sase/axe/run_agent_exec_finalize.py::finalize_loop()` is the main completion path. It already computes
  `done_agent_name` and has `ctx.agent_model` / `ctx.agent_llm_provider`.
- Planner/question follow-up chat files are saved in `src/sase/axe/run_agent_exec_plan.py` and already derive
  role-specific agent names such as `foo-plan`, `foo-2`, and `foo-2-q`.
- Some lower-level prompt-step invocations also call `save_chat_history()` through `llm_provider.postprocessing` and
  `xprompt.workflow_executor_steps_prompt`; those paths know either the effective directives or the invocation context,
  but not always a claimed SASE agent name.
- `tests/history/test_chat.py` and `tests/history/test_chat_catalog.py` assume the current header layout. The catalog
  parser reads snippets from headings, so inserting fields directly after the timestamp should be safe if we preserve
  heading structure.

## Design

1. Extend `save_chat_history()` with explicit, keyword-only transcript metadata parameters, for example:
   - `metadata_model: str | None = None`
   - `metadata_llm_provider: str | None = None`
   - `metadata_agent: str | None = None`

2. Keep the existing `agent` argument semantics unchanged. It will continue to control the filename/header role segment.
   The new `metadata_agent` value will control only the `**AGENT:**` field.

3. Render the new fields immediately after `**Timestamp:**`.
   - Prefer a stable provider/model string such as `claude/claude-sonnet-...` when both values are known.
   - Fall back to just the model or just the provider if only one is known.
   - Do not emit misleading `unknown` values from generic callers unless the SASE runner explicitly decides the
     transcript is an agent transcript and no name/model is available.

4. Pass metadata from the main ace-run completion path:
   - `metadata_agent=done_agent_name`
   - `metadata_model=<effective model>`
   - `metadata_llm_provider=<effective provider>`

5. Account for model changes after initial launch.
   - Plan approval can switch the coder model and currently records that in `agent_meta.json`; final transcript metadata
     should prefer the latest artifact metadata over the original `AgentExecContext` values.
   - Retry fallback behavior should be checked while implementing; if the actual fallback model is recorded in retry
     metadata or environment, use that value rather than the original launch model.

6. Pass metadata for plan-chain transcript saves:
   - Planner chat: planner model/provider from `ctx`, agent name from the derived planner agent name.
   - Question chat: derived question agent name; model/provider should be included only when it accurately describes the
     LLM-backed step, otherwise keep the model field absent.

7. Cover generic invocation paths conservatively:
   - For `llm_provider.postprocessing`, extend `LoggingContext` only if necessary so the resolved provider/model from
     `_invoke.py` can reach `_save_to_chat_history()`.
   - For `xprompt.workflow_executor_steps_prompt`, pass the already-computed `step_llm_provider`, `step_model`, and step
     agent name to `save_chat_history()`.
   - For older/manual non-agent uses of `save_chat_history()`, leave metadata omitted unless the caller has reliable
     values.

8. Avoid changing historical transcripts. This change applies only to newly written markdown files.

## Tests

1. Add focused `save_chat_history()` tests in `tests/history/test_chat.py`:
   - Metadata fields appear directly below the timestamp when provided.
   - Existing output remains valid when metadata is omitted.
   - Filename/header `agent` and metadata `AGENT` can differ without changing the path.

2. Add/update completion-path tests:
   - `run_agent_exec_finalize` passes model/provider/agent metadata to `save_chat_history()`.
   - A plan-approved coder model override is reflected in final transcript metadata.

3. Add/update plan-chain tests in `tests/test_axe_run_agent_exec_plan_chat_paths.py` so captured `save_chat_history()`
   kwargs include the intended `metadata_agent` and, where accurate, model/provider metadata.

4. Add a narrow workflow prompt-step test if existing coverage does not already capture the `save_chat_history()` call.

5. Run targeted tests first:
   - `uv run pytest tests/history/test_chat.py tests/test_axe_run_agent_exec.py tests/test_axe_run_agent_exec_plan_chat_paths.py`

6. After implementation changes in this repo, run `just install` if needed and then `just check` as required by the
   workspace instructions.

## Risks And Guardrails

- Do not overload the existing `agent` argument; changing it could alter filenames and break `response_path`, linked
  chats, and resume-by-chat workflows.
- Do not add new markdown headings for these fields; heading-based transcript parsing should continue to find
  `## Prompt` and `## Response` exactly as before.
- Do not backfill or rewrite existing files in `~/.sase/chats/`.
- Keep metadata formatting simple and deterministic so later tools can parse it if needed.

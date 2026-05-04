---
create_time: 2026-05-04 19:23:44
status: done
prompt: sdd/prompts/202605/vcs_tag_workflow_prompt_inheritance.md
---
# Preserve VCS workflow tags through workflow prompt execution

## Context

Recent chats show top-level prompts like:

```text
%n:aax #gh:sase #!research_swarm:: summarize work
```

but the spawned workflow chat prompt is saved without the `#gh:sase` workspace selector:

```text
#!research_swarm:: summarize work
```

The same pattern appears with ordinary standalone workflows such as:

```text
#gh:sase #!sase/fix_just
```

where the child workflow prompt step is saved as the bare workflow step prompt. This makes the workflow step run without
the intended VCS wrapper unless the workflow author hardcodes a VCS tag into every step.

## Diagnosis

There are two similar but distinct paths:

1. Direct multi-agent xprompt dispatch:
   - `parse_multi_prompt()` splits user `---` prompts.
   - `expand_multi_agent_xprompts()` expands markdown xprompts whose bodies contain segment separators.
   - This path already carries leading VCS refs to every expanded subsegment. `tests/test_multi_agent_xprompt.py` has
     coverage for `#gh:sase #three` and `#gh:sase #!three`.

2. Standalone workflow wrapper execution:
   - `run_agent_runner_setup.preprocess_prompt_xprompts()` captures `ctx.vcs_tag` from the raw top-level prompt before
     expansion.
   - `run_execution_loop()` wraps the current prompt in an anonymous workflow and calls `execute_workflow()`.
   - `_flatten_anonymous_workflow()` extracts the standalone workflow from prompts like `#gh:sase #!workflow`,
     preserving only explicit workflow args plus wrapper model/HITL overrides.
   - `WorkflowExecutor._execute_prompt_step()` executes each workflow `agent` step independently. Since the inherited
     VCS tag is not executor metadata, bare step prompts remain bare.

This is why `research_swarm` has been hard to use correctly: the wrapper `#gh:sase` is treated as launch context for the
outer agent, but it does not become launch context for the inner prompt steps created by the workflow runner.

## Desired behavior

When a standalone workflow is invoked under a leading VCS workflow tag, each agent prompt step inside that workflow
should inherit the tag unless that step already declares its own VCS/workspace ref.

Examples:

- `#gh:sase #!research_swarm:: summarize` should produce workflow prompt steps beginning with `#gh:sase`.
- A generated follow-up segment like `%w #resume #research/more %m:opus` should become
  `%w #gh:sase #resume #research/more %m:opus`, preserving directives.
- A step already starting with `#gh:other`, `#git:other`, `#cd:~`, etc. should remain authoritative.

## Implementation plan

1. Add explicit inherited VCS metadata to the workflow runner.
   - Introduce an internal argument constant in `src/sase/xprompt/workflow_runner.py`, parallel to
     `_WORKFLOW_MODEL_OVERRIDE_ARG` and `_WORKFLOW_HITL_OVERRIDE_ARG`.
   - Pass `ctx.vcs_tag` from `run_execution_loop()` into `execute_workflow()` via `named_args` when present.
   - Strip that internal key before normal workflow args are exposed to templates or saved state.

2. Preserve the inherited tag through anonymous workflow flattening.
   - `_flatten_anonymous_workflow()` should not lose caller-injected internal metadata when it replaces the anonymous
     wrapper with the referenced workflow.
   - Existing merge behavior already preserves caller args; extend tests around that behavior for the VCS metadata.

3. Apply inherited VCS tags at the prompt-step boundary.
   - Add `inherited_vcs_tag` to `WorkflowExecutor`.
   - Before early prompt preprocessing in `_execute_prompt_step()`, prefix the step prompt with the inherited tag if the
     prompt segment lacks a VCS/workspace ref.
   - Apply the prefix per multi-prompt segment so workflows with `---` inside a step remain consistent.
   - Insert after leading `%` directives and before the prompt body, matching existing directive parsing expectations.
   - Reuse existing VCS parsing helpers for detection instead of ad hoc string matching.

4. Preserve explicit step refs.
   - If a step or generated segment already has `#gh:other`, `#git:branch`, `#hg:cl`, `#cd:path`, or a known-project
     fallback VCS ref, do not rewrite it.
   - This keeps cross-repo and home-mode workflow steps possible.

5. Cover the regression with focused tests.
   - Add workflow-runner tests that `execute_workflow()` passes `inherited_vcs_tag` to `WorkflowExecutor` and does not
     leak the internal key into template args.
   - Add prompt-step tests that inherited tags prefix bare prompts, preserve leading directives, apply per segment, and
     skip explicitly tagged segments.
   - Add a `research_swarm`-shaped regression using a multi-segment prompt step or local workflow fixture so
     `#gh:sase #!workflow` visibly becomes tagged inner prompts.

## Validation

Run targeted tests first:

```bash
PYTHONPATH=src pytest tests/test_xprompt_processor_workflow.py tests/test_workflow_executor.py tests/test_multi_agent_xprompt.py
```

Then follow repo instructions:

```bash
just install
just check
```

If `just check` fails for an environment-only reason, capture the exact failure and run the closest targeted checks that
do execute.

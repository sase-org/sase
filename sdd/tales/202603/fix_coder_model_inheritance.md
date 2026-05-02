---
create_time: 2026-03-31 08:34:25
status: done
prompt: sdd/prompts/202603/fix_coder_model_inheritance.md
---

# Fix: Coder agents not inheriting model from planner agents

## Problem

When a planner agent runs with a non-default model (e.g., `%model:opus`), the followup coder agent that implements the
approved plan always falls back to the default model.

**Root cause**: `handle_plan_marker()` in `run_agent_exec_plan.py` constructs entirely new prompts for followup agents
(both the direct coder and the epic agent). These new prompts lack a `%model` directive. When `execute_workflow`
processes the followup prompt, `preprocess_prompt()` finds no `%model` directive and falls back to the default model.

The model metadata IS correctly inherited in `agent_meta.json` via `create_followup_artifacts()`, but the LLM invocation
path only reads the model from prompt directives — it never consults `agent_meta.json`.

**Affected prompt assignments** in `run_agent_exec_plan.py`:

- Line 334: Epic path — `state.current_prompt = f"{vcs_prefix}#bd/new_epic:{plan_ref}\n{embedded_refs}"`
- Lines 365-370: Direct coder path — new prompt with `@plan_file` reference

**Not affected** (model already preserved):

- Line 241: Retry-with-feedback — rebuilds from `state.original_prompt` which retains the original `%model`
- Line 443: Questions followup — appends to existing prompt which retains `%model`

## Fix

Inject a `%model:<model>` directive into the two followup prompts when `ctx.agent_model` is set. This uses the same
mechanism the rest of the codebase already uses for model selection — no new infrastructure needed.

### Phase 1: Inject model directive into followup prompts

**File**: `src/sase/axe/run_agent_exec_plan.py`

Build a `model_prefix` string from `ctx.agent_model` (empty string when no model override). Prepend it to both the epic
and direct-coder prompts, before the VCS prefix:

- Epic (line 334): `state.current_prompt = f"{model_prefix}{vcs_prefix}#bd/new_epic:..."`
- Coder (line 365): `state.current_prompt = f"{model_prefix}{vcs_prefix}@{plan_file}..."`

Compute `model_prefix` once, right before the epic/coder branch:

```python
model_prefix = f"%model:{ctx.agent_model}\n" if ctx.agent_model else ""
```

### Phase 2: Add test coverage

**File**: `tests/test_axe_run_agent_exec_plan.py`

Add tests that verify the `%model` directive appears in followup prompts when `ctx.agent_model` is set, and does not
appear when it is `None`. This requires building minimal `AgentExecContext` and `LoopState` fixtures and calling
`handle_plan_marker()` with mocked dependencies.

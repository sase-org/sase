---
create_time: 2026-04-01 10:34:39
status: done
prompt: sdd/prompts/202604/coder_model_directive_override.md
---

# Plan: Allow `%m:` in Coder Custom Prompt Without Conflicting with Inherited Model

## Problem

When approving a plan via the "Approve with Options" panel, users can enter a custom prompt for the coder agent. The
coder prompt is constructed in `run_agent_exec_plan.py:300-368` by prepending `%model:{planner_model}` and appending the
custom prompt as "Additional instructions":

```
%model:opus                          <-- inherited from planner (line 300)
#gh:sase @plan.md

The above plan has been reviewed and approved. Implement it now.

Additional instructions:
%m:sonnet                            <-- user's custom directive (line 362)
```

The directive parser (`directives.py:157-158`) raises `DirectiveError("Duplicate directive '%model' in prompt")` when it
encounters two `%model` directives. This means users **cannot** use `%m:<model>` in the custom prompt to override the
coder's model — the most natural place to do so.

## Design

When the coder's custom prompt contains a `%model`/`%m` directive, skip injecting the inherited `model_prefix`. This
gives the user's explicit directive precedence over the inherited model, which is the intuitive behavior.

### Phase 1: Add `has_model_directive()` helper to `directives.py`

Following the existing `has_wait_directive()` pattern (line 102-110), add a lightweight regex check that detects whether
a string contains a `%model` or `%m` directive. This avoids the cost of full directive extraction just to check for
presence.

**File**: `src/sase/xprompt/directives.py`

### Phase 2: Conditionally skip model prefix in coder prompt construction

In `run_agent_exec_plan.py`, when building the coder prompt (the `else` branch at line 335), check whether
`plan_result.coder_prompt` contains a model directive. If it does, set `model_prefix = ""` so the user's directive is
the only one in the prompt.

The epic branch (line 302) does not use `coder_prompt`, so it is unaffected.

**File**: `src/sase/axe/run_agent_exec_plan.py`

### Phase 3: Tests

Add test cases to `tests/test_axe_run_agent_exec_plan.py`:

1. **Custom prompt with `%m:sonnet` overrides inherited model** — verify the prompt does NOT start with `%model:opus`
   and DOES contain `%m:sonnet` in the additional instructions.
2. **Custom prompt without model directive still inherits** — verify existing behavior (prompt starts with
   `%model:opus`) still works when the custom prompt has no model directive.

Add a unit test to `tests/test_directives.py` for the new `has_model_directive()` function covering `%m:`, `%model:`,
`%m(`, and negative cases.

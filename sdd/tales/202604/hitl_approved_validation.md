---
create_time: 2026-04-02 20:12:49
status: done
prompt: sdd/prompts/202604/hitl_approved_validation.md
---

# Fix: Validator rejects `approved` field on HITL bash/python steps

## Problem

The `#split` xprompt workflow (in retired Mercurial plugin) fails validation with:

```
Step 'execute_revert': references 'revert_prompt.approved' but 'revert_prompt' output has no field 'approved'. Available: ['message']
```

The `revert_prompt` step is a bash step with `hitl: true` and `output: { message: text }`. At runtime, when the user
accepts a HITL prompt on a bash or python step, the executor auto-injects `output["approved"] = True` (see
`workflow_executor_steps_script.py` lines 191 and 366). The downstream `execute_revert` step correctly references
`{{ revert_prompt.approved }}`.

However, the static validator (`validate_cross_step_field_refs` in `workflow_validator_checks.py`) only checks the
declared output schema properties. It doesn't account for the auto-injected `approved` field, so it rejects a valid
workflow.

This is analogous to how the validator already handles `artifact: stdout` steps by auto-injecting `_artifact` into the
known fields (line 235).

## Fix

In `validate_cross_step_field_refs()` in `workflow_validator_checks.py`, add `approved` to the known fields for any step
that has `hitl: true` and is a bash or python step (not agent steps, which don't inject `approved`).

### Where to add (after the existing artifact injection at line 235):

```python
# Steps with artifact: stdout auto-inject _artifact into output
if step.artifact:
    step_fields.setdefault(step.name, set()).add("_artifact")

# Bash/python steps with hitl: true auto-inject 'approved' into output
if step.hitl and (step.bash is not None or step.python is not None):
    step_fields.setdefault(step.name, set()).add("approved")
```

### Test

Add a test in `tests/test_workflow_validator_outputs.py` that verifies:

1. A bash step with `hitl: true` allows referencing `step.approved` without error.
2. An agent step with `hitl: true` does NOT allow referencing `step.approved` (since agents don't inject it).

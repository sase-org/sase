---
create_time: 2026-04-02 13:24:14
status: done
prompt: sdd/prompts/202604/wire_format_instructions.md
---

# Wire up `generate_format_instructions` for agent steps with output specs

## Problem

The `#sync` xprompt workflow's `resolve` step declares `output: { all_resolved: bool, files_resolved: int }` and uses a
`repeat/until` loop with condition `{{ resolve.all_resolved }}`. When a real merge conflict occurs and the agent
resolves it, the loop still runs a second unnecessary iteration because the agent's output isn't parsed correctly.

### Root Cause Chain

1. `generate_format_instructions()` exists in `src/sase/xprompt/output_validation.py` but is **never called** during
   prompt step execution -- only in tests.
2. Without JSON formatting instructions appended to the prompt, the agent outputs results as prose/bullet text instead
   of JSON.
3. `extract_structured_content()` fails to parse the text, falling back to `{"_raw": response_text}`.
4. The loop condition `{{ resolve.all_resolved }}` resolves to Jinja2 `undefined` (empty string) -> `False`.
5. The loop runs again unnecessarily.

This affects **all** workflow agent steps that declare `output:` specs -- the output schema is parsed and stored but
never communicated to the agent.

## Plan

### Phase 1: Wire up format instructions in prompt step execution

**File**: `src/sase/xprompt/workflow_executor_steps_prompt.py`

After the late preprocessing phase (line 217, `preprocess_prompt_late`) and before the agent invocation (line 283,
`invoke_agent`), append format instructions when the step has an output spec:

```python
# Append output format instructions if step has output spec
if step.output:
    from sase.xprompt import generate_format_instructions
    format_instr = generate_format_instructions(step.output)
    if format_instr:
        expanded_prompt = expanded_prompt + format_instr
```

### Phase 2: Validate

Run `just check` to ensure linting, type checking, and tests pass.

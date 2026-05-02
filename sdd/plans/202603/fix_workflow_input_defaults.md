---
create_time: 2026-03-27 16:42:05
status: done
prompt: sdd/prompts/202603/fix_workflow_input_defaults.md
---

# Plan: Fix workflow input default type coercion

## Problem

The `sase_refresh_docs` chop launches on schedule but its `run_docs` and `update_marker` steps are always skipped. The
workflow's `if:` condition (`{{ count_commits.count >= threshold }}`) silently evaluates to `False` because `threshold`
is a string `"10"` while `count_commits.count` is an int `45`. Jinja2 raises `TypeError` on `45 >= "10"`, which
`_evaluate_condition` catches and returns `False`.

## Root Cause

In `src/sase/xprompt/workflow_runner.py`, both default-application blocks unconditionally stringify defaults via
`str(input_arg.default)`:

- **Lines 400-405** (simple xprompts / prompt_parts)
- **Lines 458-464** (multi-step workflows) &larr; **this is the path `refresh_docs` hits**

The `refresh_docs.yml` workflow declares `threshold: { type: int, default: 10 }`. The YAML parser correctly gives
`default=10` (Python int), but line 464 converts it to `"10"` (Python str) before it enters the executor context.
Meanwhile, the `count_commits` step's output `count` is correctly coerced to `int` by the output-type system
(`coerce_output_types`). The resulting int-vs-str comparison in Jinja2 raises `TypeError`.

## Fix

### Step 1 &mdash; Preserve default types for multi-step workflow args

**File:** `src/sase/xprompt/workflow_runner.py` (lines 458-464)

Change from:

```python
for input_arg in workflow.inputs:
    if input_arg.name not in args and input_arg.default is not UNSET:
        if input_arg.default is None:
            args[input_arg.name] = "null"
        else:
            args[input_arg.name] = str(input_arg.default)
```

To:

```python
for input_arg in workflow.inputs:
    if input_arg.name not in args and input_arg.default is not UNSET:
        args[input_arg.name] = input_arg.default
```

This preserves the original Python type (`int`, `bool`, `float`, `None`, etc.) so Jinja2 conditions work correctly. The
`_jinja.py:127-131` code path already does exactly this.

### Step 2 &mdash; Preserve default types for simple xprompt args

**File:** `src/sase/xprompt/workflow_runner.py` (lines 400-405)

Apply the same fix to keep both code paths consistent:

```python
for input_arg in workflow.inputs:
    if input_arg.name not in render_ctx and input_arg.default is not UNSET:
        render_ctx[input_arg.name] = input_arg.default
```

Jinja2's `render_template` handles non-string values natively (e.g., `{{ threshold }}` renders `10` as `"10"` in the
output, and `{{ x >= threshold }}` correctly compares int-to-int). The `str()` wrapper was never necessary.

### Step 3 &mdash; Add tests

**File:** `tests/test_workflow_executor_conditionals.py`

Add a test that creates a workflow with an int-typed input with a default, a python step that outputs an int, and an
`if:` condition comparing the two. Verify the condition evaluates correctly and the conditional step is NOT skipped.

### Step 4 &mdash; Verify with `just check`

Run `just install && just check` to confirm lint, type-check, and tests pass.

## Files Changed

| File                                           | Change                                                     |
| ---------------------------------------------- | ---------------------------------------------------------- |
| `src/sase/xprompt/workflow_runner.py`          | Remove `str()` wrapping in both default-application blocks |
| `tests/test_workflow_executor_conditionals.py` | Add test for int default + int output condition comparison |

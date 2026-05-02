---
create_time: 2026-04-03 14:07:17
status: done
prompt: sdd/prompts/202604/null_arg_validation.md
---

# Plan: Fix xprompt null argument validation

## Problem

When `null` is passed as an xprompt argument within a workflow YAML (e.g., `chain: { type: bool, default: null }`), it
should mean "use the callee's default value." Instead, it fails validation:

```
❌ XPrompt '#split_spec_generator' argument error: Argument 'should_chain_cls' expects bool, got 'None'
```

## Root Cause

1. YAML `null` → Python `None` in the workflow context
2. Step prompt template: `should_chain_cls="{{ chain }}"`
3. Jinja2's `_finalize_value()` only handles bool→lowercase, doesn't handle `None`
4. Jinja2 renders `{{ chain }}` as `"None"` (Python's `str(None)`)
5. `parse_args` extracts `should_chain_cls="None"`
6. `validate_and_convert_args` checks `value == "null"` → `"None" != "null"` → not treated as null pass-through
7. `validate_and_convert` tries to parse `"None"` as bool → validation error

## Fix

**Add None handling to `_finalize_value`** in `src/sase/xprompt/workflow_executor_utils.py` so Python `None` renders as
the string `"null"` instead of `"None"`. This is:

- Consistent with existing bool handling (`True` → `"true"`, `False` → `"false"`)
- Consistent with YAML semantics (YAML null → string "null")
- Compatible with the existing `value == "null"` pass-through check in `validate_and_convert_args`
- Safe because the `_tojson` filter already handles Python code contexts separately (rendering None as "None")

## Files to Change

1. `src/sase/xprompt/workflow_executor_utils.py` — Add `if value is None: return "null"` to `_finalize_value`
2. Tests — Add coverage for `_finalize_value(None)` and the end-to-end template rendering with None context values

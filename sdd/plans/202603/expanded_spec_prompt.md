---
prompt: sdd/prompts/202603/expanded_spec_prompt.md
---
# Plan: Store Expanded Xprompt in Spec Files

## Problem

When a plan is approved or an epic is created, `write_sdd_files()` stores the **raw** user prompt (with unexpanded
`#gh:sase`, `#reads`, `%plan` directives, etc.) in `specs/<name>.md`. The user wants the **expanded** prompt stored
instead — with all xprompt references resolved to their content and directives stripped.

## Current Flow

1. `run_execution_loop()` in `axe_run_agent_exec.py` receives `prompt` (raw text)
2. Plan approval happens, then at line 401-402:
   ```python
   sdd_spec_path_obj, _ = write_sdd_files(sdd_dir, sdd_plan_name, prompt, plan_result.plan_file)
   ```
3. `write_sdd_files()` in `sdd.py` writes the raw `prompt` directly to `specs/<name>.md`

## Desired Flow

Before passing to `write_sdd_files()`, expand the prompt:

1. Expand simple xprompts (`#reads` → content) via `process_xprompt_references()`
2. Expand embedded workflow prompt_parts (`#gh:sase` → rendered prompt_part) — **without** executing pre/post-steps
3. Remove directives (`%plan`, `%approve`) via `extract_prompt_directives()`

## Implementation

### Phase 1: Add `expand_prompt_for_spec()` to `src/sase/sdd.py`

New function that does a "dry" expansion:

```python
def expand_prompt_for_spec(prompt: str) -> str:
    """Expand xprompt references and strip directives for spec storage."""
```

Steps inside:

1. Call `preprocess_prompt_early(prompt)` — this handles xprompt expansion + directive extraction
2. Call a new helper `_dry_expand_embedded_workflows(expanded)` — replaces workflow references with their `prompt_part`
   content without executing pre/post-steps

The dry embedded workflow expansion will:

- Use `get_all_workflows()` and the same `_WORKFLOW_REF_PATTERN` regex to find workflow references
- Parse args (reusing `_parsing` helpers)
- For each workflow with a `prompt_part`: call `get_prompt_part_content()` and `render_template()` with the parsed args
- Replace the reference text with the rendered content (right-to-left for position safety)
- Skip workflows without `prompt_part` (standalone workflows) — these are left as-is or removed

### Phase 2: Update call site in `src/sase/axe_run_agent_exec.py`

At line ~401, change:

```python
# Before:
write_sdd_files(sdd_dir, sdd_plan_name, prompt, plan_result.plan_file)

# After:
from sase.sdd import expand_prompt_for_spec
expanded = expand_prompt_for_spec(prompt)
write_sdd_files(sdd_dir, sdd_plan_name, expanded, plan_result.plan_file)
```

### Phase 3: Tests

Add tests for `expand_prompt_for_spec()` verifying:

- Simple xprompt references are expanded
- Directives are removed
- Embedded workflow prompt_parts are expanded
- Pre/post-steps are NOT executed
- Unknown `#references` are left as-is

## Files to Modify

1. `src/sase/sdd.py` — add `expand_prompt_for_spec()` and `_dry_expand_embedded_workflows()`
2. `src/sase/axe_run_agent_exec.py` — call `expand_prompt_for_spec()` before `write_sdd_files()`
3. `tests/xprompt/test_expand_for_spec.py` — new test file (or add to existing sdd tests)

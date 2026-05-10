---
create_time: 2026-04-03 11:50:07
status: done
prompt: sdd/prompts/202604/fix_split_cl_name.md
---

# Plan: Fix `cl_name` undefined in `#split` xprompt workflow via `sase run`

## Problem

Running `sase run "#hg:yserve_batch_create_update #split"` fails with:

```
jinja2.exceptions.UndefinedError: 'cl_name' is undefined
```

The `#split` workflow (`split.yml` in retired Mercurial plugin) uses `{{ cl_name }}` in its first step's bash command, but `cl_name`
is never injected into the workflow context when executing via `sase run`.

## Root Cause

There are two code paths that call `execute_workflow()`:

1. **TUI path** (`src/sase/axe/run_workflow_runner.py:154-159`): Injects `cl_name`, `project_file`, and `workspace_num`
   into `workflow_named_args` before calling `execute_workflow()`.

2. **CLI `sase run` path** (`src/sase/main/query_handler/_query.py:229-236`): Passes empty `{}` as named_args — no
   `cl_name` injection despite having it available on line 86.

The `cl_name` variable is computed in `run_query()` (line 86) from the VCS project reference but never forwarded to
`execute_workflow()`.

## Fix

**File:** `src/sase/main/query_handler/_query.py`

Inject `cl_name`, `project_file`, and `workspace_num` into named_args before the `execute_workflow()` call (lines
229-236), mirroring what `run_workflow_runner.py` does:

```python
# Inject implicit workflow context variables (mirrors run_workflow_runner.py)
workflow_named_args: dict[str, Any] = {}
if cl_name:
    workflow_named_args["cl_name"] = cl_name
if project_file:
    workflow_named_args["project_file"] = project_file
if workspace_num:
    workflow_named_args["workspace_num"] = workspace_num

result = execute_workflow(
    anon_workflow.name,
    [],
    workflow_named_args,
    artifacts_dir=artifacts_dir,
    workflow_obj=anon_workflow,
    project=vcs_project,
)
```

Only inject values that are non-None/non-zero to avoid polluting the context with empty strings or zeros, which could
mask legitimate "undefined variable" errors in other workflows.

## Scope

- **Single file change**: `src/sase/main/query_handler/_query.py`
- No changes needed in retired Mercurial plugin's `split.yml` (it correctly expects `cl_name` from context)
- No changes needed in `workflow_runner.py` or `workflow_executor.py`

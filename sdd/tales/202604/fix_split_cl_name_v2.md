---
create_time: 2026-04-03 12:15:07
status: done
---

# Plan: Fix `cl_name` undefined in `#split` workflow via `sase run` (v2)

## Problem

Running `sase run "#hg:yserve_batch_create_update #split"` fails with `'cl_name' is undefined` even after the previous
fix (commit 7e1428e7) that injected `cl_name` into `workflow_named_args` in `_query.py`.

## Root Cause (Two Issues)

### Issue 1: `named_args` overwritten during anonymous workflow flattening

The previous fix correctly injects `cl_name`, `project_file`, and `workspace_num` into `workflow_named_args` at
`_query.py:228-234`. However, `execute_workflow()` in `workflow_runner.py` **completely replaces** `named_args` when
flattening the anonymous workflow:

```python
# workflow_runner.py:417-420
if workflow.is_anonymous():
    flattened = _flatten_anonymous_workflow(workflow, project=project)
    if flattened is not None:
        workflow, positional_args, named_args = flattened  # OVERWRITES caller's named_args!
```

The flattening extracts `#split` as a standalone workflow with its own (empty) `named_args`, discarding the
caller-injected `cl_name`, `project_file`, and `workspace_num`.

Evidence from logpack: The failed run's `workflow_state.json` context is `{"split_desc": null, "chain": null}` with no
`cl_name` at all. Meanwhile, the successful TUI run's context includes `cl_name`, `project_file`, and `workspace_num`.

### Issue 2: `cl_name` value is wrong (project name instead of CL name)

In `_query.py:86`, `cl_name = vcs_project` gives the project name (e.g., "yserve") or falls back to the directory
basename ("sase"). The split workflow expects the actual CL name ("yserve_batch_create_update").

`_resolve_vcs_cwd()` returns `resolved.project_name or ref`, but if `resolve_ref()` fails entirely (as it did here --
`done.json` shows `vcs_provider: "GitHub"`, `cl_name: "sase"`), it returns `None` and the CL name is lost.

The VCS ref ("yserve_batch_create_update") is always extractable from the query pattern `#hg:<ref>`, regardless of
whether workspace resolution succeeds.

## Fix

### Change 1: Merge `named_args` when flattening anonymous workflows

**File:** `src/sase/xprompt/workflow_runner.py` (lines 417-420)

When `_flatten_anonymous_workflow` returns a flattened workflow, merge the caller's `named_args` with the flattened ones
instead of replacing them. The flattened args should take precedence (they're workflow-specific), while caller-injected
context variables (`cl_name`, `project_file`, `workspace_num`) serve as the base:

```python
if workflow.is_anonymous():
    flattened = _flatten_anonymous_workflow(workflow, project=project)
    if flattened is not None:
        workflow, positional_args, flattened_named = flattened
        named_args = {**named_args, **flattened_named}
```

### Change 2: Return VCS ref from `_resolve_vcs_cwd`

**File:** `src/sase/main/query_handler/_query.py`

Modify `_resolve_vcs_cwd()` to return `(project_name, vcs_ref)` instead of just `project_name`. The `vcs_ref` is the raw
ref extracted from the `#type:ref` pattern (e.g., "yserve_batch_create_update"), captured regardless of whether
`resolve_ref()` succeeds.

Then update the caller to use `vcs_ref` as the `cl_name`.

## Scope

- **Two files changed:** `workflow_runner.py` (merge fix) and `_query.py` (return value + cl_name)
- No changes to retired Mercurial plugin plugin or `split.yml`
- No changes to `run_workflow_runner.py` (TUI path already works correctly)

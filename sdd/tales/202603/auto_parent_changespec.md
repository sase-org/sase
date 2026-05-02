---
create_time: 2026-03-27 11:05:45
status: done
prompt: sdd/prompts/202603/auto_parent_changespec.md
---

# Plan: Auto-set PARENT on new ChangeSpec during `sase commit`

## Problem

When `sase commit` creates a new ChangeSpec via `create_pull_request`, it always passes `parent=None` to
`add_changespec_to_project_file()`. This means the new ChangeSpec is never associated with the parent ChangeSpec, even
when the commit is made from a branch that already has an existing ChangeSpec.

Example: `pat_fix_flaky_chart_test_1` was created from the `pat_line_chart_component` branch but has no
`PARENT: pat_line_chart_component` field.

## Root Cause

In `src/sase/workspace_provider/changespec.py:172`, `create_changespec_for_workflow()` hardcodes `parent=None`:

```python
result = add_changespec_to_project_file(
    project_name,
    cl_name,
    description,
    parent=None,  # <-- always None
    ...
)
```

Nobody detects or passes the parent ChangeSpec from the current branch context.

## Implementation

### Step 1: Detect parent in `CommitWorkflow.run()` before VCS dispatch

**File:** `src/sase/workflows/commit/workflow.py`

In `run()`, before dispatching to the VCS provider (line 90), detect the current branch's ChangeSpec name. This MUST
happen before VCS dispatch because `create_pull_request` may change the branch. Only do this for `create_pull_request`
(the only method that creates new ChangeSpecs).

```python
# Detect parent ChangeSpec from current branch (before VCS may change it)
self._parent_cl_name: str | None = None
if self._method == "create_pull_request":
    self._parent_cl_name = self._detect_parent_changespec()
```

Add a new `_detect_parent_changespec()` method that:

1. Calls `get_cl_name_from_branch()` to get the current branch name
2. Gets the project name and file path (reusing logic already in `_create_changespec`)
3. Uses `get_changespec_from_file()` to verify the branch name corresponds to an existing ChangeSpec
4. Returns the ChangeSpec name if found, `None` otherwise
5. Ensures the detected parent is NOT the same as the new CL name being created (safety check)

### Step 2: Thread parent through `_create_changespec()` to `create_changespec_for_workflow()`

**File:** `src/sase/workflows/commit/workflow.py`

In `_create_changespec()`, pass `self._parent_cl_name` to `create_changespec_for_workflow()` as a new `parent` kwarg.

### Step 3: Add `parent` parameter to `create_changespec_for_workflow()`

**File:** `src/sase/workspace_provider/changespec.py`

1. Add `parent: str | None = None` parameter to the function signature
2. Pass it through to `add_changespec_to_project_file()` instead of the hardcoded `None`

`add_changespec_to_project_file()` already handles parent correctly: it inserts after the parent, inherits hooks and
BUG, and writes the `PARENT:` line. No changes needed there.

### Step 4: Add tests

**File:** `tests/workspace_provider/test_changespec.py`

Add a test that verifies `create_changespec_for_workflow()` passes the `parent` argument through to
`add_changespec_to_project_file()` when provided.

**File:** `tests/workflows/test_commit_workflow.py`

Add tests for `_detect_parent_changespec()`:

- Returns branch name when it matches an existing ChangeSpec
- Returns `None` when branch has no ChangeSpec
- Returns `None` when branch name matches the new CL name (self-parent prevention)
- Returns `None` when `get_cl_name_from_branch()` fails

## Key Design Decisions

1. **Detect before VCS dispatch** - The VCS provider's `create_pull_request` may change the branch, so we must capture
   the current branch beforehand.

2. **Verify ChangeSpec exists** - Don't blindly use the branch name as parent. Use `get_changespec_from_file()` to
   confirm the branch corresponds to an actual ChangeSpec. This avoids bogus parents when committing from `master` or
   other non-ChangeSpec branches.

3. **No changes to `add_changespec_to_project_file()`** - It already handles parent insertion, hook/BUG inheritance, and
   the `PARENT:` field correctly. We just need to actually pass the parent to it.

4. **Best-effort** - Wrap parent detection in try/except (matching the existing pattern in `_create_changespec`). If
   detection fails, fall back to `parent=None` silently.

## Files Changed

| File                                          | Change                                                                                                          |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `src/sase/workflows/commit/workflow.py`       | Add `_detect_parent_changespec()` method; call it in `run()`; pass parent to `create_changespec_for_workflow()` |
| `src/sase/workspace_provider/changespec.py`   | Add `parent` param to `create_changespec_for_workflow()` and pass to `add_changespec_to_project_file()`         |
| `tests/workspace_provider/test_changespec.py` | Test parent passthrough                                                                                         |
| `tests/workflows/test_commit_workflow.py`     | Test `_detect_parent_changespec()` logic                                                                        |

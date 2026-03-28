---
create_time: 2026-03-28 11:57:50
status: done
---

# Fix: `#pr` bug_id not propagated to ChangeSpec BUG field

## Problem

When the `#pr` xprompt workflow is invoked with a `bug_id` input argument, the `BUG=<bug_id>` PR tag is correctly added
to the PR description, but the `BUG: http://b/<bug_id>` field is **not** added to the ChangeSpec entry in the project
file.

## Root Cause

The `SASE_BUG_ID` environment variable is set by `pr.yml` but never read during ChangeSpec creation. The call chain is:

1. `pr.yml` sets `SASE_BUG_ID: "{{ bug_id }}"` in the environment
2. `CommitWorkflow._create_changespec()` calls `create_changespec_for_workflow()` — **no `bug` parameter passed**
3. `create_changespec_for_workflow()` — **does not accept a `bug` parameter** at all
4. `add_changespec_to_project_file()` — receives `bug=None`, so no BUG line is emitted

The `bug` parameter support already exists at the bottom of the chain (`add_changespec_to_project_file` accepts
`bug: str | None`), but nothing upstream feeds it.

## Fix

### Part A: Thread `bug` through `create_changespec_for_workflow`

**File:** `src/sase/workspace_provider/changespec.py`

Add a `bug: str | None = None` parameter to `create_changespec_for_workflow()` and pass it through to
`add_changespec_to_project_file()`.

### Part B: Read `SASE_BUG_ID` in `CommitWorkflow._create_changespec`

**File:** `src/sase/workflows/commit/workflow.py`

In `_create_changespec()`, read `SASE_BUG_ID` from the environment. If it's a truthy, non-zero value, format it as
`http://b/<bug_id>` and pass it as the `bug` parameter to `create_changespec_for_workflow()`.

### Part C: Tests

Add a test that verifies the full chain: when `SASE_BUG_ID` is set in the environment, the resulting ChangeSpec in the
project file includes a `BUG: http://b/<bug_id>` line.

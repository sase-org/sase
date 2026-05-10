---
create_time: 2026-03-25 18:00:25
status: done
prompt: sdd/prompts/202603/changespec_mercurial_fix.md
---

# Plan: Fix ChangeSpec Creation for Mercurial VCS (`#pr` workflow)

## Problem

When running an agent with `#pr:foobar` on a Mercurial workspace (retired Mercurial plugin plugin), two things go wrong:

1. **No ChangeSpec is created** for the CL
2. **The CL name is missing the `_<N>` suffix** (created as `eval_foobar` instead of `eval_foobar_1`)

## Root Cause Analysis

### The Execution Flow (from logpack)

1. Agent runs with `#hg:eval ... #pr:foobar`
2. Agent makes file changes, then tries to terminate
3. `sase_commit_stop_hook` fires, detects uncommitted changes, blocks the agent
4. Stop hook tells agent: "Use `/sase_hg_commit` to commit. Name must be `eval_foobar`."
5. Agent runs `sase commit` → `CommitWorkflow.run(method="create_pull_request")`
6. `CommitWorkflow.run()`:
   - Calls `vcs_create_pull_request({"name": "eval_foobar", ...})` → CL created as `eval_foobar`
   - Calls `_create_changespec()` → **returns None** (see below)
   - Writes `commit_result.json` with `changespec_name: null`
7. `#pr` workflow's `check_changes` step finds `has_changes=false` (already committed)
8. `#pr` workflow's `create` and `report` steps are **skipped** (gated on `has_changes`)

### Why `_create_changespec()` Returns None

`_create_changespec()` → `create_changespec_for_workflow()` → `_get_commits_ahead()` runs:

```python
git log --format=%s HEAD~1..
```

This fails in a Mercurial workspace because:

- `git log` doesn't exist / doesn't work in hg workspaces
- `HEAD~1` is a git-specific revision reference
- `branch_name` from the payload is the CL name (e.g., `"foobar"`), not a git branch

Since `_get_commits_ahead()` returns `[]`, `create_changespec_for_workflow()` returns `None` immediately (line 126-127
of `changespec.py`).

### Why the CL Name Lacks the `_<N>` Suffix

The `_<N>` suffix is computed inside `add_changespec_to_project_file()` (line 150-151 of `changespec_operations.py`),
which is only reached via `create_changespec_for_workflow()`. Since that function returns early (no commits detected),
the suffix is never computed. Even if it were, the CL has already been created by the VCS provider at that point with
the unsuffixed name.

## Fix Strategy

Two changes are needed, both in `CommitWorkflow.run()` (`src/sase/workflows/commit/workflow.py`):

### Change 1: Pre-compute the suffixed CL name before creating the CL

Before dispatching to the VCS provider, compute the `_<N>` suffix and update the payload name:

1. Extract a standalone `compute_suffixed_cl_name(project_name, base_cl_name) -> str` helper that reads existing
   ChangeSpec names from the project file + archive and returns the suffixed name (e.g., `eval_foobar_1`). This logic
   already exists in `add_changespec_to_project_file()` lines 126-151 — extract it.
2. In `CommitWorkflow.run()`, for `create_pull_request` method, call this helper to get the suffixed name and update
   `self._payload["name"]` before calling the VCS provider.
3. This ensures the CL is created with the correct suffixed name.

### Change 2: Make `create_changespec_for_workflow()` work without `git log`

The function needs commit subjects for two purposes:

- **Gate**: If no commits, return None
- **Derive CL name**: From first commit subject (only when `cl_name` is not passed)

Since `CommitWorkflow._create_changespec()` already passes `branch_name` as a parameter, and the commit message is in
the payload, we can:

1. Add a `commit_description` parameter to `create_changespec_for_workflow()` that provides a fallback when
   `_get_commits_ahead()` returns empty. This way git-based flows are unchanged, but non-git flows can pass the commit
   message directly.
2. In `CommitWorkflow._create_changespec()`, pass `self._payload.get("message", "")` as the fallback commit description.
3. Similarly, for `_save_committed_diff()`: use the VCS provider's `committed_diff()` method as a fallback when
   `git diff` fails. Or simply accept that the diff may be unavailable for non-git VCS (it's already best-effort).

## Implementation Steps

### Step 1: Extract suffix computation into a standalone helper

**File**: `src/sase/workflows/commit/changespec_operations.py`

Add a new function `compute_suffixed_cl_name(project: str, cl_name: str) -> str | None`:

- Reads existing names from the project file + archive (reuses logic from lines 126-151)
- Computes and returns the suffixed name (e.g., `eval_foobar_1`)
- Returns `None` if the project file doesn't exist and can't be created

### Step 2: Pre-compute suffix in `CommitWorkflow.run()`

**File**: `src/sase/workflows/commit/workflow.py`

In `run()`, before the `dispatch` call (line 68), when `self._method == "create_pull_request"`:

1. Import `compute_suffixed_cl_name` and project helpers
2. Get the project name and compute the suffixed CL name
3. Update `self._payload["name"]` with the suffixed name
4. Wrap in try/except so failures don't block the CL creation (best-effort, like `_create_changespec`)

### Step 3: Add `commit_description` fallback to `create_changespec_for_workflow()`

**File**: `src/sase/workspace_provider/changespec.py`

1. Add `commit_description: str | None = None` parameter
2. When `_get_commits_ahead()` returns empty and `commit_description` is provided, use `[commit_description]` as the
   commits list (treating it as a single commit subject)
3. This makes the function work for non-git VCS without changing the git path

### Step 4: Pass commit description from `CommitWorkflow._create_changespec()`

**File**: `src/sase/workflows/commit/workflow.py`

In `_create_changespec()`:

1. Pass `commit_description=self._payload.get("message", "")` to `create_changespec_for_workflow()`
2. Also pass the suffixed name as `cl_name` to avoid re-deriving it

### Step 5: Make `_save_committed_diff()` VCS-agnostic (best-effort)

**File**: `src/sase/workspace_provider/changespec.py`

In `_save_committed_diff()`, when `git diff` fails:

1. Try using the VCS provider's `committed_diff()` method as a fallback
2. Return `None` gracefully if neither works (already the behavior on git failure)

### Step 6: Tests

Add tests for:

- `compute_suffixed_cl_name()` basic behavior
- `create_changespec_for_workflow()` with `commit_description` fallback
- `CommitWorkflow.run()` name suffixing for `create_pull_request`

## Files to Modify

1. `src/sase/workflows/commit/changespec_operations.py` — extract suffix helper
2. `src/sase/workflows/commit/workflow.py` — pre-compute suffix, pass commit description
3. `src/sase/workspace_provider/changespec.py` — add commit_description fallback, VCS-agnostic diff

## Risk Assessment

- **Low risk**: The git path is unchanged — `_get_commits_ahead()` succeeds for git, so the new fallback is never
  triggered for git-based workflows.
- **Low risk**: Suffix pre-computation is best-effort (wrapped in try/except). If it fails, the flow falls back to the
  current behavior (unsuffixed name).
- **Medium risk**: The suffix is now computed before the CL is created. If two agents race to create CLs with the same
  base name, they could compute the same suffix. This is mitigated by the existing `changespec_lock` in
  `add_changespec_to_project_file()`, but the VCS CL name could still collide. This is an acceptable risk since the
  ChangeSpec lock prevents duplicate ChangeSpec names.

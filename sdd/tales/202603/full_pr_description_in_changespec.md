---
create_time: 2026-03-31 08:51:16
status: draft
prompt: sdd/prompts/202603/full_pr_description_in_changespec.md
---

# Full PR Description in ChangeSpec DESCRIPTION Field

## Problem

When a ChangeSpec is created during the `create_pull_request` workflow, the DESCRIPTION field only contains commit
subject lines (the first line of each commit). The full PR description body is lost.

## Root Cause

The data flow during ChangeSpec creation is:

1. Agent writes a multi-line commit message (title + body) — stored as `payload["message"]`
2. `CommitWorkflow._create_changespec()` passes `commit_description=self._payload.get("message", "")` to
   `create_changespec_for_workflow()`
3. `create_changespec_for_workflow()` calls `_get_commits_ahead()` which uses `git log --format=%s` — **subject only**
4. Since git log succeeds (returns subject lines), the `commit_description` fallback is **never used**
5. `_build_description()` builds the DESCRIPTION from subject-only commits
6. The full body from the PR message is discarded

The `commit_description` parameter (which contains the full PR message) exists but is documented and used strictly as a
fallback for non-git VCS where `git log` is unavailable.

## Key Files

| File                                                 | Role                                                                               |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `src/sase/workspace_provider/changespec.py`          | `_get_commits_ahead()`, `_build_description()`, `create_changespec_for_workflow()` |
| `src/sase/workflows/commit/workflow.py`              | `CommitWorkflow._create_changespec()` — calls `create_changespec_for_workflow`     |
| `src/sase/workflows/commit/changespec_operations.py` | `add_changespec_to_project_file()` — writes DESCRIPTION to .gp file                |
| `tests/workspace_provider/test_changespec.py`        | Unit tests for changespec creation                                                 |
| `tests/test_commit_workflow_changespec.py`           | Integration tests for CommitWorkflow ChangeSpec flow                               |

## Design

**Core idea**: When `commit_description` is available (which it always is for the `create_pull_request` path), use the
full message as the DESCRIPTION source rather than reconstructing from `git log --format=%s` subjects.

The `commit_description` parameter already contains the full PR message (title + body). The fix is to elevate it from a
fallback to the preferred source for the DESCRIPTION, while still using git log subjects for:

- CL name derivation (`_derive_cl_name`)
- Detecting whether there are any commits at all (the "no commits" early return)

### Changes to `create_changespec_for_workflow()`

Currently:

```python
commits = _get_commits_ahead(checkout_target, branch_name)
if not commits and commit_description:
    commits = [strip_pr_tags(commit_description)]
if not commits:
    return None

if cl_name is None:
    cl_name = _derive_cl_name(project_name, commits)
description = _build_description(commits)
```

After:

```python
commits = _get_commits_ahead(checkout_target, branch_name)
if not commits and commit_description:
    commits = [strip_pr_tags(commit_description)]
if not commits:
    return None

if cl_name is None:
    cl_name = _derive_cl_name(project_name, commits)

# Prefer the full commit_description (PR message) when available,
# falling back to git-log subjects for non-PR or legacy paths.
if commit_description:
    description = strip_pr_tags(commit_description)
else:
    description = _build_description(commits)
```

This is a minimal, surgical change. `commit_description` already goes through `strip_pr_tags` in the fallback path, so
we apply the same treatment here.

### Test Updates

1. **`test_create_changespec_for_workflow_success`** — currently asserts `description == "feat: add thing"` (subject
   only). The test passes no `commit_description`, so behavior should remain unchanged here — `_build_description` is
   still the fallback.

2. **New test: `test_create_changespec_uses_full_commit_description`** — verify that when both `_get_commits_ahead`
   returns subjects AND `commit_description` is provided (the PR path), the full `commit_description` is used for
   DESCRIPTION instead of just subjects.

3. **`test_create_changespec_for_workflow_no_commits_with_fallback`** — update to verify multi-line description is
   preserved when used as fallback.

4. **Test with PR tags in commit_description** — verify `strip_pr_tags` is applied to the full description.

## Phases

### Phase 1: Use `commit_description` as primary DESCRIPTION source

- Modify `create_changespec_for_workflow()` in `src/sase/workspace_provider/changespec.py`
- Add/update tests in `tests/workspace_provider/test_changespec.py`
- Update the test in `tests/test_commit_workflow_changespec.py` that asserts description content

## Scope Boundaries

- This change only affects the **initial ChangeSpec creation** during the PR workflow
- The reword/sync flow (`_sync_description_bg` in `ace/handlers/reword.py`) is a separate path and out of scope
- No changes needed to the .gp parser/serializer — it already handles multi-line DESCRIPTION correctly
- No changes needed to the GitHub plugin — it already passes the full message

---
create_time: 2026-03-24 09:34:47
status: done
prompt: sdd/prompts/202603/commit_workflow_fixes.md
---

# Plan: VCS Commit Workflow Fixes & Improvements

## Background

After a thorough review of the sase-9 (unified VCS commit prompts) and sase-a (implementation gaps) work — including all
source code, tests, specs, plans, and git history — I identified several bugs, code quality issues, and test gaps in the
unified commit workflow system.

## Issue Summary

| #   | Issue                                                         | Severity | Scope                   |
| --- | ------------------------------------------------------------- | -------- | ----------------------- |
| 1   | `_create_changespec` can crash workflow on success            | Medium   | sase core               |
| 2   | No validation of `name` field for `create_pull_request`       | Medium   | sase core               |
| 3   | Missing `--` separator in git add with file lists             | Low      | sase core + sase-github |
| 4   | Duplicated git add/commit/push logic across plugins           | Medium   | sase core + sase-github |
| 5   | Dead `main()` entry point in `__init__.py`                    | Low      | sase core               |
| 6   | Missing tests for changespec error handling + name validation | Medium   | sase core               |

Note: `checkout_target` default `HEAD~1` was considered but not included — the skill is expected to pass the correct
value, and changing the default would require VCS provider awareness in the workflow layer.

---

## Phase 1: Bug fixes in CommitWorkflow

**Goal**: Fix the two bugs in `CommitWorkflow` that can cause incorrect behavior.

**Scope**: `src/sase/workflows/commit/workflow.py`, `tests/test_commit_workflow.py`

### 1a: Wrap `_create_changespec` in try/except

The method is described as "best-effort" (line 61) but any exception from `get_project_file_path()` or
`create_changespec_for_workflow()` propagates up through `run()`, causing the overall workflow to appear to fail even
though the VCS operation succeeded. The agent would think the commit/PR creation failed when it actually worked.

**Fix**: Wrap the body of `_create_changespec` in a try/except that logs the error and returns gracefully:

```python
def _create_changespec(self, cl_url: str | None) -> None:
    """Best-effort ChangeSpec creation after a successful PR flow."""
    try:
        from sase.workflows.utils import ...
        # ... existing logic ...
    except Exception as exc:
        print_status(f"Skipping ChangeSpec: {exc}", "warning")
```

### 1b: Validate `name` field for `create_pull_request`

The payload validation checks for `message` but not `name`. For `create_pull_request`, `name` is required (it's used as
the branch name). With the default `.get("name", "")`, `git checkout -b ""` fails with a confusing git error.

**Fix**: Add validation after the existing `message` check:

```python
if self._method == "create_pull_request" and not self._payload.get("name"):
    print_status("Payload missing required 'name' field for create_pull_request.", "error")
    return False
```

### Tests

Add to `tests/test_commit_workflow.py`:

- `test_changespec_exception_does_not_fail_workflow`: Mock `get_project_file_path` to raise, verify `run()` still
  returns True
- `test_missing_name_for_pull_request_returns_false`: Empty/missing `name` field fails validation
- `test_name_present_for_pull_request_passes_validation`: Valid payload passes

### Verification

- `just check` passes

---

## Phase 2: Extract shared git dispatch logic to GitCommon

**Goal**: Eliminate the duplicated `vcs_create_commit` / `vcs_create_proposal` / `vcs_create_pull_request` code between
`BareGitPlugin` and `GitHubPlugin`.

**Scope**: `src/sase/vcs_provider/plugins/_git_common.py`, `src/sase/vcs_provider/plugins/bare_git.py`,
`../sase-github/src/sase_github/plugin.py`

### Current State

`vcs_create_commit` is identical in both plugins (git add → git commit → git push). Both delegate `create_proposal` to
`create_commit`. The first 4 steps of `vcs_create_pull_request` are identical (checkout -b, add, commit, push); only
GitHub adds `gh pr create`.

### Implementation

**File: `_git_common.py`** — Move shared dispatch methods here:

```python
@hookimpl
def vcs_create_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    message = payload.get("message", "")
    files = payload.get("files", [])
    if files:
        out = self._run(["git", "add", "--"] + files, cwd)
    else:
        out = self._run(["git", "add", "-A"], cwd)
    if not out.success:
        return self._to_result(out, "git add")
    out = self._run(["git", "commit", "-m", message], cwd)
    if not out.success:
        return self._to_result(out, "git commit")
    out = self._run(["git", "push"], cwd)
    if not out.success:
        return self._to_result(out, "git push")
    return (True, None)

@hookimpl
def vcs_create_proposal(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    return self.vcs_create_commit(payload, cwd)

@hookimpl
def vcs_create_pull_request(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    name = payload.get("name", "")
    message = payload.get("message", "")
    files = payload.get("files", [])
    out = self._run(["git", "checkout", "-b", name], cwd)
    if not out.success:
        return self._to_result(out, "git checkout -b")
    if files:
        out = self._run(["git", "add", "--"] + files, cwd)
    else:
        out = self._run(["git", "add", "-A"], cwd)
    if not out.success:
        return self._to_result(out, "git add")
    out = self._run(["git", "commit", "-m", message], cwd)
    if not out.success:
        return self._to_result(out, "git commit")
    out = self._run(["git", "push", "-u", "origin", name], cwd)
    if not out.success:
        return self._to_result(out, "git push")
    return (True, None)
```

Note: This also fixes bug #3 (missing `--` separator) for free.

**File: `bare_git.py`** — Remove the three dispatch methods (inherited from `GitCommon`).

**File: `../sase-github/plugin.py`** — Remove `vcs_create_commit` and `vcs_create_proposal` (inherited). Override only
`vcs_create_pull_request` to add the `gh pr create` step after the base implementation:

```python
@hookimpl
def vcs_create_pull_request(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    # Common git operations (checkout -b, add, commit, push)
    ok, err = super().vcs_create_pull_request(payload, cwd)
    if not ok:
        return (ok, err)
    # GitHub-specific: create PR
    message = payload.get("message", "")
    title = message.split("\n", 1)[0]
    pr_out = self._run(["gh", "pr", "create", "--title", title, "--body", message], cwd)
    if not pr_out.success:
        return self._to_result(pr_out, "gh pr create")
    return (True, pr_out.stdout.strip())
```

**Important**: Since `GitCommon` is a pluggy plugin mixin, the `@hookimpl` decorator in the parent and child both
register. Need to verify that pluggy's `firstresult=True` + inheritance works correctly here. If the child's `@hookimpl`
takes precedence (which it should with pluggy), this approach works. If not, GitHub's override would need to replicate
the full method and call a shared helper instead.

### Tests

- Existing tests in `test_vcs_provider_bare_git_plugin.py` should still pass (behavior unchanged)
- Existing tests in `../sase-github/tests/test_github_plugin.py` should still pass
- Verify `--` separator is present in git add commands (update assertions if needed)

### Verification

- `just check` passes in sase core
- `just check` passes in sase-github

---

## Phase 3: Remove dead code + final cleanup

**Goal**: Remove the unused standalone `main()` entry point.

**Scope**: `src/sase/workflows/commit/__init__.py`

### Implementation

**File: `src/sase/workflows/commit/__init__.py`** — Remove the `main()` function and `if __name__ == "__main__"` block.
Keep only the `CommitWorkflow` import and `__all__`. Remove unused imports (`json`, `os`, `sys`, `NoReturn`).

```python
"""Workflow for dispatching VCS commit operations."""

from .workflow import CommitWorkflow

__all__ = ["CommitWorkflow"]
```

### Verification

- `just check` passes
- Grep confirms no references to `sase.workflows.commit.main` or `sase.workflows.commit:main`

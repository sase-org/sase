---
status: done
create_time: 2026-03-30 20:40:47
prompt: sdd/prompts/202603/fix_missing_pr_creation.md
---

# Fix: `create_pull_request` silently succeeds without creating a PR

## Problem

When an agent runs with the `#pr(name=...)` embedded workflow, the commit workflow dispatches `create_pull_request` to
the VCS provider. If the `sase-github` plugin is **not installed** in the workspace's virtualenv, the `bare_git` plugin
handles the request instead. `GitCommon.vcs_create_pull_request` only performs git operations (branch, commit, push) and
returns `(True, None)` — no PR is created. The commit workflow treats this as success, writes `commit_result.json` with
`result: null`, and the agent completes without error. The user discovers the missing PR only after the fact.

**Root cause:** `CommitWorkflow.run()` checks `ok` from the VCS dispatch but does not validate that a PR URL was
actually returned for the `create_pull_request` method. The `bare_git` / `GitCommon` base class returns `(True, None)`
which passes the `ok` check.

**Observed in:** Workspace `sase_101` where `sase-github` was not installed, only `bare_git` was available as a VCS
plugin.

## Fix

### Phase 1: Validate PR URL in CommitWorkflow (main fix)

**File:** `src/sase/workflows/commit/workflow.py`

After the `dispatch()` call succeeds, add a validation check: if the method is `create_pull_request` and `result` is
falsy (None or empty string), treat it as a failure. Print a clear error message indicating that the PR was not created
and suggesting the GitHub plugin may not be installed.

This ensures the failure is surfaced immediately rather than silently written to `commit_result.json` with a null
result.

### Phase 2: Validate VCS provider at workflow start

**File:** `src/sase/workflows/commit/workflow.py`

Before performing any git operations, validate that the resolved VCS provider name matches what `create_pull_request`
expects. Specifically, if the method is `create_pull_request` and the detected VCS is `bare_git` (not `github`), fail
early with a clear error. This avoids the situation where the branch is created and pushed but no PR follows.

Implementation: call `detect_vcs(cwd)` and check the result before dispatching.

### Phase 3: Add test coverage

**File:** `tests/workflows/commit/test_workflow.py` (or nearest existing test file)

Add a unit test that verifies `CommitWorkflow.run()` returns `False` when the VCS dispatch returns `(True, None)` for
`create_pull_request`. This guards against regressions.

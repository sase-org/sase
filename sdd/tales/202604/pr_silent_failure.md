---
status: wip
create_time: 2026-04-10 13:58:43
prompt: sdd/prompts/202604/pr_silent_failure.md
---

# Fix: PR Creation Silently Skipped When Push Fails

## Problem

When an agent runs with `#pr:<name>`, the PR creation pipeline silently fails if `git push` fails (e.g., SSH agent has
no keys loaded). The user gets no structured error — the PR is simply not created.

### Root Cause Chain

1. Stop hook fires, detects uncommitted changes, instructs agent to commit via `/sase_git_commit`
2. `sase commit` creates a local commit on a new branch (e.g., `sase_fast_tui`)
3. `git push` fails (SSH keys not loaded in agent environment)
4. `CommitWorkflow.run()` returns `False` at line 160 — **before** `_write_result_marker()` at line 171
5. `commit_result.json` is never written
6. PR post-steps run: `check_changes.has_changes=false` (already committed locally), `_has_commit_result.exists=false`
7. Post-step condition `{{ check_changes.has_changes or _has_commit_result.exists }}` is false
8. `create` and `report` steps silently skipped — **no PR, no error reported**

### Key Files

- `src/sase/workflows/commit/workflow.py` — `CommitWorkflow.run()` (lines 155-171)
- `src/sase/xprompts/pr.yml` — PR post-steps with the `if` condition (lines 34-54)
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py` — `_push_with_retry()` and `vcs_create_pull_request()`

## Fix

### Phase 1: Write `commit_result.json` on failure

In `CommitWorkflow.run()`, when `dispatch()` returns `(False, error)`, write `commit_result.json` with an `error` field
before returning False. This gives the PR post-steps the information they need.

**File:** `src/sase/workflows/commit/workflow.py`

Current code (lines 155-160):

```python
ok, result = dispatch(self._payload, cwd)
if not ok:
    print_status(f"{self._method} failed: {result}", "error")
    self._cleanup_reservation()
    return False
```

Add a call to write a failure marker before returning:

```python
ok, result = dispatch(self._payload, cwd)
if not ok:
    print_status(f"{self._method} failed: {result}", "error")
    self._write_failure_marker(result)
    self._cleanup_reservation()
    return False
```

Add `_write_failure_marker()` method that writes `commit_result.json` with `"error": "<message>"` and
`"success": false`.

### Phase 2: Handle failure in PR post-steps

Update `pr.yml` so the `create` step detects the error field and reports the failure, and the `report` step outputs
`meta_pr_error` so the workflow system can surface it.

**File:** `src/sase/xprompts/pr.yml`

Changes:

1. The `_has_commit_result` step already checks for the file's existence — no change needed there
2. Update the `create` step's python to check for the `error` field and output `success=false` with the error message
3. Update the `report` step to output `meta_pr_error` when there's an error in `commit_result.json`

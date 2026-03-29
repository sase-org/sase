---
create_time: 2026-03-29 18:12:33
status: done
---
# Fix: PLAN drawer missing from COMMITS entries for coder agents

## Problem

When a coder agent implements an approved plan, the resulting ChangeSpec COMMITS entry shows `| CHAT:` and `| DIFF:` drawers but is missing the `| PLAN: <path>` drawer.

## Root Cause

The PLAN drawer depends on `SASE_PLAN` being available in the `sase commit` process's environment. The env var is set by `handle_plan_marker()` in the runner process (`run_agent_exec_plan.py:344-347`), but propagation through the subprocess chain (runner Python → Claude Code → `sase commit`) is fragile with no fallback.

A reliable file-based mechanism already exists: `plan_path.json` is written to the **planner's** artifacts directory (`_write_plan_path_artifact()` at line 180). However, it's NOT written to the **coder's** artifacts directory. The commit workflow (`_append_commits_entry()` at `workflow.py:539`) only reads the env var — it has no fallback to the artifacts file.

This contrasts with `SASE_AGENT_CHAT_PATH` and `SASE_ARTIFACTS_DIR`, which are set before the loop or at the top of each iteration and reliably propagate.

## Fix

### Phase 1: Propagate `plan_path.json` to coder artifacts directory

**File**: `src/sase/axe/run_agent_exec_plan.py`

After creating the coder's follow-up artifacts directory (the `create_followup_artifacts()` call around line 352), write `plan_path.json` there using the existing `_write_plan_path_artifact()` helper. The plan path value should match what was set in `SASE_PLAN` (either `sdd_plan_path` or `plan_data["plan_file"]`).

This mirrors the write already done for the planner step at line 180 and ensures the coder's artifacts dir has the plan path available for both the commit workflow and `_finalize_loop()`.

### Phase 2: Add `plan_path.json` fallback in commit workflow

**File**: `src/sase/workflows/commit/workflow.py`

In `_append_commits_entry()` (around line 537-544), when `SASE_PLAN` env var is empty, fall back to reading `plan_path.json` from `SASE_ARTIFACTS_DIR`. Pattern:

```python
raw_plan = os.environ.get("SASE_PLAN", "")
if not raw_plan:
    # Fallback: read from artifacts directory
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
    if artifacts_dir:
        plan_path_file = os.path.join(artifacts_dir, "plan_path.json")
        try:
            with open(plan_path_file, encoding="utf-8") as f:
                raw_plan = json.load(f).get("plan_path", "")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
```

### Phase 3: Tests

1. **Unit test for fallback**: In `tests/workflows/test_commit_workflow_artifacts.py`, add a test where `SASE_PLAN` is unset but `plan_path.json` exists in the artifacts dir — verify the PLAN drawer is added.
2. **Unit test for propagation**: Verify that `handle_plan_marker()` writes `plan_path.json` to the coder's artifacts dir (not just the planner's).

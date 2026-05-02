---
create_time: 2026-03-25 16:53:04
status: done
prompt: sdd/prompts/202603/propose_stop_hook_race.md
---

# Plan: Fix `#propose` workflow failure when commit_stop_hook pre-commits

## Problem

All 8 `pat_new_columns` agents (and `yserve_proto_updates`) failed with `PROPOSAL_ID: None EXIT_CODE: 1` despite the
Gemini agent successfully making changes, committing, and creating a proposal. The CRS workflow reports failure because
it never learns the proposal ID.

## Root Cause Analysis

The failure is caused by a **race between the `commit_stop_hook` and the `#propose` embedded workflow's post-steps**.
Here's the exact sequence:

1. CRS workflow calls `expand_embedded_workflows_in_query()`, which sets `SASE_COMMIT_METHOD=create_proposal` in
   `os.environ` (from `#propose`'s environment block)
2. CRS workflow calls `invoke_agent()` to run Gemini — the agent makes file changes
3. The `commit_stop_hook` fires, detects uncommitted changes, and injects an OVERRIDE telling the agent to commit via
   `/sase_hg_commit`
4. The agent commits via `sase commit` → `CommitWorkflow` dispatches to `vcs_create_proposal` → **proposal is created
   successfully**
5. However, `CommitWorkflow._write_result_marker()` checks `os.environ.get("SASE_ARTIFACTS_DIR")` — this is **NOT set**
   because `crs.py` only sets it at line 202, AFTER `invoke_agent()` returns → **`commit_result.json` is never written**
6. After the agent response completes, `#propose` post-steps execute:
   - `check_changes` calls `provider.has_local_changes()` → **no changes** (agent already committed)
   - `propose` step has `if: "{{ check_changes.has_changes }}"` → **SKIPPED**
   - `report` step has same guard → **SKIPPED**
7. `proposal_id` stays `None` → `exit_code = 0 if proposal_id else 1` → **FAILED**

**Two bugs compound to cause this:**

- **Bug 1 (env var timing)**: `SASE_ARTIFACTS_DIR` is not set in `os.environ` before `invoke_agent()`, so
  `commit_result.json` is never written when the stop hook causes an early commit
- **Bug 2 (guard condition)**: The `propose` step's `if` guard only checks `check_changes.has_changes`, so it's skipped
  when the stop hook already committed — even if `commit_result.json` existed

## Fix

### File 1: `src/sase/workflows/crs.py`

Move `os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir` to BEFORE the `invoke_agent()` call (currently at line 202,
should be around line 175). This ensures the Gemini subprocess (and anything it triggers, like `sase commit`) can write
`commit_result.json` to the artifacts directory.

The `SASE_COMMIT_METHOD` line can stay where it is (already set by `expand_embedded_workflows_in_query` from the
`#propose` environment block, but the explicit set is a harmless safety net for post-steps).

**Before:**

```python
expanded_prompt, post_workflows = expand_embedded_workflows_in_query(...)

# Call Gemini
response = invoke_agent(...)
...

# Inject environment variables that embedded workflow post-steps need.
os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir
os.environ["SASE_COMMIT_METHOD"] = "create_proposal"

# Execute post-steps
```

**After:**

```python
expanded_prompt, post_workflows = expand_embedded_workflows_in_query(...)

# Set SASE_ARTIFACTS_DIR before invoking the agent so that the
# commit_stop_hook path (agent commits during response) can write
# commit_result.json to the correct location.
os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir

# Call Gemini
response = invoke_agent(...)
...

# Inject remaining environment variables for post-steps.
os.environ["SASE_COMMIT_METHOD"] = "create_proposal"

# Execute post-steps
```

### File 2: `src/sase/axe/fix_hook_runner.py`

Same pattern — move `os.environ["SASE_ARTIFACTS_DIR"]` to before `invoke_agent()` (currently at line 186).

### File 3: `src/sase/xprompts/propose.yml`

Add a new hidden step `_has_commit_result` that checks for `commit_result.json` existence, and update the `if`
conditions on `propose` and `report` to also trigger when the commit result file exists.

**Before:**

```yaml
  - name: check_changes
    use: shared/check_changes

  - name: propose
    hidden: true
    if: "{{ check_changes.has_changes }}"
    ...

  - name: report
    hidden: true
    if: "{{ check_changes.has_changes }}"
    ...
```

**After:**

```yaml
  - name: check_changes
    use: shared/check_changes

  - name: _has_commit_result
    hidden: true
    python: |
      import os
      artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
      path = os.path.join(artifacts_dir, "commit_result.json") if artifacts_dir else ""
      print(f"exists={'true' if path and os.path.isfile(path) else 'false'}")
    output: { exists: bool }

  - name: propose
    hidden: true
    if: "{{ check_changes.has_changes or _has_commit_result.exists }}"
    ...

  - name: report
    hidden: true
    if: "{{ check_changes.has_changes or _has_commit_result.exists }}"
    ...
```

## Testing

1. `just check` — ensure lint/mypy/tests pass
2. Verify `propose.yml` parses correctly by running a dry workflow expansion (e.g., `sase ace --agent` or similar)
3. Manually verify with a CRS workflow that commits via the stop hook path — `commit_result.json` should now be written
   and the `propose` step should execute and extract the proposal ID

---
status: wip
create_time: 2026-03-26 19:18:31
prompt: sdd/prompts/202603/commit_diff_drawer.md
---

# Plan: Fix missing DIFF drawer for commits created via `#commit` workflow

## Root Cause

When `#commit` is embedded in an agent xprompt, the execution timeline is:

1. Agent prompt step runs (agent makes code changes).
2. **Stop hook** (`sase_commit_stop_hook`) detects uncommitted changes and blocks the agent.
3. Stop hook tells the agent to use the commit skill (e.g. `/sase_hg_commit`).
4. Agent runs the commit skill, which calls `CommitWorkflow.run()`.
5. `CommitWorkflow.run()` dispatches `create_commit` to the VCS provider, **creating the VCS commit**.
6. `CommitWorkflow._write_result_marker()` writes `commit_result.json` — but with **no `diff_path` field**.
7. Agent successfully stops; prompt step completes.
8. Workflow executor calls `capture_vcs_diff()` — returns `None` because the working directory is now **clean** (changes
   already committed in step 5).
9. Prompt step marker is saved with `diff_path=None`.
10. Embedded `#commit` post-steps run:
    - `_append_entry` calls `append_post_commit_entry(mode="commit")`.
    - `_find_best_diff_path()` scans markers — finds no `diff_path`.
    - Fallback checks `commit_result["result"]` for a `.diff` extension — it's a commit hash, not a path.
    - **Result: commit entry appended without a DIFF drawer.**

The initial commit (commit 1) works because it goes through `create_changespec_for_workflow()` which explicitly calls
`_save_committed_diff()` to generate a diff from VCS history and passes it directly to the ChangeSpec creation.

## Fix

Capture the uncommitted diff inside `CommitWorkflow` **before** `dispatch()` creates the commit, save it to
`~/.sase/diffs/`, and include the path in `commit_result.json` so `append_post_commit_entry` can use it.

### Step 1: Capture and save the diff in `CommitWorkflow.run()` before dispatch

**File:** `src/sase/workflows/commit/workflow.py`

Add a new method `_capture_pre_commit_diff()` that:

- Only runs for `create_commit` (not `create_pull_request`, which has its own diff via `_save_committed_diff`).
- Uses the VCS provider's `diff_with_untracked()` to capture uncommitted changes.
- Saves the diff to `~/.sase/diffs/{safe_cl_name}-{timestamp}.diff` using existing utility functions
  (`ensure_sase_directory`, `make_safe_filename`, `generate_timestamp`, `shorten_path`).
- Derives the CL name from `SASE_AGENT_CL_NAME` env var (with fallback to payload `name`).
- Stores the path in `self._diff_path`.

Call this method in `run()` right before the `dispatch()` call (after `_run_precommit`, `_handle_beads`, etc. but before
the VCS commit is created).

### Step 2: Include `diff_path` in `commit_result.json`

**File:** `src/sase/workflows/commit/workflow.py`

In `_write_result_marker()`, add `"diff_path": self._diff_path` to the marker dict.

### Step 3: Read `diff_path` from `commit_result.json` in `append_post_commit_entry`

**File:** `src/sase/workflows/commit_utils/post_commit.py`

In `append_post_commit_entry()`, after `_find_best_diff_path()` returns `None`, add a check for
`commit_result.get("diff_path")` **before** the existing `.diff` extension fallback. This is the primary fix — it lets
the post-commit entry finder use the diff that `CommitWorkflow` captured before committing.

## Testing

- Run `just check` to verify no regressions.
- Add a unit test for `_capture_pre_commit_diff` in the commit workflow tests.

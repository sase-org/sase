---
status: done
create_time: 2026-03-27 14:46:43
prompt: sdd/prompts/202603/fix_commits_entry_human_cli.md
---

# Plan: Fix COMMITS entry creation for human `sase commit` invocations

## Problem

When a human runs `sase commit --method create_commit --note "[man] Revert BUILD changes"` from the CLI, no COMMITS
entry is added to the ChangeSpec. The command reports success but the spec file is unchanged.

## Root Cause

`CommitWorkflow._append_commits_entry()` delegates to `append_post_commit_entry()` which requires three environment
variables that are **only set in agent contexts**:

1. `SASE_ARTIFACTS_DIR` — set by `run_agent_exec.py`, `fix_hook_runner.py`, `crs_runner.py`
2. `SASE_AGENT_PROJECT_FILE` — set by `agent/launcher.py`, `axe/fix_hook_runner.py`, `axe/crs_runner.py`
3. `SASE_AGENT_CL_NAME` — set by the same agent launchers

When any of these are missing, `append_post_commit_entry()` returns `PostCommitResult(success=False)` immediately
(post_commit.py:42). A human CLI invocation never has these env vars.

Additionally, `_capture_pre_commit_diff()` requires `SASE_ARTIFACTS_DIR` to save the diff file, so the diff is also lost
for human commits.

## History

Recurring issue across commits a8fb1ee → d32aeac → 4b61434. The latest commit (4b61434) unified COMMITS entry creation
inside CommitWorkflow (correct architecture) but didn't remove the env var dependency.

## Design Principle

ALL commit/proposal/pr logic lives in `sase commit` (CommitWorkflow). The xprompt workflows contain bare-minimum logic —
just enough to read `commit_result.json` and emit `meta_*` output variables.

## Phase 1: Make `_append_commits_entry` self-sufficient

**File: `src/sase/workflows/commit/workflow.py`**

Replace the current delegation to `append_post_commit_entry()` with direct calls to `add_commit_entry_with_id()` /
`add_proposed_commit_entry()`, resolving all parameters from workflow state:

- **project_file**: `SASE_AGENT_PROJECT_FILE` env var → `get_project_from_workspace()` + `get_project_file_path()`
- **cl_name**: `SASE_AGENT_CL_NAME` env var → `get_cl_name_from_branch()`
- **note**: `self._payload.get("note")` → first line of `self._payload.get("message", "")` → `"Manual changes"`
- **diff_path**: `self._diff_path` (already captured pre-commit)
- **chat_path**: `SASE_AGENT_CHAT_PATH` env var (None for human CLI — that's fine)

This eliminates the dependency on `SASE_ARTIFACTS_DIR` and `commit_result.json` for COMMITS entries.

## Phase 2: Fix `_capture_pre_commit_diff` for non-agent contexts

**File: `src/sase/workflows/commit/workflow.py`**

Currently requires `SASE_ARTIFACTS_DIR`. When not set, save the diff to `~/.sase/diffs/<cl_name>-<timestamp>.diff`
instead (the same location used by other sase diff operations). This gives human commits DIFF lines too.

Need to detect `cl_name` early for the filename — reuse the same detection logic from Phase 1 (extract into a helper
method `_resolve_cl_name()` and `_resolve_project_file()` that are called once in `run()` and cached on `self`).

## Phase 3: No changes to `_write_result_marker`

It's only needed for xprompt post-steps. Already guards on `SASE_ARTIFACTS_DIR`. In human CLI it's a no-op — correct.

## Phase 4: Verify xprompt minimality

**Files: `src/sase/xprompts/commit.yml`, `propose.yml`, `pr.yml`**

After 4b61434, these already contain minimal logic (read `commit_result.json`, emit `meta_*` vars). No changes needed
unless we find something. Just verify.

## Phase 5: Update tests

**File: `tests/workflows/test_post_commit.py`**

- Keep existing tests (it's still callable for backward compat)

**File: `tests/workflows/test_commit_workflow.py`**

- Add test for `_append_commits_entry()` when env vars are NOT set (human CLI path)
- Verify note from `--note` is used as entry text
- Verify diff is captured to `~/.sase/diffs/` fallback path

## Files Changed

1. `src/sase/workflows/commit/workflow.py` — main fix
2. `tests/workflows/test_commit_workflow.py` — new tests for human CLI path

---
create_time: 2026-03-30 16:22:55
status: done
---

# Fix: Test env var leaks cause bogus COMMITS entries in real ChangeSpec files

## Problem

When `just test` runs inside a sase agent context, three tests write bogus COMMITS entries to the real ChangeSpec file.
The entries are:

- (2) test — from `test_no_changespec_for_create_commit` in `test_commit_workflow_changespec.py`
- (3) fix: bug — from `test_dispatches_create_commit` in `test_commit_workflow_dispatch.py`
- (3a) propose: new feature — from `test_dispatches_create_proposal` in `test_commit_workflow_dispatch.py`

## Root Cause Chain

1. **Agent launcher sets env vars**: `SASE_AGENT_CL_NAME` and `SASE_AGENT_PROJECT_FILE` are set by
   `src/sase/agent/launcher.py:79-80` in the agent subprocess environment, pointing to the real CL name and project
   file.

2. **Env var leak from retry tests**: `tests/test_axe_run_agent_runner_retry.py` calls `run_agent_runner.main()`
   in-process via `_run_main()`. Inside `main()`, `run_execution_loop()` at `src/sase/axe/run_agent_exec.py:258` sets
   `os.environ["SASE_AGENT_CHAT_PATH"] = predicted_chat_path`. Because `get_chat_file_path` is patched to return
   `/tmp/test_chat.md`, the env var is set to `/tmp/test_chat.md`. This env var is NOT cleaned up after the test — the
   `patch.start()`/`patch.stop()` only restore the patched functions, not env var side effects.

3. **Commit workflow tests lack env var isolation**: The `_no_precommit` autouse fixture in both
   `test_commit_workflow_dispatch.py` and `test_commit_workflow_changespec.py` only patches `precommit_command` and
   `SASE_PLAN`. It does NOT clear `SASE_AGENT_CL_NAME`, `SASE_AGENT_PROJECT_FILE`, or `SASE_AGENT_CHAT_PATH`.

4. **Env vars bypass mocks**: `CommitWorkflow._resolve_cl_name()` (workflow.py:474) and `_resolve_project_file()`
   (workflow.py:486) check env vars FIRST, before calling any importable function. Even when tests patch
   `get_project_from_workspace` to return `None`, the env var takes precedence and returns the real project file.

5. **Result**: Three tests call `CommitWorkflow.run()` -> provider succeeds (mocked) -> `_append_commits_entry()` ->
   resolves real CL name + project file from env vars -> writes bogus entries to the real ChangeSpec with
   `CHAT: /tmp/test_chat.md`.

## Fix Plan

### Step 1: Add global autouse conftest fixture to clear agent env vars

**File**: `tests/conftest.py`

Add an `autouse=True` fixture that clears all `SASE_AGENT_*` env vars (plus `SASE_ARTIFACTS_DIR`) before each test. This
is the most robust defense — it prevents ALL tests from accidentally inheriting or leaking agent env vars, regardless of
individual test isolation.

Using `monkeypatch` ensures automatic restore after each test, so tests that explicitly set these vars (like
`test_post_commit.py`) still work correctly.

### Step 2: Fix env var leak in retry test helper

**File**: `tests/test_axe_run_agent_runner_retry.py`

Update `_run_main()` to snapshot and restore `os.environ` after calling `main()`, so that any env var mutations inside
`main()` (like `SASE_AGENT_CHAT_PATH`, `SASE_ARTIFACTS_DIR`, `SASE_AGENT_AUTO_APPROVE`) don't leak to subsequent tests.

### Step 3: Remove now-redundant per-file autouse fixture patches

The `_no_precommit` fixture in `test_commit_workflow_dispatch.py` and `test_commit_workflow_changespec.py` patches
`SASE_PLAN` via `patch.dict`. Since Step 1's conftest fixture already clears agent env vars, and `SASE_PLAN` isn't an
agent env var, the existing `_no_precommit` fixture can stay as-is (it still serves its purpose of disabling the
precommit command). No changes needed to these files.

## Files Changed

| File                                       | Change                                         |
| ------------------------------------------ | ---------------------------------------------- |
| `tests/conftest.py`                        | Add `_clear_agent_env_vars` autouse fixture    |
| `tests/test_axe_run_agent_runner_retry.py` | Snapshot/restore `os.environ` in `_run_main()` |

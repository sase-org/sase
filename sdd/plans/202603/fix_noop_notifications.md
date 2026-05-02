---
create_time: 2026-03-26 22:10:17
status: done
prompt: sdd/prompts/202603/fix_noop_notifications.md
---

# Fix: Suppress notifications for noop workflow runs

## Problem

When `#sase/fix_just` runs and both `just lint` and `just test` succeed, the two agent steps (`fix_linters`,
`fix_tests`) are skipped (their `if:` conditions are false). Only the hidden bash steps actually execute. Despite commit
`7a52c83` updating `all_steps_hidden()` to treat skipped steps as hidden, notifications are **still** generated.

## Root Cause Analysis

The notification gate in `run_agent_runner.py:380` is:

```python
if not was_killed() and not all_steps_hidden(current_artifacts_dir):
    notify_workflow_complete(...)
```

`all_steps_hidden()` reads `workflow_state.json` from `current_artifacts_dir`. The logic itself is correct for a
properly-written state file. The issue is one of two things:

### Hypothesis A: `_flatten_anonymous_workflow` fails due to project mismatch

The prompt `#gh:sase #sase/fix_just` flows through:

1. `run_agent_runner.py:143` - `process_xprompt_references()` uses `get_all_xprompts()` which does NOT include workflows
   (`.yml` files). Both `#gh` and `#sase/fix_just` are workflows, so neither is expanded. The prompt stays unchanged.

2. `run_agent_exec.py:205` - `create_anonymous_workflow(prompt)` wraps the prompt in a single `agent` step.

3. `workflow_runner.py:388-394` - `_flatten_anonymous_workflow()` attempts to detect the standalone workflow
   (`#sase/fix_just`) and replace the anonymous wrapper with it.

4. Inside `_flatten_anonymous_workflow`, `get_all_prompts(project=None)` is called. The `project` parameter is always
   `None` here (not passed by `execute_workflow` from `run_agent_exec.py`). Project auto-detection uses
   `detect_project()` which calls `get_workspace_name(os.getcwd())`. **If the CWD is an ephemeral workspace like
   `sase_3`, the detected project name may differ from `"sase"`**, causing `fix_just.yml` to be namespaced as e.g.
   `"sase_101/fix_just"` instead of `"sase/fix_just"`.

   When the key doesn't match, `_find_standalone_workflow_ref()` won't find `"sase/fix_just"` in the prompts dict.
   Flattening returns `None`.

5. Without flattening, the anonymous workflow's single `main` agent step runs. Claude is invoked with the raw prompt
   (which still contains `#gh:sase #sase/fix_just` as text). Claude produces an empty or near-empty response.

6. `workflow_state.json` has one step: `{"name": "main", "status": "completed", "hidden": false}`. `all_steps_hidden()`
   returns `False`. Notification fires.

### Hypothesis B: Flattening succeeds but `all_steps_hidden` is called on wrong dir

If flattening does succeed and the fix_just workflow executes directly (producing the correct 4-step
`workflow_state.json`), the notification would be suppressed. Unless `current_artifacts_dir` in `run_agent_runner.py`
doesn't match where the workflow executor wrote `workflow_state.json`. This is less likely given the sequential code
flow, but should be verified.

## Investigation Plan

### Phase 1: Confirm the root cause with diagnostics

1. **Add debug logging to `all_steps_hidden()`** (`runner_utils.py:100-120`):
   - Log the `state_path` being read
   - Log the steps found (name, status, hidden)
   - Log the return value
   - This will immediately tell us whether the file is missing, has unexpected content, or is correct

2. **Add debug logging to `_flatten_anonymous_workflow()`** (`workflow_runner.py:128-225`):
   - Log the prompt_text being analyzed
   - Log whether fast path or slow path is taken
   - Log the `prompts` dict keys (or at least whether `"sase/fix_just"` is in it)
   - Log whether flattening succeeded or returned None

3. **Trigger a test run**: Execute `#gh:sase #sase/fix_just` when lint/test pass and check the debug output.

### Phase 2: Fix based on findings

**If Hypothesis A is confirmed** (flattening fails due to name mismatch):

The fix should be in `run_agent_exec.py` where `execute_workflow()` is called. Pass the `project` parameter so that
`_flatten_anonymous_workflow` uses the correct project name for workflow resolution:

```python
# run_agent_exec.py, around line 210
result = execute_workflow(
    anon_workflow.name,
    [],
    {"cl_name": ctx.cl_name, "workspace_num": ctx.workspace_num},
    artifacts_dir=current_artifacts_dir,
    silent=True,
    workflow_obj=anon_workflow,
    project=ctx.project_name,  # NEW: pass project for correct namespacing
)
```

OR, the fix could be in `_flatten_anonymous_workflow` to do a fuzzy match on workflow names (matching by base name when
exact match fails).

**If Hypothesis B is confirmed** (artifacts_dir mismatch):

Trace the exact `artifacts_dir` values through the call chain and ensure consistency.

**Alternative/complementary fix**: Regardless of root cause, `all_steps_hidden()` currently returns `False` when
`workflow_state.json` is missing. For the noop case where `is_workflow_noop()` already detected zero agents launched,
the notification could be suppressed directly:

```python
# run_agent_runner.py, around line 380
if not was_killed() and not all_steps_hidden(current_artifacts_dir):
    ...
```

Could become:

```python
noop = is_workflow_noop(current_artifacts_dir)
if not was_killed() and not noop and not all_steps_hidden(current_artifacts_dir):
    ...
```

But note: `is_workflow_noop()` is in `run_agent_helpers.py` and is currently only called from `run_agent_exec.py`. It
also reads `workflow_state.json`, so if the file is missing, it returns `False` too. This would only help if
`workflow_state.json` exists but `all_steps_hidden()` has a logic gap.

### Phase 3: Test and clean up

1. Remove debug logging
2. Run `just lint && just test` to verify
3. Manually test: run `#sase/fix_just` when lint/test pass → verify no notification
4. Manually test: run `#sase/fix_just` when lint/test fail → verify notification still fires

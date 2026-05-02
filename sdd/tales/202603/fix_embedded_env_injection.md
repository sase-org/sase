---
status: done
create_time: 2026-03-24 16:20:24
prompt: sdd/prompts/202603/fix_embedded_env_injection.md
---

# Fix missing environment injection for embedded commit/propose/pr xprompt workflows

## Problem

The unified `#commit`, `#propose`, and `#pr` xprompt workflows define an `environment:` block that sets
`SASE_COMMIT_METHOD` (and `SASE_BUG_ID` for `#pr`). However, when these workflows are used as **embedded workflows**
(i.e., referenced in a prompt like `sase run "#commit Fix a bug"`), their `environment:` block is never injected into
`os.environ`.

### Root cause

There are **two** code paths that expand embedded workflows:

1. **`WorkflowExecutor._expand_embedded_workflows_in_prompt()`** (in `workflow_executor_steps_embedded.py`) — used by
   the full workflow executor (TUI, `sase run`, axe runner).
2. **`expand_embedded_workflows_in_query()`** (in `_query.py`) — used by standalone callers (CRS, mentor, fix_hook).

Both paths read `p.workflow.environment.get("SASE_COMMIT_METHOD")` for **content selection** (appending VCS-specific
tagged prompt parts), but **neither injects the environment variables into `os.environ`**.

The only place `_inject_environment()` is called is in `WorkflowExecutor.execute()` for the **top-level** workflow. But
when `#commit` is embedded, the top-level workflow is the anonymous wrapper (which has no `environment:` block).

### Consequence

1. `SASE_COMMIT_METHOD` is never set in `os.environ`
2. The `sase_commit_stop_hook` (Claude Code stop hook) checks `$SASE_COMMIT_METHOD` and exits immediately when empty
3. The agent is never instructed to commit
4. `commit_result.json` is never written
5. The `report` post-step finds no marker file and produces empty output

### Evidence from E2E test

- Ran `sase run -d '%model:sonnet #commit Add a comment...'`
- Agent completed, made file changes, but no commit occurred
- `prompt_step_commit__report.json` shows `"output": {}` (empty — no `commit_result.json` found)
- No `commit_result.json` in artifacts directory

## Fix

### Part A: Inject embedded workflow environment in `_expand_embedded_workflows_in_prompt()`

**File:** `src/sase/xprompt/workflow_executor_steps_embedded.py`

In Phase 3 (pre-step execution), after executing pre-steps and before rendering prompt_part, inject the embedded
workflow's `environment:` variables into `os.environ`:

```python
# After pre-step execution (around line 497), add:
# Inject embedded workflow environment variables
if p.workflow.environment:
    for key, value_template in p.workflow.environment.items():
        rendered = render_template(value_template, p.embedded_context)
        os.environ[key] = rendered
```

This ensures `SASE_COMMIT_METHOD` (and `SASE_BUG_ID` for `#pr`) are set before the agent is invoked, making them visible
to:

- The Claude Code stop hook (`sase_commit_stop_hook`)
- The `sase commit` command (which reads `$SASE_COMMIT_METHOD` as fallback)
- Any post-steps that depend on these env vars

### Part B: Inject embedded workflow environment in `expand_embedded_workflows_in_query()`

**File:** `src/sase/main/query_handler/_query.py`

Apply the same fix in the standalone expansion function. After pre-step execution (around line 211), add the same
environment injection logic.

### Part C: Add tests

**File:** `tests/test_embedded_env_injection.py` (new)

1. **`test_embedded_workflow_injects_environment`** — Create a workflow with `environment: {FOO: bar}` and a
   `prompt_part` step, embed it in a prompt, verify `os.environ["FOO"]` is set after expansion.
2. **`test_commit_workflow_sets_commit_method`** — Load the real `commit.yml` workflow, embed `#commit` in a prompt,
   verify `os.environ["SASE_COMMIT_METHOD"] == "create_commit"` after expansion.
3. **`test_pr_workflow_sets_bug_id`** — Load the real `pr.yml` workflow, embed `#pr(my-branch, 42)` in a prompt, verify
   `os.environ["SASE_BUG_ID"] == "42"` after expansion.
4. **Same tests for `expand_embedded_workflows_in_query()`** (the standalone path).

### Part D: Validation

1. Run `just check` to verify all tests pass and linting is clean.
2. Run a quick manual E2E test with `sase run -d '%model:sonnet #commit ...'` to verify the fix works end-to-end
   (optional — the unit tests are the primary validation).

### Part E: Commit

Use `ccommit` to commit changes in each repo after validation passes.

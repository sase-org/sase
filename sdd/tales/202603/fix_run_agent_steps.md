---
create_time: 2026-03-29 17:08:04
status: done
prompt: sdd/prompts/202603/fix_run_agent_steps.md
---

# Fix: `sase run` agents show no workflow steps in TUI

## Problem

When `sase run` launches an agent, the TUI initially shows it as `[agent] sase (RUNNING)` with no step count, while
other agents launched the same way display e.g. `(4 steps)`. The detail panel shows "Workflow: run" instead of the
actual workflow name.

## Root Cause

There's a timing gap between the RUNNING field claim (written immediately to the project file) and the
`workflow_state.json` creation (written later when `WorkflowExecutor.execute()` runs).

During this gap — which spans workspace preparation, xprompt loading/expansion, directive extraction, and dependency
waiting — the TUI loads the RUNNING field entry as `AgentType.RUNNING`. Since no matching `workflow_state.json` exists,
the dedup pipeline (`dedup_running_vs_workflow`) can't merge it with a WORKFLOW entry. Result:

- Agent shows as `AgentType.RUNNING` with `workflow="ace(run)"` → "Workflow: run"
- No step children (only WORKFLOW parents can have fold-counted steps)
- No "(N steps)" annotation

`run_workflow_runner.py` already handles this correctly by writing an initial `workflow_state.json` immediately after
creating the artifacts directory (line 117-119). The `run_agent_runner.py` code path does not.

The same gap also exists for **follow-up agents** (`.code`, `.epic`) created by `create_followup_artifacts()` in
`run_agent_helpers.py` — they create a new artifacts directory but don't write an initial workflow state either.

## Fix

### 1. Write initial `workflow_state.json` in `run_agent_runner.py`

After creating the artifacts directory (line 120), write an initial `workflow_state.json` with:

- `workflow_name`: `"run"` (temporary — overwritten by `WorkflowExecutor._save_state()`)
- `status`: `"running"`
- `cl_name`: from args
- `pid`: `os.getpid()`
- `appears_as_agent`: `True` (so it displays as `[agent]`)

Use the existing `_write_workflow_state` helper from `run_workflow_runner.py` — either import it or inline an equivalent
call. Since `run_agent_runner.py` already imports from sibling modules and the helper is simple, inlining a minimal JSON
write is cleaner than adding a cross-module import.

### 2. Write initial `workflow_state.json` in `create_followup_artifacts()`

Same treatment for follow-up agents. After creating the new artifacts directory and writing `agent_meta.json`, also
write an initial `workflow_state.json` so follow-up agents are immediately visible as WORKFLOW entries with step
tracking.

## Files to modify

- `src/sase/axe/run_agent_runner.py` — add initial `workflow_state.json` write after `create_artifacts_directory()`
  (around line 120)
- `src/sase/axe/run_agent_helpers.py` — add initial `workflow_state.json` write in `create_followup_artifacts()` after
  writing `agent_meta.json`

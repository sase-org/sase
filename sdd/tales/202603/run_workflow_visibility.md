---
create_time: 2026-03-29 17:29:36
status: done
---

# Fix `sase run` workflow visibility and step rendering in TUI

## Problem Summary

The prior fix addressed `ace-run` background runner paths (`run_agent_runner.py` and follow-up artifacts), but users
still see plain RUNNING entries like `Workflow: run` with no step count.

The remaining gap is the synchronous `sase run` path (`src/sase/main/query_handler/_query.py`), which:

- claims RUNNING workspace entries with workflow `run`
- writes workflow state under `~/.sase/projects/<project>/artifacts/run/<timestamp>/workflow_state.json`

Current TUI workflow loaders only scan `workflow-*` and `ace-run`, so `run` workflow states are invisible while the
agent is running.

## Root Cause

1. `load_workflow_states()` / `load_workflow_agent_steps()` never traverse `artifacts/run/*`, so no WORKFLOW entry
   exists to merge with RUNNING `run` claims.
2. `dedup_running_vs_workflow()` only merges RUNNING entries for `ace(run)` / `ace-run`, not plain `run`.
3. The synchronous run path also has a pre-execution timing window between RUNNING claim and first
   `WorkflowExecutor._save_state()` write, which can still briefly show a raw RUNNING entry.

## Implementation Plan

1. Extend workflow timestamp directory discovery to include `artifacts/run/*`.
   - Update `_iter_workflow_timestamp_dirs()` in `src/sase/ace/tui/models/_loaders/_workflow_loaders.py` to scan `run`
     alongside `workflow-*` and `ace-run`.
   - Keep behavior stable for existing workflow directories.

2. Extend RUNNING↔WORKFLOW dedup matching for `run` agents.
   - Update `dedup_running_vs_workflow()` in `src/sase/ace/tui/models/_dedup.py` so plain RUNNING workflow `run` can
     merge into WORKFLOW entries by timestamp.
   - Preserve existing merge precedence and metadata propagation.

3. Close the synchronous `sase run` timing gap.
   - In `src/sase/main/query_handler/_query.py`, write an initial `workflow_state.json` in the
     `artifacts/run/<timestamp>` directory immediately after artifacts creation and before claim/execute.
   - Include `status=running`, `appears_as_agent=True`, pid, context/cl_name, and empty step list; allow
     `WorkflowExecutor` to overwrite with canonical workflow name and step graph.

4. Add focused regression tests.
   - Add/extend tests to validate:
     - workflow loaders include `run` directories
     - dedup merges RUNNING `run` with WORKFLOW entries (same timestamp)
     - synchronous run path writes initial state before execution begins

5. Verify quality gates.
   - Run `just install` (workspace freshness requirement) then `just check`.
   - Ensure lint/type/test coverage remains green.

## Success Criteria

- Running synchronous `sase run` agents appear as WORKFLOW-backed agent entries in TUI during execution.
- The entry no longer remains stuck as plain RUNNING `Workflow: run` due to missing workflow-state discovery.
- Step tracking/count and prompt panel workflow data are available as soon as state exists.

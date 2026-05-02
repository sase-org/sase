---
create_time: 2026-03-29 15:07:29
status: done
prompt: sdd/prompts/202603/fix_planning_status.md
---

# Plan: Fix parent workflow showing PLANNING when child step is RUNNING

## Problem

In the sase ace TUI, a parent workflow agent displays "PLANNING" even when one of its child workflow steps is still
actively RUNNING. The user expects the parent to show "RUNNING" whenever any child step is in progress — "PLANNING"
should only appear when the workflow is genuinely idle and waiting for user plan approval.

## Root Cause

The status override chain has a gap for workflow step children:

1. **`_workflow_loaders.py:113-122`** — Parent workflow correctly gets `RUNNING` from `workflow_state.json` (a child
   step is in progress).
2. **`_artifact_loaders.py:123-128`** — `enrich_agent_from_meta()` overrides `RUNNING → PLANNING` because
   `agent_meta.json` has `plan=true` and `plan_approved` is not set. This override is too aggressive — it fires even
   when the workflow still has running child steps.
3. **`agent_loader.py:186-189`** — `_apply_status_overrides()` already fixes `PLANNING → RUNNING` for active
   non-workflow feedback children, but explicitly excludes workflow step children via `not agent.parent_workflow`. So
   workflow parents stay stuck at "PLANNING".

## Fix

Add a new check in `_apply_status_overrides()` for workflow step children, mirroring the existing feedback round
pattern.

### Changes

**`src/sase/ace/tui/models/agent_loader.py` — `_apply_status_overrides()`**:

After the existing feedback round loop (around line 189), add a loop over workflow step children:

- For each agent where `agent.parent_workflow` is set and `agent.parent_timestamp` matches a parent in
  `parent_by_suffix`
- If the child's status is active (not in `completed_statuses`) and the parent's status is `"PLANNING"`
- Override the parent's status to `"RUNNING"`

This is a single targeted addition (~6 lines) that follows the exact same pattern already used for feedback rounds.

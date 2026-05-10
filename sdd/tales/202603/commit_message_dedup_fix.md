---
create_time: 2026-03-31 21:30:40
status: done
prompt: sdd/prompts/202603/commit_message_dedup_fix.md
---

# Fix: Missing "Commit message:" output variable in agent metadata panel

## Problem

The "Commit message:" xprompt workflow output variable is not showing in the agent metadata panel on the Agents tab.
This affects agents that commit via the stop hook (e.g., on machines using the retired Mercurial plugin plugin with bare git VCS).

## Root Cause

The issue is in the dedup layer in `src/sase/ace/tui/models/_dedup.py`, specifically `dedup_running_vs_workflow()` (line
296).

**Data flow:**

1. `load_done_agents` loads from `done.json` — creates a RUNNING-type agent with `step_output` that includes
   `meta_commit_message` (because `_finalize_loop` calls `extract_step_output_and_diff_path`, which reads
   `commit_result.json` as a fallback).
2. `load_workflow_agents` loads from `workflow_state.json` — creates a WORKFLOW-type agent with `step_output` that only
   has `{meta_workspace: "101"}` (because `workflow_state.json` is finalized BEFORE the commit stop hook runs and
   creates `commit_result.json`).
3. `dedup_running_vs_workflow` matches these two agents by `raw_suffix` and **prefers the WORKFLOW agent**. The merge
   code at line 296:
   ```python
   if matched.step_output is None and agent.step_output is not None:
       matched.step_output = agent.step_output
   ```
   Since the WORKFLOW agent's `step_output` is NOT None (it has `{meta_workspace: "101"}`), the done.json's richer
   `step_output` (with `meta_commit_message` and `meta_new_commit`) is **silently discarded**.
4. Later, `_apply_status_overrides` tries to propagate `meta_*` fields from the child (@a.2 code role) to parent (@a.1
   plan role), but the child also lost its `meta_commit_message` through the same dedup logic.

**Result:** The WORKFLOW agent used by the TUI never gets `meta_commit_message`, so `extract_meta_fields()` returns
nothing displayable.

## Fix

Modify `dedup_running_vs_workflow` to **merge** `step_output` fields from the RUNNING agent (done.json) into the
WORKFLOW agent's existing `step_output`, rather than only replacing when None. This ensures that enriched fields added
by `extract_step_output_and_diff_path` (from `commit_result.json`) survive the dedup.

### File to change

- `src/sase/ace/tui/models/_dedup.py` — `dedup_running_vs_workflow`, line 296: Replace the all-or-nothing `step_output`
  assignment with a merge that adds missing keys from the done.json agent into the workflow agent.

### Verification

- `just check` passes.
- Confirm that `meta_commit_message` and `meta_new_commit` survive the dedup pipeline when both `workflow_state.json`
  and `done.json` exist for the same agent.

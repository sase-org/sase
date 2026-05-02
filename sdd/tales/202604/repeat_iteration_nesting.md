---
create_time: 2026-04-14 22:03:43
status: done
prompt: sdd/prompts/202604/repeat_iteration_nesting.md
---

# Show All Repeat Iterations as Nested Entries on Agents Tab

## Problem Statement

When using the `%repeat:N` directive (e.g., `%r5`), all N iterations run sequentially within the same runner process,
sharing one PID and one artifacts directory. The TUI only displays a single agent entry with a `↻N/N` annotation. After
completion, the only visible trace is the final iteration's state. The user expects each iteration to appear as its own
entry, nested under the parent — similar to how workflow steps nest under their workflow parent.

## Diagnosis Summary

The root cause is architectural: each repeat iteration runs through `run_execution_loop()` inside the same runner loop
(`run_agent_runner.py:352-384`), but no per-iteration artifacts are persisted. After each iteration:

- The runner overwrites local variables (`saved_path`, `diff_path`, `current_artifacts_dir`, `step_output`) with the
  latest result — previous iterations' data is lost.
- `repeat_state.json` is a live progress file that gets deleted after the loop finishes.
- The TUI loads a single Agent from the one RUNNING field claim and enriches it with `repeat_count`/`repeat_iteration`
  from `agent_meta.json` — but there's nothing to load per-iteration data from.

Meanwhile, workflow steps work because each step writes a `prompt_step_*.json` marker file, which the workflow step
loader reads to create child Agent entries with `parent_timestamp` linking them to their parent.

## Goals

1. Each repeat iteration appears as a distinct nested child entry on the Agents tab (like workflow steps).
2. The parent agent entry remains as the top-level row, with children foldable via the existing fold mechanism.
3. Each child shows its iteration number (e.g., `1/5`, `2/5`), status (DONE/FAILED/RUNNING), and has accessible
   response/diff paths for navigation.
4. While running, the currently-executing iteration should show as RUNNING and completed ones as DONE.
5. After all iterations complete, all children remain visible (not just the last one).

## Proposed Changes

### 1. Write per-iteration marker files in the runner

**File:** `src/sase/axe/run_agent_runner.py`

After each iteration's `run_execution_loop()` returns, write a `repeat_iter_N.json` marker file to the shared artifacts
directory containing:

```json
{
  "iteration": 1,
  "total": 5,
  "status": "completed",
  "saved_path": "...",
  "diff_path": "...",
  "artifacts_dir": "...",
  "response_path": "..."
}
```

These files survive after the loop finishes (unlike `repeat_state.json`, which is still used for live progress polling
and cleaned up as before).

### 2. Load repeat iteration markers as child agents

**File:** `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

Add a function (e.g., `_load_repeat_iterations`) called during artifact enrichment that:

- Globs for `repeat_iter_*.json` in the agent's artifacts directory.
- For each marker, creates a child Agent with:
  - `parent_timestamp` = parent's `raw_suffix` (linking to parent)
  - `step_index` = iteration - 1, `total_steps` = total
  - `step_type` = `"agent"` (so existing rendering works)
  - `status` from the marker (DONE/FAILED/RUNNING)
  - `diff_path`, `response_path`, `artifacts_dir` from the marker

Return these children so they can be added to the agent list.

### 3. Integrate repeat children into the agent loader

**File:** `src/sase/ace/tui/models/agent_loader.py`

In `load_all_agents()` (or its enrichment phase), after loading the parent repeat agent, call the new iteration loader.
Add the resulting child agents to the `workflow_agent_steps` list so the existing `_sort_and_reorder()` function inserts
them after their parent — the same path workflow step children take.

### 4. Skip repeat children in `dedup_by_pid`

**File:** `src/sase/ace/tui/models/_dedup.py`

The repeat iteration children won't have PIDs (they're constructed from marker files, not RUNNING claims), so
`dedup_by_pid` should naturally skip them (it already skips `agent.pid is None`). Verify this holds and add no
unnecessary changes.

### 5. Mark repeat parent as a nestable parent for fold logic

The existing fold filter (`_fold_filter.py`) already uses `is_workflow_child` (checks `parent_timestamp is not None`) to
identify children and `parent_timestamp` to group them. Since the new repeat children will have `parent_timestamp` set,
they'll automatically participate in fold/expand/collapse without changes to the fold filter.

The parent agent needs to be recognized as foldable — the existing `_sort_and_reorder` inserts children after agents
that match `agent.agent_type == AgentType.WORKFLOW` or have workflow-prefixed workflows. Since repeat parents are
`AgentType.RUNNING` with no workflow prefix, we need to also match parents that have repeat children (e.g., check
`agent.repeat_count is not None and agent.repeat_count > 1`).

### 6. Render repeat children with iteration labels

**File:** `src/sase/ace/tui/widgets/agent_list.py`

The existing `is_workflow_child` branch already renders `└─ N/M` for children with `step_index`/`total_steps` set.
Repeat iteration children will have these fields, so they'll render naturally. May need to tweak the label format if the
default doesn't look right (e.g., showing the CL name vs a custom iteration label).

Consider removing or adjusting the `↻N/M` annotation on the parent since the children now convey this information
individually. Or keep it as a summary when collapsed.

## What This Plan Does NOT Change

- The `repeat_state.json` live-polling mechanism (still used for real-time progress while running).
- The dedup logic beyond verifying repeat children pass through safely.
- The fold state model or fold filter — these work generically on `parent_timestamp`.
- The repeat directive parsing or variable substitution (`n`/`N` template vars).

---
create_time: 2026-04-17 17:07:00
status: done
prompt: sdd/prompts/202604/fix_planning_status_after_feedback.md
---

# Fix: Agent shows PLANNING instead of RUNNING after user gives feedback

## Problem

In the `sase ace` TUI, when a user gives feedback on a plan and a new feedback round is actively running, the parent
`.plan` workflow continues to show as **PLANNING**. It should show as **RUNNING** because the agent is actively
processing the feedback.

The snapshot in the bug report shows:

```
[workflow] pat_fix_line_chart_2 (PLANNING) (7 steps, 4 hidden) @g.plan
  └─ 1/1.plan ✘ [agent] main (DONE) @g.plan
  └─ 1/1.2 [agent] pat_fix_line_chart_2 (RUNNING) @g.2
```

The `@g.2` child is RUNNING (active feedback round), but `@g.plan` shows PLANNING.

## Root Cause

In `src/sase/ace/tui/models/agent_loader.py`, the `_apply_status_overrides()` function applies status transformations in
this order:

1. **Lines 178-196** — PLANNING → RUNNING when parent has an active feedback child (`.2`, `.3`, ...).
2. **Lines 198-204** — PLANNING → RUNNING when parent has an active workflow step.
3. **Lines 206-244** — Build `parents_with_followup` set, which **excludes** feedback rounds via
   `not _is_feedback_suffix(...)` at line 211.
4. **Lines 246-257** — DONE → PLAN DONE for `.plan` workflows whose follow-ups all completed.
5. **Lines 263-270** — DONE → PLANNING for `.plan` workflows with **no follow-up spawned yet**.

For a typical plan workflow that has finished its plan step, the parent's `workflow_state.json` reports status
`"completed"` → mapped to `"DONE"` by `_workflow_loaders.py`. The bug occurs in this scenario:

- Parent (`.plan` workflow) has status `"DONE"` from `workflow_state.json`.
- Active feedback child `.2` exists (user gave feedback, new feedback round is running).
- **Step 1** (lines 178-196): parent.status is `"DONE"`, not `"PLANNING"`, so the PLANNING → RUNNING override is
  **skipped**.
- **Step 5** (lines 263-270): feedback children are excluded from `parents_with_followup` (line 211), so the parent's
  `raw_suffix` is "not in parents_with_followup" — the override **fires** and sets status to `"PLANNING"`.
- **Final result: PLANNING** (bug — should be RUNNING because feedback round is active).

The PLANNING → RUNNING override in step 1 fires **too early** — before step 5 sets the status to PLANNING.

### Verification

Real `agent_meta.json` files at `~/.sase/projects/sase/artifacts/ace-run/` confirm the data shape:

```json
{
  "pid": 252909,
  "model": "opus",
  "llm_provider": "claude",
  "vcs_provider": "GitHub",
  "role_suffix": ".plan",
  "plan_submitted_at": "2026-03-29T14:00:02.173205+00:00",
  "feedback_submitted_at": "2026-03-29T14:00:50.237021+00:00",
  "plan_approved": true,
  "stopped_at": "2026-03-29T14:07:34.314719+00:00"
}
```

Note: `role_suffix=".plan"` and `feedback_submitted_at` are present, but `"plan": true` is **not**. This confirms that
for plan workflows, the PLANNING status flows through the DONE → PLANNING override path (step 5 above), not through
`enrich_agent_from_meta` (which requires `data.get("plan")` truthy at line 201 of `_artifact_loaders.py`).

## Fix

Modify `_apply_status_overrides()` in `src/sase/ace/tui/models/agent_loader.py`:

1. Compute a new set `parents_with_active_feedback` once near the top of the function: parent timestamps that have at
   least one feedback child (`_is_feedback_suffix(role_suffix)` true) whose status is not in `completed_statuses`.

2. In the DONE → PLANNING override block (lines 263-270): if `agent.raw_suffix in parents_with_active_feedback`, set
   status to `"RUNNING"` instead of `"PLANNING"`.

This is a minimal, surgical change that does not reorder existing logic. The existing PLANNING → RUNNING block (lines
178-196) is left intact — it still correctly handles the other case (parent's status was already PLANNING from
`enrich_agent_from_meta` because `agent_meta.json` has `"plan": true`).

### Sketch

```python
def _apply_status_overrides(agents: list[Agent]) -> None:
    completed_statuses = {"DONE", "FAILED"}

    parent_by_suffix: dict[str, Agent] = {}
    for agent in agents:
        if agent.raw_suffix and not agent.is_workflow_child:
            parent_by_suffix[agent.raw_suffix] = agent

    # NEW: collect parents with an active (non-completed) feedback round so
    # later overrides can treat them as actively-running rather than waiting
    # for plan review.
    parents_with_active_feedback: set[str] = set()
    for agent in agents:
        if (
            agent.parent_timestamp
            and not agent.parent_workflow
            and _is_feedback_suffix(agent.role_suffix)
            and agent.status not in completed_statuses
        ):
            parents_with_active_feedback.add(agent.parent_timestamp)

    # ... (existing timestamp propagation + PLANNING → RUNNING blocks unchanged)

    # ... (existing parents_with_followup, DONE → PLAN APPROVED, DONE → PLAN DONE
    # blocks unchanged)

    # MODIFIED: DONE → PLANNING for plan workflows with no follow-up — but if
    # there is an active feedback round, the agent is actively processing
    # feedback, so use RUNNING instead.
    for agent in agents:
        if (
            agent.agent_type == AgentType.WORKFLOW
            and agent.role_suffix == ".plan"
            and agent.status == "DONE"
            and agent.raw_suffix not in parents_with_followup
        ):
            if agent.raw_suffix in parents_with_active_feedback:
                agent.status = "RUNNING"
            else:
                agent.status = "PLANNING"
```

## Files to Change

### 1. `src/sase/ace/tui/models/agent_loader.py`

Modify `_apply_status_overrides()`:

- Add `parents_with_active_feedback` set computation near the top (after `parent_by_suffix`).
- Modify the DONE → PLANNING block (lines 263-270) to set RUNNING when the parent has an active feedback child.

### 2. `tests/test_agent_loader.py`

Add three regression tests covering the relevant transitions:

- **`test_apply_status_overrides_done_with_active_feedback_becomes_running`**: Parent `.plan` with status `"DONE"` +
  active feedback child `.2` (status `"RUNNING"`) → parent.status should be `"RUNNING"`. (Regression for the bug.)

- **`test_apply_status_overrides_done_with_completed_feedback_becomes_planning`**: Parent `.plan` with status `"DONE"` +
  completed feedback child `.2` (status `"DONE"`) and no other follow-up → parent.status should be `"PLANNING"`.
  (Confirms existing behavior preserved.)

- **`test_apply_status_overrides_done_with_active_code_followup_becomes_plan_approved`**: Parent `.plan` with status
  `"DONE"` + completed feedback child `.2` (status `"DONE"`) + active `.code` follow-up (status `"RUNNING"`) →
  parent.status should be `"PLAN APPROVED"`. (Confirms `.code` follow-up takes precedence and existing behavior
  preserved.)

## Verification Plan

1. Run `just install` (per the workspace gotcha) and `just check` to confirm the fix passes lint + type checks + tests.
2. Run the new regression tests in isolation to confirm they fail before the fix and pass after:
   `pytest tests/test_agent_loader.py -k "active_feedback or completed_feedback or active_code_followup" -v`

## Out of Scope

- The existing `enrich_agent_from_meta` PLANNING/PLAN APPROVED logic in `_artifact_loaders.py` (lines 201-211). It works
  correctly when `"plan": true` is in `agent_meta.json`; this fix targets the separate path that derives PLANNING status
  from `role_suffix=".plan"` + DONE state.
- Workflow step PLANNING → RUNNING override (lines 198-204). Not affected by this bug.
- Reordering `_apply_status_overrides` blocks. The minimal additive fix preserves the existing structure.

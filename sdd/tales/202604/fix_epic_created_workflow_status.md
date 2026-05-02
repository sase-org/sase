---
create_time: 2026-04-24 14:09:13
status: done
prompt: sdd/prompts/202604/fix_epic_created_workflow_status.md
---
# Fix Workflow Status: Show "EPIC CREATED" Instead of "PLAN APPROVED" After Epic Button

## Problem

In the `sase ace` TUI, when a user clicks the "Epic" button (`E`) on the plan approval modal, the Epic-creation agent is
launched as a workflow step child (`1/1.epic`). The plan agent itself is correctly marked with status `EPIC CREATED`,
but the **outer workflow container** still displays `PLAN APPROVED`.

Observed (from `sase ace` snapshot):

```
[workflow] sase (PLAN APPROVED) (6 steps, 3 hidden) @d.plan
  └─ 1/1.plan ✘ [agent] main (DONE) @d.plan
  └─ 1/1.epic   [agent] sase (RUNNING) @d.epic
  └─ 1e/1    ✘ [bash] diff  (DONE) @d.plan  ▼ #gh
```

Expected: the workflow's status should read `EPIC CREATED` (mirroring how the `.commit` follow-up results in
`PLAN COMMITTED` today, though that path likely has the same bug — see "Scope" below).

## Root Cause

`src/sase/ace/tui/models/agent_loader.py` — `_apply_status_overrides()` at lines 215–228 unconditionally overrides the
workflow's `DONE` status to the hardcoded string `"PLAN APPROVED"` whenever _any_ active follow-up child exists,
regardless of the child's `role_suffix`:

```python
parents_with_followup: set[str] = set()
for agent in agents:
    if (
        agent.parent_timestamp
        and not agent.parent_workflow  # Follow-up agent, not workflow step
        and not _is_feedback_suffix(agent.role_suffix)
    ):
        parents_with_followup.add(agent.parent_timestamp)
        parent = parent_by_suffix.get(agent.parent_timestamp)
        if parent:
            # Override DONE → PLAN APPROVED while follow-up is active
            if agent.status not in completed_statuses:
                if parent.status == "DONE":
                    parent.status = "PLAN APPROVED"   # ← hardcoded
```

This code doesn't consult `plan_action` (stored on the plan agent's `agent_meta.json`) nor does it branch on the
follow-up child's own `role_suffix`. So `.epic`, `.commit`, and `.code` follow-ups all result in the same "PLAN
APPROVED" label on the parent.

The inner `_artifact_loaders.py:169-181` logic does the right thing (reads `plan_action` and produces `EPIC CREATED` /
`PLAN COMMITTED` / `PLAN APPROVED`) but only runs on individual plan agents — the workflow container's status is derived
solely from `_apply_status_overrides()`.

## Design

Teach `_apply_status_overrides()` to pick the override status based on the active follow-up child's `role_suffix`:

| Active child `role_suffix` | Workflow status override     |
| -------------------------- | ---------------------------- |
| `.epic`                    | `EPIC CREATED`               |
| `.commit`                  | `PLAN COMMITTED`             |
| anything else              | `PLAN APPROVED` (status quo) |

Tie-breaker when multiple active follow-ups exist (rare but possible): prefer the most-recently-started child. In
practice, there is usually exactly one active follow-up at a time, so a simple last-writer-wins ordering by iteration is
acceptable; we will iterate in start-time order so the newest child's `role_suffix` wins.

### Why derive from `role_suffix` rather than reading `plan_action`

1. The follow-up's `role_suffix` is the _authoritative_ signal of what approval action was taken — it is set by the
   dispatcher in `run_agent_exec_plan.py` when the child is spawned (e.g. `current_role_suffix = ".epic"`).
2. Reading `plan_action` from the plan-agent's `agent_meta.json` would require an additional file read inside the
   status-override loop, and couples the display to a metadata field that the writer (`persist_plan_approved`) could
   forget to set — whereas the child must exist for the override to fire at all.
3. The existing code for `.code` follow-ups at line 246 already keys off `role_suffix` — this is the established
   convention.

### Non-goals

- We are **not** changing `persist_plan_approved()` or how `plan_action` is persisted. The plan agent's own status
  derivation via `_artifact_loaders.py:169-181` remains untouched.
- We are **not** introducing new status strings. `EPIC CREATED` and `PLAN COMMITTED` already exist as valid statuses
  (confirmed via `_workflow_display.py:98-108` and `_workflow_loaders.py:16-24`).
- We are **not** touching the Telegram Epic-button wiring in `_notification_modals.py` or the axe-side dispatch in
  `run_agent_exec_plan.py`.

## Implementation Sketch

In `src/sase/ace/tui/models/agent_loader.py` around lines 215–228:

```python
parents_with_followup: set[str] = set()
# Map raw_suffix → chosen override status for parents with active followups.
# Iterate children in start-time order so that, if multiple are active, the
# most-recently-started wins.
followup_override: dict[str, str] = {}

ordered_agents = sorted(
    agents, key=lambda a: a.run_start_time or a.start_time or ""
)
for agent in ordered_agents:
    if (
        agent.parent_timestamp
        and not agent.parent_workflow
        and not _is_feedback_suffix(agent.role_suffix)
    ):
        parents_with_followup.add(agent.parent_timestamp)
        parent = parent_by_suffix.get(agent.parent_timestamp)
        if parent and agent.status not in completed_statuses:
            if agent.role_suffix == ".epic":
                status = "EPIC CREATED"
            elif agent.role_suffix == ".commit":
                status = "PLAN COMMITTED"
            else:
                status = "PLAN APPROVED"
            followup_override[agent.parent_timestamp] = status

# Apply the override after picking the winning child.
for raw_suffix, status in followup_override.items():
    parent = parent_by_suffix.get(raw_suffix)
    if parent and parent.status == "DONE":
        parent.status = status
```

The meta-field / `diff_path` / `code_time` propagation at lines 230–253 is independent of the status override and should
be left in a second loop (or kept inline — either way, the status decision must finalize before the write).

## Testing

Add to `tests/test_agent_loader.py`:

1. Workflow with active `.epic` child → status becomes `EPIC CREATED`.
2. Workflow with active `.commit` child → status becomes `PLAN COMMITTED`.
3. Workflow with active `.code` child → status stays `PLAN APPROVED` (regression guard).
4. Workflow with completed `.epic` child and no active follow-ups → does **not** flip to `EPIC CREATED` (override only
   fires while active).
5. Workflow with both an active `.epic` and an active `.code` child → newest child wins (document the tie-breaker).

Manually verify in a real `sase ace` session that the snapshot in the "Problem" section now reads `EPIC CREATED`.

## Scope & Risk

- Single-file change plus test additions. No schema changes, no migrations, no new status strings.
- Risk of regression is bounded to the status-override logic for workflows with follow-up children — well covered by the
  existing + new tests.
- Downstream consumers that match on `PLAN APPROVED` (e.g. revive/canonicalize logic in `test_agent_revive.py`) already
  treat `EPIC CREATED` and `PLAN COMMITTED` as first-class statuses, so no further changes should be needed. Plan
  verifier will grep for `PLAN APPROVED` string matches during implementation to confirm.

## Open Question

Should the `.commit` case be included in the same patch, or punted to a follow-up? Current recommendation: include it —
the fix is mechanical, and shipping both together closes the general "hardcoded PLAN APPROVED" bug class in one go
rather than leaving a known-broken variant behind.

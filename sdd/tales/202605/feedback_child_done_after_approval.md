---
create_time: 2026-05-28 08:28:28
status: done
prompt: sdd/prompts/202605/feedback_child_done_after_approval.md
---
# Feedback Child Status After Plan Approval

## Context

The `sase ace` snapshot shows a plan-family root in `TALE APPROVED`, an active `-code` follow-up, and the intermediate
feedback child `@bmx-2` still displayed as `PLAN`. The live artifacts confirm `@bmx-2` recorded:

- `feedback_submitted_at`: the feedback round started at 2026-05-28 08:18:22 EDT.
- `plan_submitted_at`: the revised plan was submitted at 2026-05-28 08:22:44 EDT.
- `plan_approved: true` and `plan_action: tale`.
- A newer `@bmx-code` child exists for the same root parent timestamp.

So the feedback child is no longer waiting for review; it is a completed handoff step and should display `DONE`.

## Root Cause

`src/sase/ace/tui/models/_agent_status_overrides.py` has separate handling for the synthetic/concrete planner child and
feedback-round children.

The planner path already handles the advanced-family case: if the planner is awaiting review but a family follow-up
exists, `_planner_child_status(...)` returns `DONE`.

The feedback path does not. It unconditionally rewrites any `DONE` or `RUNNING` feedback child whose latest plan
timestamp is newer than its latest feedback timestamp to `PLAN`:

```python
elif (
    is_feedback_suffix(agent.role_suffix)
    and agent.status in {"DONE", "RUNNING"}
    and _is_awaiting_plan_review(agent)
):
    agent.status = "PLAN"
```

That correctly represents a feedback child before approval, but it ignores the later approval/handoff state. After
approval, the root and code child are normalized to `TALE APPROVED` / `PLAN APPROVED`, while the feedback child keeps
the stale `PLAN` label.

## Implementation Plan

1. Add a small predicate in `_agent_status_overrides.py` for whether an awaiting-review feedback child has progressed
   past review.
   - Treat it as progressed if its own metadata has `plan_action` set to an approved action such as `tale`, `epic`,
     `legend`, `commit`, or generic `approve`.
   - Also treat it as progressed if any non-workflow family follow-up child exists for the same root parent and was
     launched after that feedback child. This covers the visible `-code` handoff and avoids relying only on metadata
     written to the feedback row.

2. Change the feedback-child override so pending review still becomes `PLAN`, but progressed feedback children become
   `DONE`.
   - Preserve `QUESTION` behavior, because unanswered questions are normalized later and should still win.
   - Keep root mirroring behavior unchanged; the newest active code child should continue driving the root to
     `PLAN APPROVED` or `TALE APPROVED`.

3. Add focused regression tests in `tests/test_agent_loader_status_override_followups.py`.
   - Existing awaiting-review feedback child stays `PLAN`.
   - Feedback child with `plan_action="tale"` and a newer active `-code` child becomes `DONE`, while the root/code child
     stay `TALE APPROVED`.
   - Optionally cover the metadata-only case so persisted approval without loaded code child does not show stale `PLAN`.

4. Run the targeted tests first, then run the repo check required by the project instructions after code changes.
   - `python -m pytest tests/test_agent_loader_status_override_followups.py tests/test_agent_loader_status_override_tale.py`
   - `just install`
   - `just check`

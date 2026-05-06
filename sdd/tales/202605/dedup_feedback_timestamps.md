---
create_time: 2026-05-06 00:27:54
status: done
prompt: sdd/prompts/202605/dedup_feedback_timestamps.md
---
# Deduplicate Plan-Chain Timestamp Aggregation

## Context

The ACE agent details pane renders timestamps from each `Agent` model:

- `plan_times` as `PLAN`
- `feedback_times` as `FBACK`
- `questions_times` as `QUEST`
- `code_time`, `epic_time`, start, and stop timestamps

For plan-chain workflows, metadata is intentionally present in more than one artifact directory:

- The parent `.plan` artifact records the feedback submission event when the user submits feedback.
- The feedback-round child artifact also records the same `feedback_submitted_at` relationship so the child can be
  understood independently in artifact scans and graph ingestion.

The live `@ado.plan` artifact confirms this shape:

- Parent `20260506001245` has `feedback_submitted_at: ["2026-05-06T04:16:35.468038+00:00"]`.
- Child `20260506001635` with `role_suffix: ".2"` and `parent_timestamp: "20260506001245"` has the same
  `feedback_submitted_at` once.

The duplicate visible in `sase ace` is therefore a display/model aggregation issue, not evidence that feedback was
submitted twice.

## Root Cause

`src/sase/ace/tui/models/_agent_status_overrides.py` propagates timestamps from feedback-round children back to their
parent:

```python
parent.plan_times.extend(agent.plan_times)
parent.feedback_times.extend(agent.feedback_times)
parent.questions_times.extend(agent.questions_times)
```

This is not deduplicated. When the parent already loaded the same `feedback_submitted_at` from its own
`agent_meta.json`, extending from the child appends an identical `datetime`, producing two identical `FBACK` rows in
`Agent.timestamps_display`.

The bug is especially visible for the first feedback round because `run_agent_exec_plan.py` writes the same feedback
event to both the current parent metadata and the new follow-up child relationships.

## Goal

Keep the artifact metadata contract intact while making ACE's parent-row timestamp aggregation idempotent:

- One user feedback event should render as one `FBACK` line on the parent.
- Multiple distinct feedback rounds should still render as multiple `FBACK` lines.
- Multiple distinct plan submissions from feedback rounds should still render as multiple `PLAN` lines.
- The fix should not remove relationship metadata from child artifacts, because those artifacts need to remain
  self-describing for graph/index consumers.

## Design

Fix the aggregation point, not the writer.

Add a small helper in `_agent_status_overrides.py` that appends only timestamps not already present in the target list.
Use it when propagating feedback-round child `plan_times`, `feedback_times`, and `questions_times` to the parent.

This keeps existing loader behavior and artifact metadata unchanged, but makes repeated or overlapping sources safe:

- Parent already has the feedback event: child propagation is a no-op for that timestamp.
- Parent does not have the child plan event: child propagation appends it.
- Multiple children have distinct events: all distinct datetimes are preserved.
- If `apply_status_overrides()` is ever called more than once on the same models, it remains idempotent for these
  propagated timestamp lists.

## Implementation Steps

1. Add a timestamp-list append helper near the suffix helpers in `src/sase/ace/tui/models/_agent_status_overrides.py`.
2. Replace the raw `extend()` calls for feedback-round child timestamp propagation with the helper.
3. Add focused tests in `tests/test_agent_loader_status_overrides.py`:
   - A parent and feedback child with the same `feedback_times` value render/hold only one parent feedback timestamp
     after overrides.
   - A feedback child with a new `plan_times` value still propagates to the parent.
   - Reapplying overrides to the same list does not duplicate propagated timestamps.
4. Run the focused tests for status overrides and timestamp display.
5. Because this repo requires it after changes, run `just install` if needed and then `just check`.

## Non-Goals

- Do not change `run_agent_exec_plan.py` metadata writes for this fix.
- Do not migrate or rewrite existing artifact metadata.
- Do not deduplicate in `Agent.timestamps_display` as the primary fix; the model aggregation should be correct before
  rendering.

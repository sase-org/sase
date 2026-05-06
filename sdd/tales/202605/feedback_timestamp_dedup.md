---
create_time: 2026-05-06 00:24:56
status: wip
prompt: sdd/prompts/202605/feedback_timestamp_dedup.md
---
# Plan: Deduplicate Plan Feedback Timestamps in ACE

## Context

The ACE agent details panel builds its `Timestamps:` block from timestamp lists on the displayed `Agent` model.
Plan-chain agents can carry the same feedback event in more than one artifact:

- the current planner artifact records `feedback_submitted_at` when the user rejects a plan with feedback;
- the follow-up feedback-round artifact also records that same `feedback_submitted_at` as relationship metadata, so the
  child can be understood independently by ACE and the artifact graph.

For the snapshot agent `ado`, the root artifact at `20260506001245` and the feedback child at `20260506001635` both
contain the exact same feedback timestamp, `2026-05-06T04:16:35.468038+00:00`. `apply_status_overrides()` then
propagates feedback child timestamps back to the parent with plain `list.extend()`, so the parent renders two `FBACK`
entries at `2026-05-06 00:16:35`.

## Goal

Make the ACE metadata panel show one timeline entry per distinct user feedback event, while preserving distinct plan,
feedback, and question rounds when they really occurred separately.

## Approach

1. Keep the artifact metadata contract intact. Do not stop writing `feedback_submitted_at` on either the planner
   artifact or the follow-up child, because both are useful in their own context and for relationship ingestion.
2. Fix the ACE aggregation boundary in `src/sase/ace/tui/models/_agent_status_overrides.py`.
3. Replace direct timestamp `extend()` calls used when propagating feedback-round child events to the parent with a
   small helper that appends only datetimes not already present.
4. Apply the helper to the related propagated event lists (`plan_times`, `feedback_times`, `questions_times`) so the
   aggregation path is consistently idempotent.
5. Add a regression test in `tests/test_agent_loader_status_overrides.py` covering a parent and feedback child that both
   carry the same `feedback_times` value, while still verifying child-only plan timestamps are propagated.
6. Run focused tests for status overrides and timestamp display. Because this repo requires it after edits, run
   `just install` if needed and then `just check` before reporting back.

## Risk and Notes

This is a display/model aggregation fix, not a migration. Existing artifacts with duplicate relationship timestamps will
render correctly after reload. Exact datetime equality is the right dedupe key: two real events with distinct
microseconds remain separate, while the duplicated parent/child copy of the same event collapses to one display row.

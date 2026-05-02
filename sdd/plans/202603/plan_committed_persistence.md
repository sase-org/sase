---
create_time: 2026-03-31 18:46:30
status: done
prompt: sdd/prompts/202603/plan_committed_persistence.md
---

# Plan: Persist "PLAN COMMITTED" (and "EPIC CREATED") agent status across TUI restarts

## Problem

When a user clicks "commit" (or "epic") in the plan approval modal, the TUI sets an in-memory status override
(`_agent_status_overrides`) to "PLAN COMMITTED" (or "EPIC CREATED") and calls `persist_plan_approved()`. However,
`persist_plan_approved()` only writes `plan_approved: true` to `agent_meta.json`. On TUI restart,
`enrich_agent_from_meta()` reads this flag and maps it to "PLAN APPROVED" — there is no way to distinguish "approved"
from "committed" or "epic created" on disk.

**Result**: After restart, agents that were "PLAN COMMITTED" or "EPIC CREATED" revert to showing "PLAN APPROVED".

## Root Cause

`persist_plan_approved()` is a one-size-fits-all function that writes the same `plan_approved: true` regardless of which
action was taken. The load-side (`enrich_agent_from_meta()`) has no field to differentiate the three plan approval
actions.

## Fix

### 1. Write a `plan_action` field to `agent_meta.json`

In `_notification_modals.py`, update `persist_plan_approved()` to accept an optional `action` parameter (one of
`"approve"`, `"commit"`, `"epic"`). Write it as `plan_action` alongside the existing `plan_approved: true`.

Update the three call sites in `on_dismiss()` to pass the appropriate action string.

### 2. Read `plan_action` in `enrich_agent_from_meta()`

In `_artifact_loaders.py`, extend the existing `plan + plan_approved` status logic (lines 131-136) to check
`plan_action`:

- `plan_action == "commit"` → status = "PLAN COMMITTED"
- `plan_action == "epic"` → status = "EPIC CREATED"
- Otherwise (including `plan_action == "approve"` or absent) → status = "PLAN APPROVED" (existing behavior)

### 3. Backfill: in-memory override no longer needed for these statuses

Once the on-disk status is correct, the in-memory `_agent_status_overrides` entries for "PLAN COMMITTED" and "EPIC
CREATED" become redundant on the _next_ load cycle (since `enrich_agent_from_meta` will set them). They're still useful
for the _immediate_ UI update before the next refresh, so keep setting them — they'll just be consistent with what's on
disk.

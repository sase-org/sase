---
create_time: 2026-03-29 17:50:05
status: done
---

# SASE Plan: timestamps field gap for #pr-created ChangeSpecs

## Goal

Ensure ChangeSpecs created via `#pr` (and similar workflow-based creation paths) consistently get `TIMESTAMPS` entries,
matching the TIMESTAMPS plan intent and current event model.

## Findings Summary

- TIMESTAMPS parsing/rendering/recording infrastructure is already implemented.
- Existing event hooks record timestamps for:
  - commit entry creation via `add_commit_entry_with_id()` / `add_proposed_commit_entry()`
  - status transitions
  - sync success
  - reword description and tag add
- Gap: `create_changespec_for_workflow()` creates a new ChangeSpec with an initial COMMITS entry
  (`(1) [run] Initial Commit`) by writing raw block text via `add_changespec_to_project_file()`, so commit-entry
  timestamp hooks are bypassed.
- Consequence: if no later status/reword/sync/commit events occur, new specs have no `TIMESTAMPS:` section.

## Plan

1. Update ChangeSpec creation path to seed initial TIMESTAMPS entries.

- Extend `add_changespec_to_project_file()` to accept optional initial timestamp entries and serialize a `TIMESTAMPS:`
  block at creation time.
- Keep section ordering consistent (`TIMESTAMPS` last).

2. Record initial COMMIT timestamp for initial commits created at spec creation.

- In `create_changespec_for_workflow()`, construct initial timestamp entries corresponding to each initial commit entry
  ID.
- Ensure detail format is `(<entry_id>)` and event type is `COMMIT`.

3. Add/adjust tests.

- Add focused tests ensuring ChangeSpec creation with initial commits produces `TIMESTAMPS:` entries.
- Verify parser round-trip still works and no regressions in existing creation/commit workflow tests.

4. Validate end to end.

- Run `just install` (workspace hygiene requirement).
- Run targeted tests first, then full `just check` before final response.

## Risks / Notes

- Preserve backward compatibility: call sites that do not pass initial timestamps should retain current behavior.
- Keep implementation minimal: do not redesign existing timestamp recorder paths; close only the creation-time gap.

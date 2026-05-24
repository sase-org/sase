---
create_time: 2026-05-24 16:44:50
status: done
---
# Fix Notification Modal Revert Conflict

## Context

`bc0fb1775ed9` attempted to resolve a conflict while reverting `6be68fa08`
(`feat: sync plan notification mutes to agent tags`) after `5240b224a` had already split the old monolithic
`tests/test_notification_modal_actions.py` module into focused notification modal test files.

The current tree correctly removes the production mute-tag sync feature from `src/sase/ace/...`, but the conflict
resolution reintroduced the old monolithic `tests/test_notification_modal_actions.py` file and left some
reverted-feature expectations in `tests/test_notification_modal_mute_snooze.py`.

## Goal

Make the repository represent the intended post-revert state:

- The plan-notification mute-tag sync feature from `6be68fa08` stays reverted.
- The test split from `5240b224a` stays intact.
- No duplicate monolithic notification modal action test module remains.
- No tests assert behavior from the reverted mute-tag sync feature.

## Plan

1. Remove the accidentally restored `tests/test_notification_modal_actions.py` file. Its valid coverage already lives in
   the split files added by `5240b224a`.

2. Update `tests/test_notification_modal_mute_snooze.py` to remove the tests that still expect
   `_sync_plan_notification_mute_tag` to be called when muting, unmuting, or snoozing plan approval notifications. Those
   expectations belong to the reverted `6be68fa08` feature.

3. Search the codebase for remaining references to the reverted mute-tag sync API and plan-notification mute-tag tests.
   If any non-documentation references remain, remove or adjust them to match the reverted behavior.

4. Validate the focused notification modal and polling/tag tests first, then run the repository-required validation.
   Because this repo requires it after file changes, run `just install` if needed and then `just check`.

## Expected Result

The final diff should be small and conflict-resolution focused: deleting the stale monolithic test module and removing
only the leftover tests for the reverted feature. Existing split-test coverage for dismiss, bindings, mark/tabs,
mute/snooze, jump, and sections should remain in place.

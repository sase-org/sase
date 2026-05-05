---
create_time: 2026-05-05 11:38:21
status: wip
prompt: sdd/prompts/202605/sync_dollar_hooks.md
---
# Plan: Reset `$` Hook Results After `Y` Sync

## Goal

When the `sase ace` CLs-tab sync action bound to `Y` completes successfully, every HOOKS entry using the special `$`
prefix should have its status line for the latest COMMITS entry removed. Removing that status line makes the axe hook
scheduler treat the hook as stale for the current commit and start it again on the next hook-check cycle.

## Current Shape

- `Y` is the default app keymap for the `sync` action in `src/sase/default_config.yml`, with a fallback binding in
  `src/sase/ace/tui/bindings.py`.
- `SyncMixin.action_sync()` submits `_sync_task()` as a background task and passes an `on_success` callback.
- `TaskActionsMixin._on_task_worker_completed()` only invokes `on_success` when the task returns `success=True`, so the
  hook reset belongs after sync completion, not before or on failure.
- `src/sase/ace/hooks/mutations.py::reset_dollar_hooks()` already parses the current ChangeSpec, identifies hooks whose
  command prefix includes `$`, kills running processes for those hooks, and delegates to
  `rerun_delete_hooks_by_command()` with the latest COMMITS entry ID.

## Implementation Plan

1. Strengthen the helper contract around "latest COMMITS entry"
   - Keep `reset_dollar_hooks()` as the domain-level hook reset helper.
   - Ensure it computes the latest entry from the current ChangeSpec's COMMITS list and clears only that entry ID.
   - Preserve older hook status lines and non-`$` hook status lines.
   - Preserve no-op behavior when the ChangeSpec, HOOKS, or COMMITS entries are missing.

2. Strengthen the TUI sync completion contract
   - Keep the reset in the `action_sync()` success callback so it runs after the background sync task has completed.
   - Ensure it is not invoked when sync submission is rejected or when the background task reports failure.
   - Leave the keymap itself unchanged because `Y -> sync` is already configured in the default keymaps and fallback
     bindings.

3. Add focused regression tests
   - Add helper-level tests proving `$` hooks lose only the status line for the latest COMMITS entry.
   - Cover mixed `$` and non-`$` hooks, combined prefixes such as `!$`, and preservation of older COMMITS status lines.
   - Add a TUI action-level test proving `action_sync()` registers a success callback that calls `reset_dollar_hooks()`
     with the selected ChangeSpec file/name only when the sync task succeeds.

4. Verify behavior
   - Run the focused tests for hook reset and TUI sync behavior.
   - Because this repo requires it after changes, run `just install` if needed and then `just check` before reporting
     completion.

## Risks And Boundaries

- Do not move this behavior into Textual rendering code; this is ChangeSpec mutation logic, shared by
  sync/reword/add-tag style workflows.
- Do not delete all historical status lines for `$` hooks. Only the latest COMMITS entry should be invalidated so older
  run history remains visible.
- Do not reset `$` hooks on failed sync, unresolved conflicts, failed checkout, rejected task submission, or terminal
  ChangeSpecs where sync is unavailable.

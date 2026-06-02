---
create_time: 2026-06-02 06:18:39
status: done
prompt: sdd/prompts/202606/project_management_marks.md
---
# Project Management Marks Plan

## Context

The new Project Management modal currently supports single-project lifecycle actions: activate, archive, close, delete,
force-after-block, reload, text filtering, and state filtering. Existing mark behavior in this codebase follows two
useful patterns:

- ChangeSpecs use `m` to toggle a `[✓]` row mark, auto-advance, show mark counts, and let later actions switch from
  single-row semantics to marked-set semantics.
- Agents and modal-local pickers use stable identities for marks, patch or rebuild row prompts after toggles, preserve
  marks across ordinary navigation/filtering, and clear or prune marks after the underlying entries disappear.

Project entries should follow the stable-identity pattern. Project names are the natural mark keys because filters and
reloads can reorder rows, while project names remain stable.

## Goals

Add `m` support inside `ProjectManagementModal` so users can mark multiple project entries and run lifecycle operations
on the marked set.

Keep the implementation modal-local. The Project Management modal is already a modal with hardcoded local `BINDINGS`,
like the artifact and tag cleanup modals, so this does not need a new app-level `AppKeymaps` field or
`default_config.yml` entry unless we decide to make modal bindings globally configurable later.

## User-Facing Behavior

1. Pressing `m` on a project row toggles a project mark, renders a green checked marker in that row, and advances to the
   next visible project row with wraparound.
2. Pressing `u` clears all project marks in the modal.
3. Marks are keyed by project name and persist across text/state filter changes. Marks are pruned only when reload shows
   that a project no longer exists.
4. When no projects are marked, `a`, `r`, `c`, `Ctrl+D`, and `Enter` keep their current single-project behavior.
5. When one or more projects are marked:
   - `a`, `r`, and `c` operate on every live marked project in loaded-record order.
   - `Ctrl+D` opens one bulk delete confirmation for the marked projects.
   - `Enter` should continue to be a default action for the highlighted row, not a hidden bulk operation; explicit
     lifecycle keys should drive bulk changes.
6. Summary/footer/detail text should show the current mark count and make it clear when lifecycle/delete keys are
   targeting the marked set.

## Technical Design

Add `self._marked_projects: set[str]` to `ProjectManagementModal`. Add helpers for mark bookkeeping:

- `_marked_records()` returns live marked records from `self._records` in display order.
- `_target_records()` returns marked records when marks exist, otherwise the selected record.
- `_prune_stale_marked_projects()` removes marks whose project names are absent after reload.
- `_refresh_footer()` updates the footer `Static` after mark changes and reloads.

Update row rendering so `_record_label()` emits `[✓] ` before the project name when the project is marked. The modal can
rebuild options on mark toggles rather than introducing a custom patch path; the list is small and this keeps the change
well scoped.

State changes should route through a shared bulk-aware helper rather than duplicating activate/archive/close logic:

- `_set_project_state(state, force=False)` remains the public action target but delegates to a records/names helper.
- For marked-set state changes, skip projects already in the requested state, apply `set_project_state_locked()` to each
  remaining project, collect successes, failures, and `ProjectLifecycleBlockedError`s, then reload once.
- Clear marks for successful or skipped projects; preserve marks for blocked or failed projects so the user can retry.
- Replace the single pending-force tuple with a pending force target that can hold one or many project names plus the
  desired state.
- `F` confirms and force-applies the pending blocked set. The existing single-row force flow should remain a one-project
  special case of the same mechanism.

Deletion should use one confirmation modal when marks exist:

- Build the confirmation message from marked project names and directories, truncating long lists but always showing the
  count and warning that workspace checkouts are not deleted.
- On confirm, call `delete_project_locked(project, projects_root=self._projects_root)` for each live marked project.
- Clear deleted marks, preserve blocked/failed marks, reload once, and call `_notify_lifecycle_changed()` once if any
  project changed.

Filtering and reload behavior:

- `_apply_filters()` should not clear marks.
- `_load_records()` should prune marks after replacing `self._records`.
- `_refresh_options()` should keep the current highlighted project when possible and update summary/detail/footer so
  hidden marked projects are still counted.

## Tests

Extend `tests/ace/tui/modals/test_project_management_modal.py` with focused modal tests:

- `m` marks the highlighted project, advances selection, renders the checked marker, and updates footer/summary mark
  count.
- `u` clears project marks and restores unmarked row labels.
- Marks survive state/text filter changes and are pruned after reload removes a project.
- With marks present, `r` or `c` calls `set_project_state_locked()` for the marked projects, not the highlighted
  unmarked row.
- Bulk state changes clear successful marks, preserve blocked/failed marks, and allow `F` to force the blocked set after
  one confirmation.
- Bulk delete opens a single confirmation, cancel preserves marks, confirm deletes each marked project through
  `delete_project_locked()`, reloads once, and preserves marks for blocked failures.
- Existing single-project activate/delete/force tests continue to pass.

## Verification

After implementation, run the focused modal tests first:

```bash
just install
pytest tests/ace/tui/modals/test_project_management_modal.py
```

Because this repository requires a full check after code changes, finish with:

```bash
just check
```

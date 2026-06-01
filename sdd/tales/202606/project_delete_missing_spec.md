---
create_time: 2026-06-01 17:25:14
status: done
prompt: sdd/prompts/202606/project_delete_missing_spec.md
---
# Plan: Fix Project Management Delete for Missing Active ProjectSpec

## Root Cause

The new `Ctrl+D` flow in `ProjectManagementModal` selects a `ProjectRecordWire` returned by `list_project_records()` and
calls `delete_project_locked(record.project_name, ...)`. The lifecycle listing can surface a project directory whose
active ProjectSpec is missing, marking it as active/defaulted with warnings like `active ProjectSpec file not found`.
The deletion helper then resolves the directory successfully but rejects it because
`preferred_project_spec_path(...).is_file()` is false, raising `project '<name>' was not found`.

That makes malformed or partially-deleted SASE project directories visible in the management panel but impossible to
delete from that same panel. The snapshot shows exactly that state for `bryan`: the project directory exists, the row is
selected, and the detail pane warns that `/home/bryan/.sase/projects/bryan/bryan.sase` is missing.

## Implementation Plan

1. Update `delete_project_locked()` in `src/sase/main/project_handler.py` so deletion is based on the validated project
   directory, not the existence of the active ProjectSpec alone.
2. Preserve the existing safety checks:
   - reject `home`, path traversal, symlinks, and non-direct-child targets;
   - reject system-managed records when `list_project_records()` reports one;
   - block deletion if live artifact markers exist under the project directory.
3. When an active ProjectSpec exists, keep the current behavior: hold `changespec_lock(str(project_file))`, read the
   file, reject live `RUNNING` claims, revalidate the directory inside the lock, and then `shutil.rmtree()` the
   directory.
4. When the active ProjectSpec is missing, allow deletion of the validated project directory after checking live
   artifact markers. Use a deterministic lock path based on the expected active ProjectSpec path so concurrent delete
   attempts are still serialized, but skip content-based `RUNNING` claim parsing because there is no active file to
   parse.
5. Keep error messages specific: a missing directory is still `project '<name>' was not found`; a missing active spec is
   no longer treated as project-not-found when the directory itself exists.

## Tests

1. Add a focused backend regression test in `tests/main/test_project_handler.py` for a project directory whose
   `<name>.sase` file is absent but which contains other SASE state. `delete_project_locked()` should remove the whole
   directory.
2. Add a blocked variant for the same missing-spec shape with a live artifact marker, asserting that deletion raises
   `ProjectLifecycleBlockedError` and leaves the directory intact.
3. Add or adjust a modal test in `tests/ace/tui/modals/test_project_management_modal.py` so a defaulted/warning record
   can be confirmed and deleted without surfacing `project '<name>' was not found`.

## Verification

Run focused tests first:

```bash
pytest tests/main/test_project_handler.py tests/ace/tui/modals/test_project_management_modal.py
```

Then run the repository-required validation after file changes:

```bash
just install
just check
```

---
create_time: 2026-06-01 16:05:30
status: done
prompt: sdd/prompts/202606/project_delete_keymap.md
---
# Add Ctrl+D Project Deletion to Project Management Panel

## Context

The Project Management panel is opened by the leader keymap `,P` and implemented in
`src/sase/ace/tui/modals/project_management_modal.py`. It currently lists all non-system projects and supports lifecycle
state changes (`active`, `archived`, `closed`) with a force-confirm flow for blocked archive/close operations.

SASE project state is stored under `sase_projects_dir()`, which resolves to `$SASE_HOME/projects` or `~/.sase/projects`.
The user-facing request mentions `~/.sase/project/<project>/`, but the repository consistently uses the plural
`projects` path. The implementation should therefore delete `~/.sase/projects/<project>/` via `sase_projects_dir()`.

There is already a `ctrl+d` delete action in `ProjectSelectModal`, but that older flow only deletes project spec files
when no ChangeSpecs exist. It does not delete the whole project directory, does not live in the Project Management
panel, and should not be reused as-is for this request.

## Goals

- Add a `Ctrl+D` binding to `ProjectManagementModal`.
- Prompt the user with a y/n confirmation before the destructive operation.
- Delete the selected project's entire SASE project directory, including active and archive ProjectSpec files,
  project-local config, artifacts, and other contents below that directory.
- Keep system-managed projects such as `home` protected.
- Avoid deleting project state while live work is still registered.
- Refresh the Project Management panel and the parent TUI after deletion.
- Cover the deletion helper and modal behavior with focused tests.

## Non-Goals

- Do not delete the source checkout/workspace referenced by `WORKSPACE_DIR`; the requested destructive target is the
  SASE project state directory under `~/.sase/projects/<project>/`.
- Do not add a CLI `sase project delete` command unless the implementation reveals it is necessary. This task is
  specifically for the Project Management panel.
- Do not change the global configurable keymap registry or `default_config.yml`; this is a modal-local Textual binding,
  like the existing ProjectSelectModal `ctrl+d` binding.

## Design

Add a small backend helper alongside the existing project lifecycle helpers in `src/sase/main/project_handler.py`, for
example `delete_project_locked(project, projects_root=None)`.

The helper should:

- Resolve the target as `<projects_root or sase_projects_dir()> / project`.
- Reject `home` and any system-managed project.
- Validate the target is an actual direct child directory of the projects root, not an arbitrary or path-traversal
  target.
- Resolve the active ProjectSpec path using `preferred_project_spec_path`.
- Hold the existing `changespec_lock` while checking project content and deleting, matching the lifecycle mutation model
  already used by `set_project_state_locked`.
- Reuse the existing live-work checks:
  - `list_workspace_claims_from_content` for `RUNNING` claims.
  - `_live_artifact_marker_paths` for `running.json`, `waiting.json`, and `pending_question.json`.
- If live work is present, raise `ProjectLifecycleBlockedError` and leave the directory untouched.
- Use `shutil.rmtree` to remove the whole target directory after validation and live-work checks pass.
- Return a small result value or the deleted project name/path so the TUI can produce an accurate notification.

In `ProjectManagementModal`:

- Add `Binding("ctrl+d", "delete_project", "Delete", priority=True)` to `BINDINGS`.
- Add `Ctrl+D delete` to the modal footer text.
- Implement `action_delete_project`:
  - Read the selected `ProjectRecordWire`; if nothing is selected, set/notify a "No project selected" status.
  - Block `home` or `record.system_managed` defensively.
  - Push `ConfirmActionModal` with explicit destructive wording, including the project name and the full project
    directory path.
  - On `n`/cancel, set a short "Delete cancelled" status.
  - On `y`, call the deletion helper, catch blocked/error cases, update the status, reload records, refresh options,
    notify parent TUI refresh hooks via `_notify_lifecycle_changed`, and show a success notification.

The confirmation prompt should make clear that it deletes the SASE project directory and cannot be undone. It should not
imply that the workspace checkout is deleted.

## Tests

Add or extend tests in:

- `tests/main/test_project_handler.py`
  - Deletes an entire project directory containing active spec, archive spec, and nested artifacts.
  - Rejects deletion of `home`.
  - Rejects deletion when the ProjectSpec has live `RUNNING` claims.
  - Rejects deletion when live artifact marker files exist.
  - Leaves the directory intact on blocked/error paths.

- `tests/ace/tui/modals/test_project_management_modal.py`
  - `Ctrl+D` opens a y/n confirmation for the selected project.
  - Pressing `n` cancels and does not call the deletion helper.
  - Pressing `y` calls the deletion helper, reloads the project list, removes the deleted row, and updates the status.
  - A `ProjectLifecycleBlockedError` from the helper surfaces as a blocked status and leaves the row visible.
  - The modal footer includes the new delete affordance.

Run focused tests first:

```bash
pytest tests/main/test_project_handler.py tests/ace/tui/modals/test_project_management_modal.py
```

Because this repo requires a full check after file changes, run:

```bash
just install
just check
```

## Risks and Mitigations

- **Accidental deletion outside SASE_HOME**: validate direct-child paths under `sase_projects_dir()` before calling
  `shutil.rmtree`.
- **Deleting live work state**: reuse the existing RUNNING-claim and live-artifact marker checks and block deletion when
  either is present.
- **Stale UI after deletion**: reload the modal records and trigger the same parent refresh hooks used by lifecycle
  state changes.
- **Ambiguous path wording**: use `sase_projects_dir()` everywhere and surface the actual resolved path in the
  confirmation message.

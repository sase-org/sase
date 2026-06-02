---
create_time: 2026-06-02 06:59:55
status: done
prompt: sdd/prompts/202606/project_management_edit_keymap_1.md
---
# Plan: Project Management `e` Edit Keymap

## Goal

Add a local `e` key binding to the ACE TUI Project Management modal that opens the ProjectSpec file for the currently
highlighted project in the user's editor. The action should use the project path discovered by the lifecycle backend,
avoid surprising project directory creation, protect the ProjectSpec while the editor is open, and refresh the TUI after
the editor exits.

## Current State

- The Project Management panel is implemented by `ProjectManagementModal` in
  `src/sase/ace/tui/modals/project_management_modal.py`.
- Modal rows are `ProjectRecordWire` values returned by the Rust-backed `list_project_records()` facade. Each row
  already carries `project_file`, `project_dir`, state, warnings, launchability, and claim counts.
- Modal actions are local Textual bindings, not app-level configurable keymaps. The panel already binds filtering, state
  changes, marking, deletion, force, reload, and close locally.
- Footer affordances are hand-rendered in `src/sase/ace/tui/modals/project_management_rendering.py`.
- Lifecycle/delete actions call `_notify_lifecycle_changed()`, which asks the parent app to refresh ChangeSpecs, Agents,
  AXE, and the active tab when project state may have changed.
- Existing TUI editor flows use `$EDITOR` with an `nvim` fallback, `sase.ace.hints.build_editor_args()`,
  `subprocess.run(..., check=False)`, and `self.app.suspend()` or `self.suspend()` while the external editor owns the
  terminal.
- Existing ChangeSpec editing uses `acquire_edit_lock()` / `release_edit_lock()` around ProjectSpec editor sessions so
  cooperating writers wait while the file is being edited.
- Tests for this modal are split across `tests/ace/tui/modals/test_project_management_modal_filtering.py`,
  `test_project_management_modal_states.py`, `test_project_management_modal_marks.py`, and
  `test_project_management_modal_delete.py`, with shared helpers in `project_management_modal_test_helpers.py`.

## Design

1. Add a modal-local binding:
   - Key: `e`
   - Action: `edit_project_spec`
   - Label: `Edit`
   - Scope: `ProjectManagementModal.BINDINGS` only

2. Target only the highlighted project.
   - Call `_selected_record()`.
   - If no record is selected, set status to `No project selected` and notify with warning severity.
   - Ignore marks for this action. Bulk state/delete operations use marks, but editing multiple ProjectSpec files is not
     part of this request and would make accidental edits easier.

3. Open the authoritative ProjectSpec path.
   - Use `Path(record.project_file).expanduser()`.
   - Do not derive the file from project name or `_projects_root`; discovery already accounts for canonical, legacy, and
     future path details.
   - If `record.project_file` is empty or unusable, report an error.
   - If the parent directory is missing, report an error and do not create it. This check must happen before
     `acquire_edit_lock()`, because that helper creates missing lock directories.
   - Do not require the ProjectSpec file itself to exist. Defaulted/missing-spec records with an existing project
     directory should still open the intended ProjectSpec path so the editor can create it.

4. Preserve write safety while the editor is open.
   - Acquire `acquire_edit_lock(str(project_file))` before suspending the TUI.
   - Release it in a `finally` block with `release_edit_lock(str(project_file))`.
   - This matches existing ChangeSpec edit behavior and protects cooperating SASE writers during manual edits.

5. Invoke the editor consistently with existing TUI flows.
   - Resolve `editor = os.environ.get("EDITOR") or "nvim"`.
   - Build arguments with `build_editor_args(editor, [str(project_file)])`.
   - Run `subprocess.run(editor_args, check=False)` inside `with self.app.suspend():`.
   - Treat `OSError` and similar launch failures as errors: release the edit lock, set a concise status, and notify with
     error severity. A nonzero editor exit code should not raise because `check=False` is intentional.

6. Refresh after the editor process exits.
   - Clear `_pending_force`; a manual ProjectSpec edit can make any prior blocked-force state stale.
   - Reload records with `_load_records()`.
   - Refresh options with `preferred_project=record.project_name` so the same row remains highlighted when it still
     exists and matches the current filters.
   - Call `_notify_lifecycle_changed()` after a successful editor launch/return so app-level panes can reflect manual
     edits.
   - Use status wording such as `Editor closed for alpha` rather than claiming the file changed.

7. Update visible affordances.
   - Add `e edit` to `footer_text()` in `project_management_rendering.py`.
   - Update footer assertions accordingly.
   - Do not update `src/sase/default_config.yml`, command catalog metadata, or app keymap tests unless implementation
     reveals a hidden app-level keymap surface. This is a modal-local Textual binding, and the default-config gotcha
     applies to configurable app keymaps.

## Test Plan

- Add a focused edit test module, likely `tests/ace/tui/modals/test_project_management_modal_edit.py`, reusing
  `ProjectManagementTestApp` and `make_project_record()`.
- Cover the happy path:
  - pressing `e` on a highlighted record opens exactly `record.project_file`;
  - `$EDITOR` is honored and `build_editor_args()` semantics are observable through the subprocess arguments;
  - the app is suspended while the subprocess runs;
  - the `.edit_lock` sentinel is released after completion;
  - records are reloaded and selection prefers the edited project;
  - `_notify_lifecycle_changed()` reaches the app refresh hooks.
- Cover edge cases:
  - no highlighted record does not invoke the editor and reports `No project selected`;
  - a missing ProjectSpec file with an existing parent directory still invokes the editor;
  - a missing parent directory does not invoke the editor and reports a clear error;
  - editor launch failure releases the edit lock and reports an error.
- Update `test_project_management_modal_filtering.py` or a rendering-focused assertion so the footer includes `e edit`
  as well as the existing `Ctrl+D delete` affordance.

## Validation

After implementation:

```bash
just install
just test tests/ace/tui/modals/test_project_management_modal_edit.py tests/ace/tui/modals/test_project_management_modal_filtering.py
just check
```

If `just check` is blocked by an unrelated existing failure, capture the exact failing command/output and still run the
focused modal tests.

## Risks And Tradeoffs

- Refreshing after every editor return may do extra work when the user closes without changes, but stale lifecycle and
  launchability state would be more confusing than a low-frequency refresh.
- Allowing missing ProjectSpec files to be created is useful for defaulted records, but implicitly creating missing
  project directories would be surprising, so parent directories should be required.
- The edit lock is cooperative. It protects SASE writers that honor the existing lock helpers, but it cannot block
  arbitrary external editors or shell commands.

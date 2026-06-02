---
create_time: 2026-06-02 06:44:17
status: wip
prompt: sdd/prompts/202606/project_management_edit_keymap.md
---
# Plan: Project Management `e` Edit Keymap

## Goal

Add an `e` keymap to the ace TUI Project Management modal that opens the ProjectSpec file for the highlighted project in
the user's editor. The action should fit the existing modal behavior, avoid inventing a second project path resolver,
and refresh TUI state after the editor exits so manual ProjectSpec changes are visible.

## Current State

- The Project Management modal lives in `src/sase/ace/tui/modals/project_management_modal.py`.
- Rows are backed by `ProjectRecordWire`, which already carries the authoritative `project_file` path from the
  Rust-backed lifecycle/discovery facade.
- The modal already has local Textual bindings for project lifecycle actions, a hand-maintained footer string, reload
  behavior, and `_notify_lifecycle_changed()` hooks that refresh the rest of the app after project lifecycle mutations.
- Existing editor actions in the TUI use `$EDITOR` with an `nvim` fallback, `sase.ace.hints.build_editor_args()`,
  `subprocess.run(..., check=False)`, and `self.app.suspend()` or `self.suspend()` while the external editor owns the
  terminal.
- Existing ChangeSpec editing wraps the ProjectSpec path in `acquire_edit_lock()` / `release_edit_lock()` so other
  cooperating writers wait while the user has the file open.

## Design

1. Add a modal-local binding:
   - Key: `e`
   - Action: `edit_project_spec`
   - Label: `Edit`
   - Scope: only `ProjectManagementModal.BINDINGS`

2. Use the selected/highlighted row only.
   - The new action will call `_selected_record()`.
   - If there is no selected record, set modal status to `No project selected` and notify with warning severity.
   - Marked projects will not affect this key. Bulk state and delete actions already use marks, but this request is for
     the selected project spec file.

3. Open the authoritative ProjectSpec path.
   - Use `record.project_file`, expanded via `Path(record.project_file).expanduser()`.
   - Do not derive the path from project name or `_projects_root`; that would duplicate lifecycle discovery logic and
     could be wrong for legacy or future path rules.
   - If the path's parent directory does not exist, notify an error instead of creating a project directory as a side
     effect of pressing `e`.
   - Do not require the ProjectSpec file itself to exist. Defaulted/missing-spec records should still let the editor
     create the associated spec path if the project directory exists.

4. Preserve ProjectSpec write safety while the editor is open.
   - Use `acquire_edit_lock(str(project_file))` before suspending the TUI.
   - Release it in a `finally` block with `release_edit_lock(str(project_file))`.
   - This matches the existing ChangeSpec edit behavior and prevents cooperating SASE writers from mutating the same
     ProjectSpec while the user edits.

5. Editor invocation behavior.
   - Import and use `build_editor_args()`.
   - Resolve editor as `os.environ.get("EDITOR") or "nvim"`.
   - Run `subprocess.run(editor_args, check=False)` inside `with self.app.suspend():`.
   - Catch editor launch failures such as `OSError`, set a clear status, and notify with error severity. The edit lock
     must still be released.

6. Refresh after the editor exits.
   - Reload project records with `_load_records()`.
   - Refresh options with `preferred_project=record.project_name` so the same project remains highlighted when it still
     exists and matches filters.
   - Call `_notify_lifecycle_changed()` after a successful editor return so ChangeSpecs, agents, AXE, and the active tab
     can refresh if the ProjectSpec content changed.
   - Set a concise status such as `Edited alpha spec` or `Editor closed for alpha`; prefer wording that does not claim
     the file was changed.

7. Update visible affordances.
   - Add `e edit` to `_footer_text()`.
   - Existing help/config keymap files should not need updates because this is a modal-local Textual binding, not an
     app-level configurable keymap in `default_config.yml`.

## Tests

1. Extend `tests/ace/tui/modals/test_project_management_modal.py`.
   - Pressing `e` on a selected project opens `record.project_file` with `$EDITOR` through `build_editor_args()`
     semantics.
   - The editor call occurs while the TUI is suspended. This can be verified with a small suspend recorder or by
     following the existing modal editor test style where feasible.
   - A temporary `.edit_lock` is released after the action completes.
   - The modal reloads records and preserves the selected project after the editor exits.
   - App refresh hooks such as `_schedule_changespecs_async_refresh()` and `_refresh_current_tab()` are invoked via
     `_notify_lifecycle_changed()`.

2. Add edge coverage.
   - Empty filtered list or no highlighted record does not invoke the editor and reports `No project selected`.
   - Missing ProjectSpec file with an existing project directory still invokes the editor for the intended path.
   - Missing parent directory does not invoke the editor and reports a clear error.
   - Editor launch failure releases the edit lock and reports an error.

3. Update existing footer assertion.
   - Change the footer test to expect both `e edit` and the existing delete affordance.

## Validation

After implementation, run:

```bash
just install
just test tests/ace/tui/modals/test_project_management_modal.py
just check
```

If `just check` is too expensive or blocked by environment issues, record the exact failure and at least run the
targeted modal test suite.

## Risks And Tradeoffs

- Always refreshing after the editor exits may do extra work if the user closes without changes, but this key is low
  frequency and stale TUI state after manual ProjectSpec edits would be worse.
- Opening a missing ProjectSpec is useful for defaulted records, but creating missing project directories implicitly
  would be surprising. The action should only allow editor-created files when the parent project directory already
  exists.
- The edit lock is cooperative. It protects SASE writers that use the existing locking helpers, but it cannot prevent
  arbitrary external tools from editing the file at the same time.

"""Lifecycle and delete actions for the project management modal."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from textual.app import SuspendNotSupported
from textual.worker import WorkerState

from sase.ace.patch.locking import acquire_edit_lock, release_edit_lock
from sase.ace.hints import build_editor_args
from sase.ace.tui.widgets.current_project_indicator import CurrentProjectIndicator
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.current_project import SetCurrentProjectOutcome, set_current_project
from sase.main.project_handler import ProjectLifecycleBlockedError

from .confirm_action_modal import ConfirmActionModal
from .confirm_dialog import ConfirmKind
from .project_alias_editor_modal import ProjectAliasEditorModal
from .project_management_rendering import (
    bulk_delete_message,
    bulk_delete_status,
    force_state_change_message,
    state_change_status,
    truncated_project_lines,
)

if TYPE_CHECKING:
    from textual.app import App
    from textual.worker import Worker

    from sase.current_project import CurrentProject

_CURRENT_PROJECT_SET_GROUP = "current-project-set"

_SET_CURRENT_NOTIFY_SEVERITY: dict[str, Literal["information", "warning", "error"]] = {
    "set": "information",
    "unchanged": "information",
    "ineligible": "warning",
    "unverified": "error",
}


def _normalize_alias_input(aliases: Sequence[str]) -> list[str]:
    return sorted({alias.strip() for alias in aliases if alias.strip()})


class ProjectManagementActionsMixin:
    """Action handlers that mutate project lifecycle state."""

    if TYPE_CHECKING:
        _marked_projects: set[str]
        _pending_force: tuple[tuple[str, ...], str] | None
        _projects_root: Path | None
        _records: list[ProjectRecordWire]
        _status_message: str
        _current_project: CurrentProject | None
        _current_project_set_worker: Worker[Any] | None
        app: App[Any]

        def _selected_record(self) -> ProjectRecordWire | None: ...
        def _selected_project_name(self) -> str | None: ...
        def _target_records(self) -> list[ProjectRecordWire]: ...
        def _records_for_names(
            self, project_names: Sequence[str]
        ) -> list[ProjectRecordWire]: ...
        def _marked_records(self) -> list[ProjectRecordWire]: ...
        def _set_status(self, message: str) -> None: ...
        def _refresh_options(self, *, preferred_project: str | None = None) -> None: ...
        def _load_records(self) -> bool: ...
        def _start_current_project_resolve(self) -> None: ...
        def notify(self, message: str, **kwargs: Any) -> None: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Worker[Any]: ...
        def _set_project_state_locked(
            self, project: str, state: str, *, force: bool = False
        ) -> ProjectRecordWire: ...
        def _delete_project_locked(self, project: str) -> Path: ...
        def _set_project_aliases_locked(
            self, project: str, aliases: list[str]
        ) -> ProjectRecordWire: ...

    def action_set_current_project(self) -> None:
        record = self._selected_record()
        if record is None:
            self._set_status("No project selected")
            return

        display = effective_project_name(record)
        if record.state != "enabled":
            message = f"{display} is disabled; enable it first (a)"
            self._set_status(message)
            self.notify(message, severity="warning")
            return
        if not record.launchable:
            message = f"{display} has no launchable ProjectSpec"
            self._set_status(message)
            self.notify(message, severity="warning")
            return
        current = self._current_project
        if current is not None and current.project_key == record.project_name:
            self._set_status(f"{display} is already current")
            return

        project_name = record.project_name
        projects_dir = self._projects_root
        self._set_status(f"Making {display} current…")

        def task() -> SetCurrentProjectOutcome:
            return set_current_project(project_name, projects_dir=projects_dir)

        self._current_project_set_worker = self.run_worker(
            task,
            thread=True,
            exclusive=False,
            exit_on_error=False,
            group=_CURRENT_PROJECT_SET_GROUP,
        )

    def _apply_set_current_project_outcome(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.CANCELLED:
            return
        if event.state == WorkerState.ERROR:
            error = event.worker.error
            message = (
                f"Could not set current project: {error}"
                if error
                else "Could not set current project"
            )
            self._set_status(message)
            self.notify(message, severity="error")
            return
        if event.state != WorkerState.SUCCESS:
            return
        outcome = event.worker.result
        if not isinstance(outcome, SetCurrentProjectOutcome):
            message = "Could not set current project"
            self._set_status(message)
            self.notify(message, severity="error")
            return
        self._set_status(outcome.message)
        self.notify(
            outcome.message,
            severity=_SET_CURRENT_NOTIFY_SEVERITY[outcome.status],
        )
        if outcome.status == "set":
            self._start_current_project_resolve()
            self._invalidate_current_project_indicator()

    def _invalidate_current_project_indicator(self) -> None:
        try:
            self.app.query_one(CurrentProjectIndicator).invalidate()
        except Exception:
            return

    def action_enable_project(self) -> None:
        self._set_project_state("enabled")

    def action_disable_project(self) -> None:
        self._set_project_state("disabled")

    def action_activate_project(self) -> None:
        self.action_enable_project()

    def action_deactivate_project(self) -> None:
        self.action_disable_project()

    def action_archive_project(self) -> None:
        self.action_disable_project()

    def action_close_project(self) -> None:
        self.action_disable_project()

    def action_edit_project_spec(self) -> None:
        record = self._selected_record()
        if record is None:
            self._set_status("No project selected")
            self.notify("No project selected", severity="warning")
            return

        project_file_text = (record.project_file or "").strip()
        if not project_file_text:
            message = f"ProjectSpec path missing for {effective_project_name(record)}"
            self._set_status(message)
            self.notify(message, severity="error")
            return

        project_file = Path(project_file_text).expanduser()
        project_parent = project_file.parent
        if not project_parent.is_dir():
            message = f"ProjectSpec directory missing: {project_parent}"
            self._set_status(message)
            self.notify(message, severity="error")
            return

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [str(project_file)])

        try:
            acquire_edit_lock(str(project_file))
            try:
                with self.app.suspend():  # type: ignore[attr-defined]
                    subprocess.run(editor_args, check=False)
            finally:
                release_edit_lock(str(project_file))
        except (OSError, SuspendNotSupported) as exc:
            message = f"Editor failed for {effective_project_name(record)}: {exc}"
            self._set_status(message)
            self.notify(message, severity="error")
            return

        self._pending_force = None
        self._load_records()
        self._set_status(f"Editor closed for {effective_project_name(record)}")
        self._refresh_options(preferred_project=record.project_name)
        self._notify_lifecycle_changed()

    def action_edit_project_aliases(self) -> None:
        record = self._selected_record()
        if record is None:
            self._set_status("No project selected")
            self.notify("No project selected", severity="warning")
            return

        current_aliases = _normalize_alias_input(record.aliases)

        def _on_alias_editor_dismiss(aliases: list[str] | None) -> None:
            if aliases is None:
                self._set_status("Alias edit cancelled")
                return

            normalized = _normalize_alias_input(aliases)
            if normalized == current_aliases:
                self._set_status(
                    f"Aliases unchanged for {effective_project_name(record)}"
                )
                return

            if not normalized and current_aliases:

                def _on_clear_confirm(confirmed: bool | None) -> None:
                    if not confirmed:
                        self._set_status("Alias clear cancelled")
                        return
                    self._replace_project_aliases(record.project_name, [])

                self.app.push_screen(
                    ConfirmActionModal(
                        title="Clear Project Aliases",
                        message=(
                            f"Clear all aliases for '{effective_project_name(record)}'?"
                        ),
                        confirm_label="Clear",
                        cancel_label="Cancel",
                    ),
                    _on_clear_confirm,
                )
                return

            self._replace_project_aliases(record.project_name, normalized)

        self.app.push_screen(
            ProjectAliasEditorModal(effective_project_name(record), record.aliases),
            _on_alias_editor_dismiss,
        )

    def action_delete_project(self) -> None:
        if self._marked_projects:
            records = self._marked_records()
            if not records:
                self._marked_projects.clear()
                self._pending_force = None
                self._set_status("No marked projects remain")
                self._refresh_options()
                return

            project_names = tuple(record.project_name for record in records)

            def _on_bulk_delete_confirm(confirmed: bool | None) -> None:
                if not confirmed:
                    self._set_status("Delete cancelled")
                    return
                self._delete_marked_projects_confirmed(project_names)

            self.app.push_screen(
                ConfirmActionModal(
                    title="Delete Marked Project Directories",
                    message=self._bulk_delete_message(records),
                    kind=ConfirmKind.DANGER,
                    confirm_label="Delete",
                    cancel_label="Cancel",
                ),
                _on_bulk_delete_confirm,
            )
            return

        record = self._selected_record()
        if record is None:
            self._set_status("No project selected")
            return
        if record.project_name == "home" or record.system_managed:
            message = f"Project '{effective_project_name(record)}' is system-managed"
            self._set_status(message)
            self.notify(message, severity="error")
            return

        project_dir = self._project_dir_for(record)

        def _on_single_delete_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                self._set_status("Delete cancelled")
                return
            self._delete_project_confirmed(record.project_name)

        self.app.push_screen(
            ConfirmActionModal(
                title="Delete Project Directory",
                message=(
                    "Delete SASE project directory for "
                    f"'{effective_project_name(record)}'?\n\n"
                    f"{project_dir}\n\n"
                    "This removes project specs, project-local config, artifacts, "
                    "and other SASE state. It cannot be undone.\n\n"
                    "The workspace checkout is not deleted."
                ),
                kind=ConfirmKind.DANGER,
                confirm_label="Delete",
                cancel_label="Cancel",
            ),
            _on_single_delete_confirm,
        )

    def action_default_project_action(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        if record.state != "enabled":
            self._set_project_state_for_records([record], "enabled")
        else:
            self._set_status(f"{effective_project_name(record)} is already enabled")

    def action_force_current_state_change(self) -> None:
        if self._pending_force is None:
            self._set_status("No blocked disable to force")
            return
        projects, state = self._pending_force
        if len(projects) == 1 and projects[0] not in self._marked_projects:
            record = self._selected_record()
            if record is None or record.project_name != projects[0]:
                self._set_status(f"Select {projects[0]} before forcing")
                return

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                self._set_status("Force cancelled")
                return
            records = self._records_for_names(projects)
            if not records:
                self._pending_force = None
                self._set_status("No blocked projects remain")
                self._refresh_options()
                return
            self._set_project_state_for_records(records, state, force=True)

        self.app.push_screen(
            ConfirmActionModal(
                title="Force Project State Change",
                message=self._force_state_change_message(projects, state),
                kind=ConfirmKind.DANGER,
                confirm_label="Force",
                cancel_label="Cancel",
            ),
            _on_confirm,
        )

    def _set_project_state(self, state: str, *, force: bool = False) -> None:
        records = self._target_records()
        if not records:
            return
        self._set_project_state_for_records(records, state, force=force)

    def _set_project_state_for_records(
        self,
        records: Sequence[ProjectRecordWire],
        state: str,
        *,
        force: bool = False,
    ) -> None:
        if not records:
            self._set_status("No project selected")
            return

        bulk = len(records) > 1 or any(
            record.project_name in self._marked_projects for record in records
        )
        skipped: list[str] = []
        successes: list[ProjectRecordWire] = []
        blocked: list[tuple[str, ProjectLifecycleBlockedError]] = []
        failed: list[tuple[str, Exception]] = []

        for record in records:
            if record.state == state:
                skipped.append(record.project_name)
                continue
            try:
                updated = self._set_project_state_locked(
                    record.project_name,
                    state,
                    force=force,
                )
            except ProjectLifecycleBlockedError as exc:
                blocked.append((record.project_name, exc))
            except Exception as exc:
                failed.append((record.project_name, exc))
            else:
                successes.append(updated)

        cleared = set(skipped)
        cleared.update(updated.project_name for updated in successes)
        if cleared:
            self._marked_projects -= cleared

        if blocked:
            self._pending_force = (
                tuple(project for project, _exc in blocked),
                state,
            )
        else:
            self._pending_force = None

        status = self._state_change_status(
            records,
            state,
            bulk=bulk,
            skipped=skipped,
            successes=successes,
            blocked=blocked,
            failed=failed,
        )
        preferred_project = (
            successes[-1].project_name if successes else records[0].project_name
        )
        self._status_message = status

        if successes or bulk:
            self._load_records()
        self._refresh_options(preferred_project=preferred_project)

        if successes:
            self._notify_lifecycle_changed()
            if bulk:
                self.notify(f"Updated {len(successes)} marked project(s) to {state}")
            else:
                updated = successes[0]
                self.notify(
                    "Project "
                    f"'{effective_project_name(updated)}' state is now {updated.state}"
                )
        if blocked:
            self.notify(status, severity="warning")
        if failed:
            self.notify(status, severity="error")

    def _replace_project_aliases(self, project: str, aliases: list[str]) -> None:
        try:
            updated = self._set_project_aliases_locked(project, aliases)
        except Exception as exc:
            self._pending_force = None
            message = f"Alias update failed for {project}: {exc}"
            self._set_status(message)
            self.notify(message, severity="error")
            return

        self._pending_force = None
        if not self._load_records():
            self._refresh_options(preferred_project=project)
            self.notify(self._status_message, severity="error")
            return

        aliases_text = ", ".join(updated.aliases) if updated.aliases else "none"
        self._status_message = (
            f"{effective_project_name(updated)} aliases: {aliases_text}"
        )
        self._refresh_options(preferred_project=updated.project_name)
        self._notify_lifecycle_changed()
        self.notify(f"Updated aliases for '{effective_project_name(updated)}'")

    def _state_change_status(
        self,
        records: Sequence[ProjectRecordWire],
        state: str,
        *,
        bulk: bool,
        skipped: Sequence[str],
        successes: Sequence[ProjectRecordWire],
        blocked: Sequence[tuple[str, ProjectLifecycleBlockedError]],
        failed: Sequence[tuple[str, Exception]],
    ) -> str:
        return state_change_status(
            records,
            state,
            bulk=bulk,
            skipped=skipped,
            successes=successes,
            blocked=blocked,
            failed=failed,
        )

    def _force_state_change_message(
        self,
        projects: Sequence[str],
        state: str,
    ) -> str:
        return force_state_change_message(projects, state)

    def _project_dir_for(self, record: ProjectRecordWire) -> Path:
        root = (
            self._projects_root
            if self._projects_root is not None
            else sase_projects_dir()
        )
        return root.expanduser() / record.project_name

    def _truncated_project_lines(self, projects: Sequence[str]) -> list[str]:
        return truncated_project_lines(projects)

    def _bulk_delete_message(self, records: Sequence[ProjectRecordWire]) -> str:
        return bulk_delete_message(records, self._project_dir_for)

    def _delete_project_confirmed(self, project: str) -> None:
        try:
            self._delete_project_locked(project)
        except ProjectLifecycleBlockedError as exc:
            self._pending_force = None
            message = f"Blocked: {exc}"
            self._set_status(message)
            self.notify(message, severity="warning")
            return
        except Exception as exc:
            self._pending_force = None
            self._set_status(f"Delete failed: {exc}")
            self.notify(f"Project deletion failed: {exc}", severity="error")
            return

        self._pending_force = None
        self._marked_projects.discard(project)
        self._status_message = f"Deleted {project}"
        try:
            self._load_records()
        except Exception as exc:
            self._set_status(f"Deleted, reload failed: {exc}")
        self._refresh_options()
        self._notify_lifecycle_changed()
        self.notify(f"Deleted project '{project}'")

    def _delete_marked_projects_confirmed(self, project_names: Sequence[str]) -> None:
        records = self._records_for_names(project_names)
        if not records:
            self._marked_projects.clear()
            self._pending_force = None
            self._set_status("No marked projects remain")
            self._refresh_options()
            return

        deleted: list[str] = []
        blocked: list[tuple[str, ProjectLifecycleBlockedError]] = []
        failed: list[tuple[str, Exception]] = []
        for record in records:
            try:
                self._delete_project_locked(record.project_name)
            except ProjectLifecycleBlockedError as exc:
                blocked.append((record.project_name, exc))
            except Exception as exc:
                failed.append((record.project_name, exc))
            else:
                deleted.append(record.project_name)

        self._pending_force = None
        if deleted:
            self._marked_projects -= set(deleted)
        self._status_message = self._bulk_delete_status(deleted, blocked, failed)
        self._load_records()
        self._refresh_options()

        if deleted:
            self._notify_lifecycle_changed()
            self.notify(f"Deleted {len(deleted)} marked project(s)")
        if blocked:
            self.notify(self._status_message, severity="warning")
        if failed:
            self.notify(self._status_message, severity="error")

    def _bulk_delete_status(
        self,
        deleted: Sequence[str],
        blocked: Sequence[tuple[str, ProjectLifecycleBlockedError]],
        failed: Sequence[tuple[str, Exception]],
    ) -> str:
        return bulk_delete_status(deleted, blocked, failed)

    def _notify_lifecycle_changed(self) -> None:
        app = self.app
        for refresh_name in (
            "_schedule_patches_async_refresh",
            "_schedule_changespecs_async_refresh",  # legacy compatibility alias
        ):
            patch_refresh = getattr(app, refresh_name, None)
            if patch_refresh is not None:
                patch_refresh()
        for method_name, args, kwargs in (
            (
                "_schedule_agents_async_refresh",
                (),
                {"source": "project_lifecycle", "full_history": False},
            ),
            ("_schedule_axe_async_refresh", (), {}),
            ("_refresh_current_tab", (), {}),
        ):
            method = getattr(app, method_name, None)
            if method is None:
                continue
            try:
                method(*args, **kwargs)
            except TypeError:
                try:
                    method()
                except Exception:
                    pass
            except Exception:
                pass

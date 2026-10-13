"""New-project wizard, integration, show-new, help, and reload actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual import on
from textual.containers import Vertical
from textual.widgets import Button
from textual.worker import Worker, WorkerState

from sase.core.project_lifecycle_wire import effective_project_name
from sase.current_project import CurrentProject

from ._projects_pane_shared import ProjectsFilterInput

if TYPE_CHECKING:
    from textual.app import App

    from sase.ace.tui.keymaps import ProjectsPaneKeymaps
    from sase.core.project_lifecycle_wire import ProjectRecordWire

    from .config_center_session import ProjectsSubTab


def _current_project_owner(project: CurrentProject | None) -> str:
    """Return the GitHub owner encoded in a canonical project key."""

    if project is None or project.workflow_type != "gh":
        return ""
    key = project.project_key
    if not key.startswith("gh_") or "__" not in key:
        return ""
    return key.removeprefix("gh_").split("__", 1)[0]


class ProjectsPaneNewMixin(Vertical):
    """Open the New Project wizard and fold its result back into the list."""

    if TYPE_CHECKING:
        _current_project: CurrentProject | None
        _current_project_key: str | None
        _current_project_loaded: bool
        _current_project_resolve_worker: Worker[Any] | None
        _filtered_records: list[ProjectRecordWire]
        _keymaps: ProjectsPaneKeymaps
        _last_integrated_operation_id: str | None
        _last_integrated_project_key: str | None
        _pending_force: tuple[tuple[str, ...], str] | None
        _pending_new_project_open: bool
        _pending_show_project_key: str | None
        _records: list[ProjectRecordWire]
        _status_message: str
        _tag_catalog_worker: Worker[Any] | None
        _text_filter: str
        app: App[Any]
        is_mounted: bool

        def _apply_filters(self) -> None: ...

        def _invalidate_current_project_indicator(self) -> None: ...

        def _load_records(self) -> bool: ...

        def _notify_lifecycle_changed(self) -> None: ...

        def _refresh_hints(self) -> None: ...

        def _refresh_options(self, *, preferred_project: str | None = None) -> None: ...

        def _selected_project_name(self) -> str | None: ...

        def _set_status(self, message: str) -> None: ...

        def _start_current_project_resolve(self) -> None: ...

        def _start_inventory_load(self) -> None: ...

        def _switch_to_subtab(self, subtab: ProjectsSubTab) -> None: ...

        def focus_default(self) -> None: ...

        def notify(self, message: str, **kwargs: Any) -> None: ...

        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...

        def run_worker(self, *args: Any, **kwargs: Any) -> Worker[Any]: ...

    def action_focus_filter(self) -> None:
        self.query_one("#projects-filter", ProjectsFilterInput).focus()

    def action_new_project(self) -> None:
        """Open the New Project wizard and integrate its selected result."""
        needs_context = not self._current_project_loaded or (
            self._current_project is None and bool(self._current_project_key)
        )
        if needs_context:
            self._pending_new_project_open = True
            worker_state = getattr(self._current_project_resolve_worker, "state", None)
            if worker_state not in {WorkerState.PENDING, WorkerState.RUNNING}:
                self._start_current_project_resolve()
            return
        self._open_new_project_wizard()

    def _open_new_project_wizard(self) -> None:
        from .new_project_modal import NewProjectModal, NewProjectSelection

        def on_dismissed(result: object | None) -> None:
            if isinstance(result, NewProjectSelection):
                self._handle_new_project_selection(result)

        current = self._current_project
        workflow_type = current.workflow_type if current is not None else ""
        self.app.push_screen(
            NewProjectModal(
                current_workflow_type=workflow_type,
                current_project_owner=_current_project_owner(current),
            ),
            on_dismissed,
        )

    def _handle_new_project_selection(self, result: Any) -> None:
        if result.outcome in {"show", "show-project", "added"}:
            if self.is_mounted:
                self._integrate_added_project(
                    str(result.project_key or ""),
                    outcome=str(result.outcome),
                    operation_id=str(getattr(result, "operation_id", "") or ""),
                )
            return
        if result.outcome == "jump-resume" and result.row is not None:
            proc_id = str(result.row.data.get("proc_id") or "")
            opener = getattr(self.app, "_open_config_center", None)
            if callable(opener):
                if proc_id:
                    opener("procs", proc_focus_target=proc_id)
                else:
                    opener("procs")

    def _integrate_added_project(
        self,
        project_key: str,
        *,
        outcome: str = "added",
        operation_id: str = "",
    ) -> None:
        """Reload and select an added project, preserving a filter that hides it.

        Duplicate delivery of one wizard/apply operation (the durable proc
        completion plus its matching Ready dismissal) integrates once. A later
        independent ``show``, ``show-project``, or ``added`` outcome for the
        same key reloads and selects again.
        """
        if not self.is_mounted:
            return
        if (
            operation_id
            and project_key
            and project_key == self._last_integrated_project_key
            and operation_id == self._last_integrated_operation_id
        ):
            return
        if project_key:
            self._last_integrated_project_key = project_key
            self._last_integrated_operation_id = operation_id
        self._switch_to_subtab("projects")
        self._pending_force = None
        loaded = self._load_records()
        self._invalidate_current_project_indicator()
        self._notify_lifecycle_changed()
        self._warm_project_tag_catalog()
        self._start_inventory_load()
        self._start_current_project_resolve()
        if not loaded:
            self._refresh_options()
            return

        visible_keys = {record.project_name for record in self._filtered_records}
        known_keys = {record.project_name for record in self._records}
        if (
            project_key in known_keys
            and self._text_filter.strip()
            and project_key not in visible_keys
        ):
            self._pending_show_project_key = project_key
            self._set_status("New project is hidden by the current filter")
            self._set_show_new_project_action(True)
            self._refresh_options(preferred_project=self._selected_project_name())
            return

        self._pending_show_project_key = None
        self._set_show_new_project_action(False)
        if outcome == "show-project":
            display = project_key
            for record in self._records:
                if record.project_name == project_key:
                    display = effective_project_name(record)
                    break
            self._set_status(f"Showing {display}")
        else:
            self._set_status("Project added")
        self._refresh_options(preferred_project=project_key or None)

    def _warm_project_tag_catalog(self) -> None:
        worker = self._tag_catalog_worker
        if worker is not None and worker.state in {
            WorkerState.PENDING,
            WorkerState.RUNNING,
        }:
            return
        from sase.project_tags import ensure_project_tag_catalog

        self._tag_catalog_worker = self.run_worker(
            ensure_project_tag_catalog,
            thread=True,
            exclusive=True,
            exit_on_error=False,
            group="project-tag-catalog",
        )

    def _set_show_new_project_action(self, visible: bool) -> None:
        try:
            self.query_one("#projects-show-new-project", Button).display = visible
        except Exception:
            pass
        self._refresh_hints()

    def action_help(self) -> None:
        from .projects_help_modal import ProjectsHelpModal

        self.app.push_screen(ProjectsHelpModal(keymaps=self._keymaps))

    def action_show_new_project(self) -> None:
        project_key = self._pending_show_project_key
        if not project_key:
            return
        self._pending_show_project_key = None
        self._set_show_new_project_action(False)
        self._text_filter = ""
        try:
            self.query_one("#projects-filter", ProjectsFilterInput).value = ""
        except Exception:
            pass
        self._apply_filters()
        self._set_status("Showing new project")
        self._refresh_options(preferred_project=project_key)
        self.focus_default()

    @on(Button.Pressed, "#projects-show-new-project")
    def _on_show_new_project_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_show_new_project()

    def _preferred_project_after_filter(self) -> str | None:
        key = self._pending_show_project_key
        if key is None:
            return None
        if any(record.project_name == key for record in self._filtered_records):
            self._pending_show_project_key = None
            self._set_show_new_project_action(False)
            self._set_status("Showing new project")
            return key
        return None

    def action_reload_projects(self) -> None:
        self._reload_projects()

    def _reload_projects(self, *, preferred_project: str | None = None) -> None:
        if preferred_project and self._text_filter:
            self._text_filter = ""
            try:
                self.query_one("#projects-filter", ProjectsFilterInput).value = ""
            except Exception:
                pass
            self._apply_filters()
        selected = preferred_project or self._selected_project_name()
        if not self._load_records():
            self._pending_force = None
            self._refresh_options(preferred_project=selected)
            self.notify(self._status_message, severity="error")
            self._start_current_project_resolve()
            return
        self._pending_force = None
        self._set_status("Reloaded")
        self._refresh_options(preferred_project=selected)
        self._start_inventory_load()
        self._start_current_project_resolve()

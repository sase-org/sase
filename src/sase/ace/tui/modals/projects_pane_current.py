"""Current-project display, session storage, and inventory-filter seeding."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.current_project import CurrentProject

from ._projects_pane_shared import CurrentProjectSnapshot
from .project_inventory_panes import RepoInventoryPane, WorkspaceInventoryPane

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase

    from sase.core.project_lifecycle_wire import ProjectRecordWire

    from .config_center_session import ProjectsSessionState
else:
    _MixinBase = object


class ProjectsPaneCurrentMixin(_MixinBase):
    """Apply current-project resolve results without yanking the highlight."""

    if TYPE_CHECKING:
        _current_project: CurrentProject | None
        _current_project_key: str | None
        _current_project_name: str | None
        _current_project_accent: str
        _current_project_loaded: bool
        _pending_new_project_open: bool
        _records: list[ProjectRecordWire]
        _session_state: ProjectsSessionState

        def _refresh_options(self, *, preferred_project: str | None = None) -> None: ...

        def _selected_project_name(self) -> str | None: ...

        def _open_new_project_wizard(self) -> None: ...

        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...

    def _store_current_project_session(self) -> None:
        self._session_state.current_project_key = self._current_project_key
        self._session_state.current_project_name = self._current_project_name
        self._session_state.current_project_accent = self._current_project_accent

    def _apply_current_project_display(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.CANCELLED:
            return
        if event.state != WorkerState.SUCCESS:
            if not self._current_project_loaded:
                self._current_project_loaded = True
                self._repaint_for_current_project()
            self._open_pending_new_project()
            return
        result = event.worker.result
        if isinstance(result, CurrentProjectSnapshot):
            project = result.project
            self._current_project = project
            self._current_project_key = None if project is None else project.project_key
            self._current_project_name = (
                None if project is None else project.display_name
            )
            self._current_project_accent = result.accent
        else:
            self._current_project = None
            self._current_project_key = None
            self._current_project_name = None
            self._current_project_accent = ""
        self._current_project_loaded = True
        self._store_current_project_session()
        self._repaint_for_current_project()
        self._open_pending_new_project()

    def _open_pending_new_project(self) -> None:
        if not self._pending_new_project_open or not self._current_project_loaded:
            return
        self._pending_new_project_open = False
        self._open_new_project_wizard()

    def _repaint_for_current_project(self) -> None:
        """Repaint for a resolve without moving the user's highlighted row.

        The resolve lands whenever its thread finishes, which can be before
        the pane has handled the ``OptionHighlighted`` message for a row the
        user just moved to. A bare ``_refresh_options()`` would fall back to
        the stale session bookmark and yank the highlight back, so pin the
        live highlight the way the inventory worker's completion does.
        """

        self._refresh_options(preferred_project=self._selected_project_name())

    def _apply_current_project_seed(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        if self._session_state.project_filter_seeded:
            return
        self._session_state.project_filter_seeded = True
        result = event.worker.result if event.state == WorkerState.SUCCESS else None
        project = result.project if isinstance(result, CurrentProjectSnapshot) else None
        if not isinstance(project, CurrentProject):
            return
        project_key = project.project_key
        if project_key not in {record.project_name for record in self._records}:
            return
        try:
            repos_pane = self.query_one(RepoInventoryPane)
            if repos_pane.project_filter is None:
                repos_pane.set_project_filter(project_key)
        except Exception:
            pass
        try:
            workspaces_pane = self.query_one(WorkspaceInventoryPane)
            if workspaces_pane.project_filter is None:
                workspaces_pane.set_project_filter(project_key)
        except Exception:
            pass

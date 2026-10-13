"""Projects-pane sub-tab switching, cycling, and inventory project picker."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual import on
from textual.containers import Vertical
from textual.widgets import ContentSwitcher

from sase.core.project_lifecycle_wire import effective_project_name

from ._projects_pane_shared import SUBTAB_ORDER, SUBTAB_WIDGET_IDS
from .config_center_session import ProjectsSubTab
from .inventory_project_picker import (
    InventoryProjectChoice,
    InventoryProjectPicker,
    InventoryProjectPickerResult,
)
from .pane_entry_jump import PaneEntryJumpMixin
from .project_inventory_pane_base import InventoryProjectFilterRequested
from .project_inventory_panes import RepoInventoryPane, WorkspaceInventoryPane
from ..widgets.panel_tab_strip import PanelTabStrip

if TYPE_CHECKING:
    from textual.app import App

    from sase.core.project_lifecycle_wire import ProjectRecordWire

    from .config_center_session import ProjectsSessionState
    from .project_management_rendering import ProjectInventoryCounts


class ProjectsPaneSubtabsMixin(Vertical):
    """Drive the projects / repos / workspaces sub-tab strip."""

    if TYPE_CHECKING:
        _records: list[ProjectRecordWire]
        _active_subtab: ProjectsSubTab
        _session_state: ProjectsSessionState
        app: App[Any]
        jump_mode_active: bool

        def _counts_for(self, record: ProjectRecordWire) -> ProjectInventoryCounts: ...

        def _selected_record(self) -> ProjectRecordWire | None: ...

        def _set_status(self, message: str) -> None: ...

        def exit_jump_mode(self) -> None: ...

        def focus_default(self) -> None: ...

        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...

    @on(PanelTabStrip.TabClicked)
    def _on_subtab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        event.stop()
        if event.tab_id in SUBTAB_ORDER:
            self._switch_to_subtab(cast(ProjectsSubTab, event.tab_id))

    @on(InventoryProjectFilterRequested)
    def _on_inventory_project_filter_requested(
        self,
        event: InventoryProjectFilterRequested,
    ) -> None:
        event.stop()
        self._open_project_picker(event.pane)

    def _open_project_picker(
        self,
        pane: RepoInventoryPane | WorkspaceInventoryPane,
    ) -> None:
        choices: list[InventoryProjectChoice] = []
        for record in self._records:
            counts = self._counts_for(record)
            display = effective_project_name(record)
            if display != record.project_name:
                display = f"{display} ({record.project_name})"
            choices.append(
                InventoryProjectChoice(
                    project_key=record.project_name,
                    display_name=display,
                    state=record.state,
                    repo_count=counts.repo_count,
                    workspace_count=counts.workspace_count,
                )
            )

        def on_picked(result: InventoryProjectPickerResult | None) -> None:
            if result is not None:
                pane.set_project_filter(result.project_key)
                pane.focus_default()

        self.app.push_screen(
            InventoryProjectPicker(
                choices,
                current_project=pane.project_filter,
            ),
            on_picked,
        )

    def _exit_subtab_jump_modes(self) -> None:
        """Drop any painted hints so a sub-tab switch cannot strand them."""

        panes: list[PaneEntryJumpMixin] = [cast(PaneEntryJumpMixin, self)]
        try:
            panes.append(self.query_one(RepoInventoryPane))
            panes.append(self.query_one(WorkspaceInventoryPane))
        except Exception:
            pass
        for pane in panes:
            if pane.jump_mode_active:
                pane.exit_jump_mode()

    def _switch_to_subtab(self, subtab: ProjectsSubTab) -> None:
        self._exit_subtab_jump_modes()
        self._active_subtab = subtab
        self._session_state.active_subtab = subtab
        try:
            self.query_one(
                "#projects-subtab-switcher", ContentSwitcher
            ).current = SUBTAB_WIDGET_IDS[subtab]
            self.query_one("#projects-subtabs", PanelTabStrip).set_active_tab(subtab)
        except Exception:
            return
        self.focus_default()

    def _set_repos_project_filter(self, project_key: str | None) -> None:
        self._session_state.repos_project_filter = project_key

    def _set_workspaces_project_filter(self, project_key: str | None) -> None:
        self._session_state.workspaces_project_filter = project_key

    def _cycle_subtab(self, step: int) -> None:
        index = SUBTAB_ORDER.index(self._active_subtab)
        self._switch_to_subtab(SUBTAB_ORDER[(index + step) % len(SUBTAB_ORDER)])

    def action_cycle_subtab(self) -> None:
        self._cycle_subtab(1)

    def action_cycle_subtab_reverse(self) -> None:
        self._cycle_subtab(-1)

    def _show_selected_project_inventory(self, subtab: ProjectsSubTab) -> None:
        record = self._selected_record()
        if record is None:
            self._set_status("No project selected")
            return
        if subtab == "repos":
            pane: RepoInventoryPane | WorkspaceInventoryPane = self.query_one(
                RepoInventoryPane
            )
        else:
            pane = self.query_one(WorkspaceInventoryPane)
        pane.set_project_filter(record.project_name)
        self._switch_to_subtab(subtab)

    def action_show_project_repos(self) -> None:
        self._show_selected_project_inventory("repos")

    def action_show_project_workspaces(self) -> None:
        self._show_selected_project_inventory("workspaces")

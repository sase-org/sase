"""Projects, repositories, and workspaces pane for the SASE Admin Center."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.worker import Worker, WorkerState
from textual.widgets import ContentSwitcher, OptionList, Static

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.main.project_handler import (
    ProjectLifecycleBlockedError,
    delete_project_locked,
    set_project_aliases_locked,
    set_project_state_locked,
)

from .base import FilterInput, OptionListNavigationMixin
from .config_center_session import ProjectsSessionState, ProjectsSubTab
from .inventory_project_picker import (
    InventoryProjectChoice,
    InventoryProjectPicker,
    InventoryProjectPickerResult,
)
from .project_management_actions import ProjectManagementActionsMixin
from .project_inventory_counts import (
    ProjectCountsLoadResult,
    collect_project_inventory_counts,
)
from .project_list_controller import ProjectListControllerMixin
from .project_management_rendering import (
    ProjectInventoryCounts,
    column_header_text,
)
from .project_inventory_panes import (
    InventoryProjectFilterRequested,
    RepoInventoryPane,
    WorkspaceInventoryPane,
)
from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip

_SUBTAB_ORDER: tuple[ProjectsSubTab, ...] = (
    "projects",
    "repos",
    "workspaces",
)
_SUBTAB_WIDGET_IDS: dict[ProjectsSubTab, str] = {
    "projects": "projects-subtab-projects",
    "repos": "projects-subtab-repos",
    "workspaces": "projects-subtab-workspaces",
}
_SUBTABS: tuple[PanelTab, ...] = tuple(
    PanelTab(tab, tab.title(), "#FFAF5F") for tab in _SUBTAB_ORDER
)
_PendingForce = tuple[tuple[str, ...], str]


class _ProjectsFilterInput(FilterInput):
    """Filter input that forwards printable sub-tab cycle keys."""

    def on_key(self, event: events.Key) -> None:
        if event.key in ("left_square_bracket", "right_square_bracket"):
            pane = self._pane()
            if pane is not None:
                event.stop()
                event.prevent_default()
                if event.key == "left_square_bracket":
                    pane.action_cycle_subtab_reverse()
                else:
                    pane.action_cycle_subtab()

    def _pane(self) -> ProjectsPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, ProjectsPane):
                return node
            node = getattr(node, "parent", None)
        return None


class ProjectsPane(
    ProjectManagementActionsMixin,
    ProjectListControllerMixin,
    OptionListNavigationMixin,
    Vertical,
):
    """Manage true SASE projects and host related inventory sub-tabs."""

    _option_list_id = "projects-list"
    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("/", "focus_filter", "Filter"),
        ("right_square_bracket", "cycle_subtab", "Next Sub-tab"),
        ("left_square_bracket", "cycle_subtab_reverse", "Previous Sub-tab"),
        ("m", "toggle_project_mark", "Mark"),
        ("u", "clear_project_marks", "Unmark All"),
        ("e", "edit_project_spec", "Edit"),
        ("A", "edit_project_aliases", "Aliases"),
        ("a", "enable_project", "Enable"),
        ("d", "disable_project", "Disable"),
        ("ctrl+d", "delete_project", "Delete"),
        ("F", "force_current_state_change", "Force"),
        ("enter", "default_project_action", "Default"),
        ("R", "reload_projects", "Reload"),
        ("r", "show_project_repos", "Project Repos"),
        ("w", "show_project_workspaces", "Project Workspaces"),
    ]

    _PROJECT_ONLY_ACTIONS = frozenset(
        {
            "next_option",
            "prev_option",
            "focus_filter",
            "toggle_project_mark",
            "clear_project_marks",
            "edit_project_spec",
            "edit_project_aliases",
            "enable_project",
            "disable_project",
            "delete_project",
            "force_current_state_change",
            "default_project_action",
            "reload_projects",
            "show_project_repos",
            "show_project_workspaces",
        }
    )

    def __init__(
        self,
        projects_root: Path | None = None,
        *,
        session_state: ProjectsSessionState | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._projects_root = projects_root
        self._session_state = session_state or ProjectsSessionState()
        self._records: list[ProjectRecordWire] = []
        self._filtered_records: list[ProjectRecordWire] = []
        self._active_subtab: ProjectsSubTab = self._session_state.active_subtab
        self._text_filter = ""
        self._status_message = ""
        self._marked_projects: set[str] = set()
        self._pending_force: _PendingForce | None = None
        self._inventory_counts: dict[str, ProjectInventoryCounts] = {}
        self._inventory_loading = False
        self._inventory_error = ""
        self._inventory_worker: Worker[Any] | None = None
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._project_selection_guard = ProgrammaticSelectionGuard()
        self._load_records()
        self._inventory_loading = bool(self._records)

    def compose(self) -> ComposeResult:
        yield PanelTabStrip(
            _SUBTABS,
            self._active_subtab,
            uppercase_active=True,
            id="projects-subtabs",
        )
        with ContentSwitcher(
            initial=_SUBTAB_WIDGET_IDS[self._active_subtab],
            id="projects-subtab-switcher",
        ):
            with Vertical(id=_SUBTAB_WIDGET_IDS["projects"]):
                yield Static(self._summary_text(), id="projects-summary")
                yield _ProjectsFilterInput(
                    placeholder="Type to filter projects...",
                    id="projects-filter",
                )
                projects_box = Vertical(id="projects-box")
                projects_box.border_title = "Projects"
                with projects_box:
                    yield Static(column_header_text(), id="projects-columns")
                    yield OptionList(
                        *self._create_options(self._filtered_records),
                        id=self._option_list_id,
                    )
                detail_box = VerticalScroll(id="projects-detail-scroll")
                detail_box.border_title = "Details"
                with detail_box:
                    yield Static("", id="projects-detail")
                yield Static(self._hints_text(), id="projects-hints")
            yield RepoInventoryPane(
                projects_root=self._projects_root,
                project_records=self._records,
                bookmark=self._session_state.repos,
                project_filter=self._session_state.repos_project_filter,
                on_project_filter_changed=self._set_repos_project_filter,
                id=_SUBTAB_WIDGET_IDS["repos"],
            )
            yield WorkspaceInventoryPane(
                projects_root=self._projects_root,
                project_records=self._records,
                bookmark=self._session_state.workspaces,
                project_filter=self._session_state.workspaces_project_filter,
                on_project_filter_changed=self._set_workspaces_project_filter,
                id=_SUBTAB_WIDGET_IDS["workspaces"],
            )

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._refresh_options()
        self._start_inventory_load()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self._active_subtab != "projects" and action in self._PROJECT_ONLY_ACTIONS:
            return False
        return super().check_action(action, parameters)

    def focus_default(self) -> None:
        """Focus the active sub-tab's browse surface."""

        try:
            if self._active_subtab == "projects":
                self.query_one(f"#{self._option_list_id}", OptionList).focus()
            elif self._active_subtab == "repos":
                self.query_one(RepoInventoryPane).focus_default()
            else:
                self.query_one(WorkspaceInventoryPane).focus_default()
        except Exception:
            pass

    def _projects_root_path(self) -> Path:
        return self._projects_root or sase_projects_dir()

    def _load_records(self) -> bool:
        try:
            records = list_project_records(
                self._projects_root_path(),
                "all",
                include_home=False,
                projects_only=True,
            )
        except Exception as exc:
            self._records = []
            self._filtered_records = []
            self._status_message = f"Load failed: {exc}"
            return False
        self._records = sorted(
            (
                record
                for record in records
                if record.is_project
                and record.project_name != "home"
                and not record.system_managed
            ),
            # Rust discovery already provides deterministic project ordering;
            # keep that stable while grouping disabled rows after enabled ones.
            key=lambda record: record.state == "disabled",
        )
        live_keys = {record.project_name for record in self._records}
        self._inventory_counts = {
            key: value
            for key, value in self._inventory_counts.items()
            if key in live_keys
        }
        self._prune_stale_marked_projects()
        self._apply_filters()
        self._sync_inventory_project_records()
        return True

    def _sync_inventory_project_records(self) -> None:
        """Update mounted inventory panes after lifecycle records change."""

        try:
            self.query_one(RepoInventoryPane).set_project_records(self._records)
        except Exception:
            pass
        try:
            self.query_one(WorkspaceInventoryPane).set_project_records(self._records)
        except Exception:
            pass

    def _start_inventory_load(self) -> None:
        if not self._records:
            self._inventory_loading = False
            self._inventory_error = ""
            self._update_summary()
            return
        self._inventory_loading = True
        self._inventory_error = ""
        self._update_summary()
        projects_root = self._projects_root_path()
        records = tuple(self._records)

        def task() -> ProjectCountsLoadResult:
            return collect_project_inventory_counts(projects_root, records)

        self._inventory_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            exit_on_error=False,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._inventory_worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._inventory_loading = False
            if isinstance(result, ProjectCountsLoadResult):
                self._inventory_counts = result.counts
                self._inventory_error = "; ".join(result.errors)
            else:
                self._inventory_error = "inventory returned no result"
            selected = self._selected_project_name()
            self._refresh_options(preferred_project=selected)
        elif event.state == WorkerState.ERROR:
            self._inventory_loading = False
            self._inventory_error = (
                str(event.worker.error)
                if event.worker.error
                else "inventory load failed"
            )
            self._update_summary()

    def _set_project_state_locked(
        self,
        project: str,
        state: str,
        *,
        force: bool = False,
    ) -> ProjectRecordWire:
        return set_project_state_locked(project, state, force=force)

    def _delete_project_locked(self, project: str) -> Path:
        return delete_project_locked(project, projects_root=self._projects_root)

    def _set_project_aliases_locked(
        self,
        project: str,
        aliases: list[str],
    ) -> ProjectRecordWire:
        return set_project_aliases_locked(
            project,
            aliases,
            projects_root=self._projects_root,
        )

    @on(PanelTabStrip.TabClicked)
    def _on_subtab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        event.stop()
        if event.tab_id in _SUBTAB_ORDER:
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

    def _switch_to_subtab(self, subtab: ProjectsSubTab) -> None:
        self._active_subtab = subtab
        self._session_state.active_subtab = subtab
        try:
            self.query_one(
                "#projects-subtab-switcher", ContentSwitcher
            ).current = _SUBTAB_WIDGET_IDS[subtab]
            self.query_one("#projects-subtabs", PanelTabStrip).set_active_tab(subtab)
        except Exception:
            return
        self.focus_default()

    def _set_repos_project_filter(self, project_key: str | None) -> None:
        self._session_state.repos_project_filter = project_key

    def _set_workspaces_project_filter(self, project_key: str | None) -> None:
        self._session_state.workspaces_project_filter = project_key

    def _cycle_subtab(self, step: int) -> None:
        index = _SUBTAB_ORDER.index(self._active_subtab)
        self._switch_to_subtab(_SUBTAB_ORDER[(index + step) % len(_SUBTAB_ORDER)])

    def action_cycle_subtab(self) -> None:
        self._cycle_subtab(1)

    def action_cycle_subtab_reverse(self) -> None:
        self._cycle_subtab(-1)

    def action_focus_filter(self) -> None:
        self.query_one("#projects-filter", _ProjectsFilterInput).focus()

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

    def action_reload_projects(self) -> None:
        selected = self._selected_project_name()
        if not self._load_records():
            self._pending_force = None
            self._refresh_options(preferred_project=selected)
            self.notify(self._status_message, severity="error")
            return
        self._pending_force = None
        self._set_status("Reloaded")
        self._refresh_options(preferred_project=selected)
        self._start_inventory_load()


__all__ = [
    "ProjectLifecycleBlockedError",
    "ProjectsPane",
    "ProjectsSubTab",
    "ProjectCountsLoadResult",
    "collect_project_inventory_counts",
    "delete_project_locked",
    "list_project_records",
    "set_project_aliases_locked",
    "set_project_state_locked",
]

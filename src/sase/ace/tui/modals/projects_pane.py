"""Projects, repositories, and workspaces pane for the SASE Admin Center."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Vertical, VerticalScroll
from textual.worker import Worker, WorkerState
from textual.widgets import Button, ContentSwitcher, OptionList, Static

from sase.ace.tui.keymaps import (
    ProjectsPaneKeymaps,
    build_projects_bindings,
    load_keymap_registry,
    split_key_alternatives,
)
from sase.project_accents import accent_among_keys, project_accent
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
from sase.core.paths import sase_projects_dir
from sase.current_project import CurrentProject, resolve_current_project
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.macro.loader import get_known_project_workspaces
from sase.main.project_handler import (
    ProjectLifecycleBlockedError,
    delete_project_locked,
    set_project_aliases_locked,
    set_project_state_locked,
)

from ..actions.navigation.jump_hints import normalize_jump_key
from ._projects_pane_shared import (
    SUBTAB_WIDGET_IDS,
    SUBTABS,
    CurrentProjectSnapshot,
    ProjectsFilterInput,
)
from .base import OptionListNavigationMixin
from .config_center_session import ProjectsSessionState, ProjectsSubTab
from .project_management_actions import ProjectManagementActionsMixin
from .projects_pane_current import ProjectsPaneCurrentMixin
from .projects_pane_init_actions import ProjectsPaneInitActionsMixin
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
    RepoInventoryPane,
    WorkspaceInventoryPane,
)
from .projects_pane_new import ProjectsPaneNewMixin
from .projects_pane_subtabs import ProjectsPaneSubtabsMixin
from ..widgets.panel_tab_strip import PanelTabStrip

_PendingForce = tuple[tuple[str, ...], str]
_CURRENT_PROJECT_RESOLVE_GROUP = "current-project-resolve"


def _resolve_current_project_snapshot() -> CurrentProjectSnapshot:
    """Resolve the current project and its accent off the UI thread."""

    try:
        project = resolve_current_project()
        accent = ""
        if project is not None:
            try:
                records = list_project_records(sase_projects_dir(), "all")
                among: tuple[str, ...] = accent_among_keys(records)
            except Exception:  # noqa: BLE001 - display reads always degrade.
                among = tuple(get_known_project_workspaces())
            accent = project_accent(project.project_key, among=among)
    except Exception:  # noqa: BLE001 - display reads always degrade.
        return CurrentProjectSnapshot(project=None, accent="")
    return CurrentProjectSnapshot(project=project, accent=accent)


class ProjectsPane(
    ProjectsPaneNewMixin,
    ProjectsPaneSubtabsMixin,
    ProjectsPaneCurrentMixin,
    ProjectsPaneInitActionsMixin,
    ProjectManagementActionsMixin,
    ProjectListControllerMixin,
    OptionListNavigationMixin,
    Vertical,
):
    """Manage true SASE projects and host related inventory sub-tabs."""

    _option_list_id = "projects-list"
    BINDINGS = []

    _PROJECT_ONLY_ACTIONS = frozenset(
        {
            "jump_to_entry",
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
            "set_current_project",
            "initialize_project",
            "initialize_all_projects",
            "new_project",
            "help",
            "show_new_project",
        }
    )

    def __init__(
        self,
        projects_root: Path | None = None,
        *,
        session_state: ProjectsSessionState | None = None,
        keymaps: ProjectsPaneKeymaps | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._keymaps = keymaps or load_keymap_registry({}).projects
        self._bindings = BindingsMap(build_projects_bindings(self._keymaps))
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
        self._current_project: CurrentProject | None = None
        self._current_project_key = self._session_state.current_project_key
        self._current_project_name = self._session_state.current_project_name
        self._current_project_accent = self._session_state.current_project_accent
        self._current_project_loaded = bool(
            self._current_project_key or self._current_project_name
        )
        self._current_project_resolve_worker: Worker[Any] | None = None
        self._current_project_set_worker: Worker[Any] | None = None
        self._tag_catalog_worker: Worker[Any] | None = None
        self._pending_new_project_open = False
        self._pending_show_project_key: str | None = None
        self._last_integrated_project_key: str | None = None
        self._last_integrated_operation_id: str | None = None
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._project_selection_guard = ProgrammaticSelectionGuard()
        self._load_records()
        self._inventory_loading = bool(self._records)

    def compose(self) -> ComposeResult:
        yield PanelTabStrip(
            SUBTABS,
            self._active_subtab,
            uppercase_active=True,
            id="projects-subtabs",
        )
        with ContentSwitcher(
            initial=SUBTAB_WIDGET_IDS[self._active_subtab],
            id="projects-subtab-switcher",
        ):
            with Vertical(id=SUBTAB_WIDGET_IDS["projects"]):
                yield Static(self._summary_text(), id="projects-summary")
                yield Button(
                    "Show new project",
                    id="projects-show-new-project",
                    variant="primary",
                )
                yield ProjectsFilterInput(
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
                keymaps=self._keymaps,
                id=SUBTAB_WIDGET_IDS["repos"],
            )
            yield WorkspaceInventoryPane(
                projects_root=self._projects_root,
                project_records=self._records,
                bookmark=self._session_state.workspaces,
                project_filter=self._session_state.workspaces_project_filter,
                on_project_filter_changed=self._set_workspaces_project_filter,
                keymaps=self._keymaps,
                id=SUBTAB_WIDGET_IDS["workspaces"],
            )

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self.query_one("#projects-show-new-project", Button).display = False
        self._refresh_options()
        self._start_inventory_load()
        self._start_current_project_resolve()

    def on_resize(self, _event: events.Resize) -> None:
        self._refresh_hints()

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        if self._current_project_resolve_worker is not None:
            self._current_project_resolve_worker.cancel()
        if self._current_project_set_worker is not None:
            self._current_project_set_worker.cancel()
        if self._tag_catalog_worker is not None:
            self._tag_catalog_worker.cancel()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self._active_subtab != "projects" and action in self._PROJECT_ONLY_ACTIONS:
            return False
        if action in {"new_project", "show_new_project"} and self._filter_has_focus():
            return False
        if action == "show_new_project" and not self._pending_show_project_key:
            return False
        return super().check_action(action, parameters)

    def on_key(self, event: events.Key) -> None:
        """Drive hint jump mode over the projects sub-tab's own rows."""

        if self._active_subtab != "projects" or self._filter_has_focus():
            return
        if self.jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if self.handle_jump_key(key):
                event.prevent_default()
                event.stop()
                return
        if event.key in split_key_alternatives(self._keymaps.jump_to_entry):
            event.prevent_default()
            event.stop()
            self.action_jump_to_entry()

    def _filter_has_focus(self) -> bool:
        try:
            return self.query_one("#projects-filter", ProjectsFilterInput).has_focus
        except Exception:
            return False

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

    def _start_current_project_resolve(self) -> None:
        """Resolve the current project off-thread for display (and first seed)."""

        settings = getattr(self.app, "_current_project_settings", None)
        if (
            not self._session_state.project_filter_seeded
            and settings is not None
            and not getattr(settings, "seed_filters", True)
        ):
            self._session_state.project_filter_seeded = True
        if self._current_project_resolve_worker is not None:
            self._current_project_resolve_worker.cancel()
        self._current_project_resolve_worker = self.run_worker(
            _resolve_current_project_snapshot,
            thread=True,
            exclusive=False,
            exit_on_error=False,
            group=_CURRENT_PROJECT_RESOLVE_GROUP,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._current_project_set_worker:
            self._apply_set_current_project_outcome(event)
            return
        if event.worker is self._current_project_resolve_worker:
            self._apply_current_project_display(event)
            self._apply_current_project_seed(event)
            return
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

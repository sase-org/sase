"""Projects, repositories, and workspaces pane for the SASE Admin Center."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from textual import events, on
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
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.macro.loader import get_known_project_workspaces
from sase.main.project_handler import (
    ProjectLifecycleBlockedError,
    delete_project_locked,
    set_project_aliases_locked,
    set_project_state_locked,
)

from ..actions.navigation.jump_hints import normalize_jump_key
from .base import FilterInput, OptionListNavigationMixin
from .config_center_session import ProjectsSessionState, ProjectsSubTab
from .pane_entry_jump import PaneEntryJumpMixin
from .inventory_project_picker import (
    InventoryProjectChoice,
    InventoryProjectPicker,
    InventoryProjectPickerResult,
)
from .project_management_actions import ProjectManagementActionsMixin
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
from .project_inventory_pane_base import InventoryProjectFilterRequested
from .project_inventory_panes import (
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
_CURRENT_PROJECT_RESOLVE_GROUP = "current-project-resolve"


@dataclass(frozen=True, slots=True)
class _CurrentProjectSnapshot:
    """Resolved current project plus the accent computed off-thread."""

    project: CurrentProject | None
    accent: str


def _resolve_current_project_snapshot() -> _CurrentProjectSnapshot:
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
        return _CurrentProjectSnapshot(project=None, accent="")
    return _CurrentProjectSnapshot(project=project, accent=accent)


def _current_project_owner(project: CurrentProject | None) -> str:
    """Return the GitHub owner encoded in a canonical project key."""

    if project is None or project.workflow_type != "gh":
        return ""
    key = project.project_key
    if not key.startswith("gh_") or "__" not in key:
        return ""
    return key.removeprefix("gh_").split("__", 1)[0]


class _ProjectsFilterInput(FilterInput):
    """Filter input that forwards printable sub-tab cycle keys."""

    def on_key(self, event: events.Key) -> None:
        pane = self._pane()
        if pane is None:
            return
        if event.key in split_key_alternatives(pane._keymaps.cycle_subtab_reverse):
            event.stop()
            event.prevent_default()
            pane.action_cycle_subtab_reverse()
        elif event.key in split_key_alternatives(pane._keymaps.cycle_subtab):
            event.stop()
            event.prevent_default()
            pane.action_cycle_subtab()

    def _pane(self) -> ProjectsPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, ProjectsPane):
                return node
            node = getattr(node, "parent", None)
        return None


class ProjectsPane(
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
                yield Button(
                    "Show new project",
                    id="projects-show-new-project",
                    variant="primary",
                )
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
                keymaps=self._keymaps,
                id=_SUBTAB_WIDGET_IDS["repos"],
            )
            yield WorkspaceInventoryPane(
                projects_root=self._projects_root,
                project_records=self._records,
                bookmark=self._session_state.workspaces,
                project_filter=self._session_state.workspaces_project_filter,
                on_project_filter_changed=self._set_workspaces_project_filter,
                keymaps=self._keymaps,
                id=_SUBTAB_WIDGET_IDS["workspaces"],
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
            return self.query_one("#projects-filter", _ProjectsFilterInput).has_focus
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
        if isinstance(result, _CurrentProjectSnapshot):
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
        project = (
            result.project if isinstance(result, _CurrentProjectSnapshot) else None
        )
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

    def _exit_subtab_jump_modes(self) -> None:
        """Drop any painted hints so a sub-tab switch cannot strand them."""

        panes: list[PaneEntryJumpMixin] = [self]
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
            self.query_one("#projects-filter", _ProjectsFilterInput).value = ""
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
                self.query_one("#projects-filter", _ProjectsFilterInput).value = ""
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

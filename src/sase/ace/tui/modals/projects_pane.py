"""Projects, repositories, and workspaces pane for the SASE Admin Center."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.worker import Worker, WorkerState
from textual.widgets import ContentSwitcher, Input, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.main.project_handler import (
    ProjectLifecycleBlockedError,
    delete_project_locked,
    set_project_aliases_locked,
    set_project_state_locked,
)
from sase.repo_inventory import collect_repo_inventory
from sase.workspace_provider.inventory import collect_workspace_inventory

from .base import FilterInput, OptionListNavigationMixin
from .project_management_actions import ProjectManagementActionsMixin
from .project_management_rendering import (
    ProjectInventoryCounts,
    column_header_text,
    detail_text,
    hints_text,
    record_label,
    summary_text,
)
from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip

ProjectsSubTab = Literal["projects", "repos", "workspaces"]
_DEFAULT_SUBTAB: ProjectsSubTab = "projects"
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


@dataclass(frozen=True)
class _ProjectCountsLoadResult:
    counts: dict[str, ProjectInventoryCounts]
    errors: tuple[str, ...] = ()


def _collect_project_inventory_counts(
    projects_root: Path,
    project_records: Sequence[ProjectRecordWire],
) -> _ProjectCountsLoadResult:
    """Join Phase-3 repo/workspace inventories into per-project aggregates."""

    project_keys = {record.project_name for record in project_records}
    project_lookup: dict[str, str] = {}
    for record in project_records:
        for name in (
            record.project_name,
            effective_project_name(record),
            *record.aliases,
        ):
            project_lookup.setdefault(name, record.project_name)

    repo_kind_counts: dict[str, dict[str, int]] = {
        key: {"primary": 0, "sidecar": 0, "linked": 0} for key in project_keys
    }
    workspace_counts = dict.fromkeys(project_keys, 0)
    claimed_workspace_counts = dict.fromkeys(project_keys, 0)
    issue_messages: dict[str, list[str]] = {key: [] for key in project_keys}
    errors: list[str] = []

    try:
        repo_inventory = collect_repo_inventory(
            projects_root,
            include_disabled=True,
        )
    except Exception as exc:
        errors.append(f"repos unavailable: {exc}")
    else:
        for repo in repo_inventory.records:
            if repo.project_key in repo_kind_counts:
                repo_kind_counts[repo.project_key][repo.kind] += 1
        for repo_issue in repo_inventory.issues:
            key = project_lookup.get(repo_issue.project)
            if key is not None:
                issue_messages[key].append(f"Repo inventory: {repo_issue.message}")

    try:
        workspace_inventory = collect_workspace_inventory(
            projects_root,
            include_disabled=True,
        )
    except Exception as exc:
        errors.append(f"workspaces unavailable: {exc}")
    else:
        for workspace in workspace_inventory.records:
            if workspace.project_key not in workspace_counts:
                continue
            workspace_counts[workspace.project_key] += 1
            if workspace.claimed:
                claimed_workspace_counts[workspace.project_key] += 1
        for workspace_issue in workspace_inventory.issues:
            key = project_lookup.get(workspace_issue.project)
            if key is not None:
                issue_messages[key].append(
                    f"Workspace inventory: {workspace_issue.message}"
                )

    counts: dict[str, ProjectInventoryCounts] = {}
    for key in project_keys:
        kinds = repo_kind_counts[key]
        counts[key] = ProjectInventoryCounts(
            repo_count=sum(kinds.values()),
            primary_repo_count=kinds["primary"],
            sidecar_repo_count=kinds["sidecar"],
            linked_repo_count=kinds["linked"],
            workspace_count=workspace_counts[key],
            claimed_workspace_count=claimed_workspace_counts[key],
            issue_messages=tuple(issue_messages[key]),
        )
    return _ProjectCountsLoadResult(counts, tuple(errors))


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


class _ProjectsPlaceholder(Static, can_focus=True):
    """Focusable empty-state used until the remaining sub-tabs land."""


class ProjectsPane(
    ProjectManagementActionsMixin,
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
        }
    )

    def __init__(self, projects_root: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._projects_root = projects_root
        self._records: list[ProjectRecordWire] = []
        self._filtered_records: list[ProjectRecordWire] = []
        self._active_subtab: ProjectsSubTab = _DEFAULT_SUBTAB
        self._text_filter = ""
        self._status_message = ""
        self._marked_projects: set[str] = set()
        self._pending_force: _PendingForce | None = None
        self._inventory_counts: dict[str, ProjectInventoryCounts] = {}
        self._inventory_loading = False
        self._inventory_error = ""
        self._inventory_worker: Worker[Any] | None = None
        self._detail_debouncer: DetailPanelDebouncer | None = None
        self._syncing_options = False
        self._load_records()
        self._inventory_loading = bool(self._records)

    def compose(self) -> ComposeResult:
        yield PanelTabStrip(
            _SUBTABS,
            self._active_subtab,
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
            yield _ProjectsPlaceholder(
                "Repository inventory view is coming in the next phase.\n\n"
                "Use [ / ] or click a sub-tab to keep browsing.",
                id=_SUBTAB_WIDGET_IDS["repos"],
                classes="projects-subtab-placeholder",
                markup=False,
            )
            yield _ProjectsPlaceholder(
                "Workspace inventory view is coming in the next phase.\n\n"
                "Use [ / ] or click a sub-tab to keep browsing.",
                id=_SUBTAB_WIDGET_IDS["workspaces"],
                classes="projects-subtab-placeholder",
                markup=False,
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
            else:
                self.query_one(
                    f"#{_SUBTAB_WIDGET_IDS[self._active_subtab]}",
                    _ProjectsPlaceholder,
                ).focus()
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
        return True

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

        def task() -> _ProjectCountsLoadResult:
            return _collect_project_inventory_counts(projects_root, records)

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
            if isinstance(result, _ProjectCountsLoadResult):
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

    def _apply_filters(self) -> None:
        text_filter = self._text_filter.casefold().strip()
        rows: list[ProjectRecordWire] = []
        for record in self._records:
            if text_filter:
                haystack = " ".join(
                    (
                        record.project_name,
                        effective_project_name(record),
                        " ".join(record.aliases),
                        record.state,
                        record.vcs_kind or "",
                        record.workspace_dir or "",
                        " ".join(record.warnings),
                        " ".join(record.parse_warnings),
                    )
                ).casefold()
                if text_filter not in haystack:
                    continue
            rows.append(record)
        self._filtered_records = rows

    def _create_options(self, records: list[ProjectRecordWire]) -> list[Option]:
        if not records:
            message = (
                "No projects match the current search"
                if self._text_filter.strip()
                else "No registered projects"
            )
            return [Option(Text(message, style="dim"), id="empty")]
        return [
            Option(self._record_label(record), id=record.project_name)
            for record in records
        ]

    def _counts_for(self, record: ProjectRecordWire) -> ProjectInventoryCounts:
        return self._inventory_counts.get(
            record.project_name,
            ProjectInventoryCounts(),
        )

    def _record_label(self, record: ProjectRecordWire) -> Text:
        return record_label(
            record,
            self._marked_projects,
            self._counts_for(record),
        )

    def _summary_text(self) -> Text:
        return summary_text(
            self._records,
            self._text_filter,
            self._status_message,
            self._marked_projects,
            inventory_loading=self._inventory_loading,
            inventory_error=self._inventory_error,
        )

    def _hints_text(self) -> str:
        return hints_text(self._marked_projects)

    def _refresh_options(self, *, preferred_project: str | None = None) -> None:
        try:
            option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        current = preferred_project or self._selected_project_name()
        self._syncing_options = True
        try:
            option_list.clear_options()
            for option in self._create_options(self._filtered_records):
                option_list.add_option(option)
            if self._filtered_records:
                index = 0
                if current is not None:
                    for i, record in enumerate(self._filtered_records):
                        if record.project_name == current:
                            index = i
                            break
                option_list.highlighted = index
            else:
                option_list.highlighted = None
        finally:
            self._syncing_options = False
        self._update_summary()
        self._update_detail()
        self._refresh_hints()

    def _update_summary(self) -> None:
        try:
            self.query_one("#projects-summary", Static).update(self._summary_text())
        except Exception:
            pass

    def _refresh_hints(self) -> None:
        try:
            self.query_one("#projects-hints", Static).update(self._hints_text())
        except Exception:
            pass

    def _selected_project_name(self) -> str | None:
        record = self._selected_record()
        return None if record is None else record.project_name

    def _selected_record(self) -> ProjectRecordWire | None:
        try:
            option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not (0 <= highlighted < len(self._filtered_records)):
            return None
        return self._filtered_records[highlighted]

    def _marked_records(self) -> list[ProjectRecordWire]:
        return [
            record
            for record in self._records
            if record.project_name in self._marked_projects
        ]

    def _records_for_names(
        self, project_names: Sequence[str]
    ) -> list[ProjectRecordWire]:
        requested = set(project_names)
        return [record for record in self._records if record.project_name in requested]

    def _target_records(self) -> list[ProjectRecordWire]:
        if self._marked_projects:
            records = self._marked_records()
            if records:
                return records
            self._marked_projects.clear()
            self._pending_force = None
            self._set_status("No marked projects remain")
            self._refresh_options()
            return []

        record = self._selected_record()
        if record is None:
            self._set_status("No project selected")
            return []
        return [record]

    def _prune_stale_marked_projects(self) -> None:
        if not self._marked_projects:
            return
        live_projects = {record.project_name for record in self._records}
        stale = self._marked_projects - live_projects
        if stale:
            self._marked_projects -= stale
            if self._pending_force is not None:
                project_names, state = self._pending_force
                live_pending = tuple(
                    project for project in project_names if project in live_projects
                )
                self._pending_force = (live_pending, state) if live_pending else None

    def _advance_mark_selection(self, highlighted: int) -> str | None:
        if not self._filtered_records:
            return None
        next_index = (highlighted + 1) % len(self._filtered_records)
        return self._filtered_records[next_index].project_name

    def _detail_text(self, record: ProjectRecordWire | None) -> Text:
        counts = self._counts_for(record) if record is not None else None
        return detail_text(record, self._marked_projects, counts)

    def _update_detail(self) -> None:
        try:
            self.query_one("#projects-detail", Static).update(
                self._detail_text(self._selected_record())
            )
        except Exception:
            pass

    def _schedule_detail_update(self) -> None:
        if self._detail_debouncer is None:
            self._update_detail()
            return
        self._detail_debouncer.schedule(self._update_detail)

    def _set_status(self, message: str) -> None:
        self._status_message = message
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

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "projects-filter":
            return
        self._text_filter = event.value
        self._apply_filters()
        self._refresh_options()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).focus()
        self.action_default_project_action()

    def on_option_list_option_highlighted(
        self, _event: OptionList.OptionHighlighted
    ) -> None:
        if not self._syncing_options:
            self._schedule_detail_update()

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        self.action_default_project_action()

    @on(PanelTabStrip.TabClicked)
    def _on_subtab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        event.stop()
        if event.tab_id in _SUBTAB_ORDER:
            self._switch_to_subtab(cast(ProjectsSubTab, event.tab_id))

    def _switch_to_subtab(self, subtab: ProjectsSubTab) -> None:
        self._active_subtab = subtab
        try:
            self.query_one(
                "#projects-subtab-switcher", ContentSwitcher
            ).current = _SUBTAB_WIDGET_IDS[subtab]
            self.query_one("#projects-subtabs", PanelTabStrip).set_active_tab(subtab)
        except Exception:
            return
        self.focus_default()

    def _cycle_subtab(self, step: int) -> None:
        index = _SUBTAB_ORDER.index(self._active_subtab)
        self._switch_to_subtab(_SUBTAB_ORDER[(index + step) % len(_SUBTAB_ORDER)])

    def action_cycle_subtab(self) -> None:
        self._cycle_subtab(1)

    def action_cycle_subtab_reverse(self) -> None:
        self._cycle_subtab(-1)

    def action_focus_filter(self) -> None:
        self.query_one("#projects-filter", _ProjectsFilterInput).focus()

    def action_toggle_project_mark(self) -> None:
        record = self._selected_record()
        if record is None:
            self._set_status("No project selected")
            return

        if record.project_name in self._marked_projects:
            self._marked_projects.remove(record.project_name)
        else:
            self._marked_projects.add(record.project_name)

        try:
            option_list = self.query_one(f"#{self._option_list_id}", OptionList)
            highlighted = option_list.highlighted
        except Exception:
            highlighted = None
        preferred = (
            self._advance_mark_selection(highlighted)
            if highlighted is not None
            else record.project_name
        )
        self._set_status(f"Marked {len(self._marked_projects)} project(s)")
        self._refresh_options(preferred_project=preferred)

    def action_clear_project_marks(self) -> None:
        if not self._marked_projects:
            self._set_status("No marks to clear")
            self.notify("No marks to clear", severity="warning")
            return

        count = len(self._marked_projects)
        self._marked_projects.clear()
        self._pending_force = None
        self._set_status(f"Cleared {count} mark(s)")
        self._refresh_options()
        self.notify(f"Cleared {count} mark(s)")

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
    "_ProjectCountsLoadResult",
    "_collect_project_inventory_counts",
    "delete_project_locked",
    "list_project_records",
    "set_project_aliases_locked",
    "set_project_state_locked",
]

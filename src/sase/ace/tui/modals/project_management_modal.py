"""Project lifecycle management modal for the ace TUI."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.main.project_handler import (
    ProjectLifecycleBlockedError,
    delete_project_locked,
    set_project_state_locked,
)

from .base import FilterInput, OptionListNavigationMixin
from .project_management_actions import ProjectManagementActionsMixin
from .project_management_rendering import (
    detail_text,
    footer_text,
    record_label,
    short_path as _short_path,
    state_style as _state_style,
    summary_text,
    warning_count as _warning_count,
)

ProjectStateFilter = Literal["all", "active", "archived", "closed"]
_PendingForce = tuple[tuple[str, ...], str]
_STATE_FILTERS: tuple[ProjectStateFilter, ...] = (
    "all",
    "active",
    "archived",
    "closed",
)


class ProjectManagementModal(
    ProjectManagementActionsMixin,
    OptionListNavigationMixin,
    ModalScreen[None],
):
    """List and mutate SASE project lifecycle state."""

    _option_list_id = "project-management-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("/", "focus_filter", "Filter", priority=True),
        Binding("tab", "cycle_state_filter", "Cycle State", priority=True),
        Binding("m", "toggle_project_mark", "Mark", priority=True),
        Binding("u", "clear_project_marks", "Unmark All", priority=True),
        Binding("a", "activate_project", "Activate", priority=True),
        Binding("r", "archive_project", "Archive", priority=True),
        Binding("c", "close_project", "Close", priority=True),
        Binding("ctrl+d", "delete_project", "Delete", priority=True),
        Binding("F", "force_current_state_change", "Force", priority=True),
        Binding("enter", "default_project_action", "Default", priority=True),
        Binding("R", "reload_projects", "Reload", priority=True),
    ]

    def __init__(self, projects_root: Path | None = None) -> None:
        super().__init__()
        self._projects_root = projects_root
        self._records: list[ProjectRecordWire] = []
        self._filtered_records: list[ProjectRecordWire] = []
        self._state_filter: ProjectStateFilter = "all"
        self._text_filter = ""
        self._status_message = ""
        self._marked_projects: set[str] = set()
        self._pending_force: _PendingForce | None = None
        self._load_records()

    def compose(self) -> ComposeResult:
        with Container(id="project-management-container"):
            yield Label("Project Management", id="project-management-title")
            yield Static(self._summary_text(), id="project-management-summary")
            yield FilterInput(
                placeholder="Type to filter projects...", id="project-management-filter"
            )
            yield OptionList(
                *self._create_options(self._filtered_records),
                id=self._option_list_id,
            )
            yield Static("", id="project-management-detail")
            yield Static(self._footer_text(), id="project-management-footer")

    def on_mount(self) -> None:
        self._refresh_options()
        self.query_one(f"#{self._option_list_id}", OptionList).focus()
        self._update_detail()

    def _load_records(self) -> None:
        root = (
            self._projects_root
            if self._projects_root is not None
            else sase_projects_dir()
        )
        try:
            records = list_project_records(root, "all", include_home=False)
        except Exception as exc:
            self._records = []
            self._filtered_records = []
            self._status_message = f"Load failed: {exc}"
            return
        self._records = [
            record
            for record in records
            if record.project_name != "home" and not record.system_managed
        ]
        self._prune_stale_marked_projects()
        self._apply_filters()

    def _apply_filters(self) -> None:
        text_filter = self._text_filter.lower().strip()
        rows: list[ProjectRecordWire] = []
        for record in self._records:
            if self._state_filter != "all" and record.state != self._state_filter:
                continue
            if text_filter:
                haystack = " ".join(
                    (
                        record.project_name,
                        record.state,
                        record.workspace_dir or "",
                        " ".join(record.warnings),
                        " ".join(record.parse_warnings),
                    )
                ).lower()
                if text_filter not in haystack:
                    continue
            rows.append(record)
        self._filtered_records = rows

    def _create_options(self, records: list[ProjectRecordWire]) -> list[Option]:
        if not records:
            return [
                Option(
                    Text("No projects match the current filters", style="dim"),
                    id="empty",
                )
            ]
        return [
            Option(self._record_label(record), id=record.project_name)
            for record in records
        ]

    def _record_label(self, record: ProjectRecordWire) -> Text:
        return record_label(record, self._marked_projects)

    def _summary_text(self) -> Text:
        return summary_text(
            self._records,
            self._state_filter,
            self._text_filter,
            self._status_message,
            self._marked_projects,
        )

    def _footer_text(self) -> str:
        return footer_text(self._marked_projects)

    def _refresh_options(self, *, preferred_project: str | None = None) -> None:
        try:
            option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return
        current = preferred_project or self._selected_project_name()
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
        self._update_summary()
        self._update_detail()
        self._refresh_footer()

    def _update_summary(self) -> None:
        try:
            self.query_one("#project-management-summary", Static).update(
                self._summary_text()
            )
        except Exception:
            pass

    def _refresh_footer(self) -> None:
        try:
            self.query_one("#project-management-footer", Static).update(
                self._footer_text()
            )
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
        return detail_text(record, self._marked_projects)

    def _update_detail(self) -> None:
        try:
            self.query_one("#project-management-detail", Static).update(
                self._detail_text(self._selected_record())
            )
        except Exception:
            pass

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

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "project-management-filter":
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
        self._update_detail()

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        self.action_default_project_action()

    def action_focus_filter(self) -> None:
        self.query_one("#project-management-filter", FilterInput).focus()

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

    def action_cycle_state_filter(self) -> None:
        idx = _STATE_FILTERS.index(self._state_filter)
        self._state_filter = _STATE_FILTERS[(idx + 1) % len(_STATE_FILTERS)]
        self._pending_force = None
        self._apply_filters()
        self._refresh_options()

    def action_reload_projects(self) -> None:
        selected = self._selected_project_name()
        try:
            self._load_records()
        except Exception as exc:
            self._set_status(f"Reload failed: {exc}")
            self.notify(f"Project reload failed: {exc}", severity="error")
            return
        self._pending_force = None
        self._set_status("Reloaded")
        self._refresh_options(preferred_project=selected)


__all__ = [
    "ProjectLifecycleBlockedError",
    "ProjectManagementModal",
    "ProjectStateFilter",
    "delete_project_locked",
    "list_project_records",
    "set_project_state_locked",
]

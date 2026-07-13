"""Reusable Projects pane for the SASE Admin Center modal.

This widget hosts the body of the former ``ProjectManagementModal`` (state
filter tabs, summary, filter input, project list, detail pane, and hints) so it
can live inside the **Projects** tab of the :class:`ConfigCenterModal` content
switcher. Every behavior of the old modal is preserved; the only structural
change is that the surrounding ``ModalScreen`` chrome (centering container,
escape/close handling, main-tab navigation) now belongs to the host modal.

The lifecycle/delete actions (:class:`ProjectManagementActionsMixin`) and the
pure rendering helpers (``project_management_rendering``) are reused unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

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
from .project_management_actions import ProjectManagementActionsMixin
from .project_management_rendering import (
    column_header_text,
    detail_text,
    hints_text,
    record_label,
    state_tabs_text,
    summary_text,
)

ProjectStateFilter = Literal["all", "enabled", "disabled", "sibling"]
_DEFAULT_STATE_FILTER: ProjectStateFilter = "enabled"
_PendingForce = tuple[tuple[str, ...], str]
_STATE_FILTERS: tuple[ProjectStateFilter, ...] = (
    _DEFAULT_STATE_FILTER,
    "sibling",
    "disabled",
    "all",
)


class _ProjectsFilterInput(FilterInput):
    """Filter input that forwards navigation keys swallowed by ``Input``.

    Printable keys are consumed by :class:`Input` as text before pane or
    screen bindings fire, so ``[`` / ``]`` are forwarded to the owning pane's
    state-filter actions. ``Tab`` / ``Shift+Tab`` are intentionally left to the
    Admin Center's priority bindings for main-tab navigation.
    """

    def on_key(self, event: events.Key) -> None:
        """Forward state-cycle keys before they become filter text."""
        if event.key in ("left_square_bracket", "right_square_bracket"):
            pane = self._pane()
            if pane is not None:
                event.stop()
                event.prevent_default()
                if event.key == "left_square_bracket":
                    pane.action_cycle_state_filter_reverse()
                else:
                    pane.action_cycle_state_filter()

    def _pane(self) -> ProjectsPane | None:
        """Return the owning :class:`ProjectsPane`, if any."""
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, ProjectsPane):
                return node
            node = getattr(node, "parent", None)
        return None


class ProjectsPane(
    ProjectManagementActionsMixin,
    OptionListNavigationMixin,
    Vertical,
):
    """List and mutate SASE project lifecycle state inside the Admin Center."""

    _option_list_id = "projects-list"
    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("/", "focus_filter", "Filter"),
        ("right_square_bracket", "cycle_state_filter", "Cycle State"),
        ("left_square_bracket", "cycle_state_filter_reverse", "Cycle State Back"),
        ("ctrl+x", "toggle_inactive_projects", "Inactive"),
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

    def __init__(self, projects_root: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._projects_root = projects_root
        self._records: list[ProjectRecordWire] = []
        self._filtered_records: list[ProjectRecordWire] = []
        self._state_filter: ProjectStateFilter = _DEFAULT_STATE_FILTER
        self._show_inactive_projects = False
        self._text_filter = ""
        self._status_message = ""
        self._marked_projects: set[str] = set()
        self._pending_force: _PendingForce | None = None
        self._load_records()

    def compose(self) -> ComposeResult:
        yield Static(self._state_tabs_text(), id="projects-state-tabs")
        yield Static(self._summary_text(), id="projects-summary")
        yield _ProjectsFilterInput(
            placeholder="Type to filter projects...", id="projects-filter"
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

    def on_mount(self) -> None:
        self._refresh_options()

    def focus_default(self) -> None:
        """Focus the project list (browse-first) when the Projects tab opens."""
        try:
            self.query_one(f"#{self._option_list_id}", OptionList).focus()
        except Exception:
            pass

    def _load_records(self) -> bool:
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
            return False
        self._records = [
            record
            for record in records
            if record.project_name != "home" and not record.system_managed
        ]
        self._prune_stale_marked_projects()
        self._apply_filters()
        return True

    def _apply_filters(self) -> None:
        text_filter = self._text_filter.lower().strip()
        rows: list[ProjectRecordWire] = []
        for record in self._records:
            state_matches = (
                True
                if self._state_filter == "all"
                else record.state == self._state_filter
                or (
                    self._state_filter == "enabled"
                    and self._show_inactive_projects
                    and record.state == "disabled"
                )
            )
            if not state_matches:
                continue
            if text_filter:
                haystack = " ".join(
                    (
                        record.project_name,
                        effective_project_name(record),
                        " ".join(record.aliases),
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
            self._text_filter,
            self._status_message,
            self._marked_projects,
            self._show_inactive_projects,
        )

    def _state_tabs_text(self) -> Text:
        return state_tabs_text(self._state_filter)

    def _hints_text(self) -> str:
        return hints_text(self._marked_projects, self._show_inactive_projects)

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
        self._update_state_tabs()
        self._update_summary()
        self._update_detail()
        self._refresh_hints()

    def _update_state_tabs(self) -> None:
        try:
            self.query_one("#projects-state-tabs", Static).update(
                self._state_tabs_text()
            )
        except Exception:
            pass

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
        return detail_text(record, self._marked_projects)

    def _update_detail(self) -> None:
        try:
            self.query_one("#projects-detail", Static).update(
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
        self._update_detail()

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        self.action_default_project_action()

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

    def _cycle_state_filter(self, step: int) -> None:
        idx = _STATE_FILTERS.index(self._state_filter)
        self._state_filter = _STATE_FILTERS[(idx + step) % len(_STATE_FILTERS)]
        self._pending_force = None
        self._apply_filters()
        self._refresh_options()

    def action_cycle_state_filter(self) -> None:
        self._cycle_state_filter(1)

    def action_cycle_state_filter_reverse(self) -> None:
        self._cycle_state_filter(-1)

    def action_toggle_inactive_projects(self) -> None:
        self._show_inactive_projects = not self._show_inactive_projects
        self._pending_force = None
        self._apply_filters()
        message = (
            "Disabled projects visible"
            if self._show_inactive_projects
            else "Disabled projects hidden"
        )
        self._set_status(message)
        self._refresh_options()
        self.notify(message)

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


__all__ = [
    "ProjectLifecycleBlockedError",
    "ProjectStateFilter",
    "ProjectsPane",
    "delete_project_locked",
    "list_project_records",
    "set_project_aliases_locked",
    "set_project_state_locked",
]

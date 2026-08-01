"""Project-list state, rendering coordination, and selection actions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import restore_selection_by_identity
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name

from .config_center_session import ProjectsSessionState
from .project_management_rendering import (
    ProjectInventoryCounts,
    detail_text,
    hints_text,
    record_label,
    summary_text,
)

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class ProjectListControllerMixin(_MixinBase):
    """Coordinate the filterable project list and its detail panel."""

    if TYPE_CHECKING:
        _option_list_id: str
        _records: list[ProjectRecordWire]
        _filtered_records: list[ProjectRecordWire]
        _text_filter: str
        _status_message: str
        _marked_projects: set[str]
        _pending_force: tuple[tuple[str, ...], str] | None
        _inventory_counts: dict[str, ProjectInventoryCounts]
        _inventory_loading: bool
        _inventory_error: str
        _detail_debouncer: DetailPanelDebouncer | None
        _syncing_options: bool
        _session_state: ProjectsSessionState

        def action_default_project_action(self) -> None: ...

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
        current = (
            preferred_project
            or self._session_state.projects.identity
            or self._selected_project_name()
        )
        self._syncing_options = True
        selected_index: int | None = None
        try:
            option_list.clear_options()
            for option in self._create_options(self._filtered_records):
                option_list.add_option(option)
            if self._filtered_records:
                index = restore_selection_by_identity(
                    self._filtered_records,
                    prior_identity=current,
                    prior_visual_row=self._session_state.projects.row,
                    identity_fn=lambda record: record.project_name,
                )
                option_list.highlighted = index
                selected_index = index
            else:
                option_list.highlighted = None
        finally:
            self._syncing_options = False
        self._record_project_bookmark(selected_index)
        self._update_summary()
        self._update_detail()
        self._refresh_hints()

    def _record_project_bookmark(self, index: int | None) -> None:
        if index is None or not (0 <= index < len(self._filtered_records)):
            if not self._records:
                self._session_state.projects.record(None, None)
            return
        record = self._filtered_records[index]
        self._session_state.projects.record(record.project_name, index)

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
            try:
                highlighted = self.query_one(
                    f"#{self._option_list_id}", OptionList
                ).highlighted
            except Exception:
                highlighted = None
            self._record_project_bookmark(highlighted)
            self._schedule_detail_update()

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        self.action_default_project_action()

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


__all__ = ["ProjectListControllerMixin"]

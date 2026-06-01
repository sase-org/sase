"""Project lifecycle management modal for the ace TUI."""

from __future__ import annotations

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
from .confirm_action_modal import ConfirmActionModal

ProjectStateFilter = Literal["all", "active", "archived", "closed"]
_STATE_FILTERS: tuple[ProjectStateFilter, ...] = (
    "all",
    "active",
    "archived",
    "closed",
)


def _warning_count(record: ProjectRecordWire) -> int:
    return len(record.warnings) + len(record.parse_warnings)


def _short_path(path: str | None, *, max_len: int = 46) -> str:
    if not path:
        return "-"
    text = str(Path(path).expanduser())
    if len(text) <= max_len:
        return text
    return "..." + text[-(max_len - 3) :]


def _state_style(state: str) -> str:
    if state == "active":
        return "bold #00D7AF"
    if state == "archived":
        return "bold #FFD700"
    if state == "closed":
        return "bold #FF8C00"
    return "bold"


class ProjectManagementModal(OptionListNavigationMixin, ModalScreen[None]):
    """List and mutate SASE project lifecycle state."""

    _option_list_id = "project-management-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("/", "focus_filter", "Filter", priority=True),
        Binding("tab", "cycle_state_filter", "Cycle State", priority=True),
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
        self._pending_force: tuple[str, str] | None = None
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
        text = Text()
        text.append(f"{record.project_name:<24.24}", style="bold")
        text.append("  ")
        text.append(f"{record.state:<8}", style=_state_style(record.state))
        if not record.state_explicit:
            text.append(" default", style="dim")
        else:
            text.append("        ")
        text.append(f"  claims:{record.active_claim_count:<2}")
        launch = "yes" if record.launchable and record.state == "active" else "no"
        text.append(f"  launch:{launch:<3}")
        if _warning_count(record):
            text.append(f"  warnings:{_warning_count(record)}", style="bold red")
        text.append("  ")
        text.append(_short_path(record.workspace_dir), style="dim")
        return text

    def _summary_text(self) -> Text:
        counts: dict[str, int] = {"active": 0, "archived": 0, "closed": 0}
        for record in self._records:
            if record.state in counts:
                counts[record.state] += 1
        text = Text()
        text.append("Filter: ", style="dim")
        text.append(self._state_filter, style="bold")
        text.append(
            f"  all:{len(self._records)} active:{counts['active']} "
            f"archived:{counts['archived']} closed:{counts['closed']}",
            style="dim",
        )
        if self._text_filter:
            text.append(f"  search:{self._text_filter}", style="dim")
        if self._status_message:
            text.append(f"  {self._status_message}", style="#87D7FF")
        return text

    def _footer_text(self) -> str:
        return (
            "j/k navigate  / filter  Tab state  Enter activate inactive  "
            "a activate  r archive  c close  Ctrl+D delete  "
            "F force after block  R reload  q close"
        )

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

    def _update_summary(self) -> None:
        try:
            self.query_one("#project-management-summary", Static).update(
                self._summary_text()
            )
        except Exception:
            pass

    def _selected_project_name(self) -> str | None:
        try:
            option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not (0 <= highlighted < len(self._filtered_records)):
            return None
        return self._filtered_records[highlighted].project_name

    def _selected_record(self) -> ProjectRecordWire | None:
        try:
            option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not (0 <= highlighted < len(self._filtered_records)):
            return None
        return self._filtered_records[highlighted]

    def _detail_text(self, record: ProjectRecordWire | None) -> Text:
        text = Text()
        if record is None:
            text.append("No project selected", style="dim")
            return text

        source = "explicit" if record.state_explicit else "defaulted"
        launch = "yes" if record.launchable and record.state == "active" else "no"
        text.append(record.project_name, style="bold")
        text.append("  ")
        text.append(record.state, style=_state_style(record.state))
        text.append(f" ({source})")
        text.append(f"\nProject file: {record.project_file}", style="dim")
        text.append(f"\nWorkspace: {_short_path(record.workspace_dir, max_len=72)}")
        text.append(
            f"\nActive claims: {record.active_claim_count}    Launchable: {launch}"
        )
        warnings = [*record.warnings, *record.parse_warnings]
        if warnings:
            text.append("\nWarnings:", style="bold red")
            for warning in warnings:
                text.append(f"\n  - {warning}", style="red")
        if record.state != "active":
            text.append(
                f"\nHint: press a or Enter to reactivate {record.project_name}.",
                style="#87D7FF",
            )
        return text

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

    def action_activate_project(self) -> None:
        self._set_project_state("active")

    def action_archive_project(self) -> None:
        self._set_project_state("archived")

    def action_close_project(self) -> None:
        self._set_project_state("closed")

    def action_delete_project(self) -> None:
        record = self._selected_record()
        if record is None:
            self._set_status("No project selected")
            return
        if record.project_name == "home" or record.system_managed:
            message = f"Project '{record.project_name}' is system-managed"
            self._set_status(message)
            self.notify(message, severity="error")
            return

        project_dir = self._project_dir_for(record)

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                self._set_status("Delete cancelled")
                return
            self._delete_project_confirmed(record.project_name)

        self.app.push_screen(
            ConfirmActionModal(
                title="Delete Project Directory",
                message=(
                    f"Delete SASE project directory for '{record.project_name}'?\n\n"
                    f"{project_dir}\n\n"
                    "This removes project specs, project-local config, artifacts, "
                    "and other SASE state. It cannot be undone.\n\n"
                    "The workspace checkout is not deleted."
                ),
            ),
            _on_confirm,
        )

    def action_default_project_action(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        if record.state != "active":
            self._set_project_state("active")
        else:
            self._set_status(f"{record.project_name} is already active")

    def action_force_current_state_change(self) -> None:
        if self._pending_force is None:
            self._set_status("No blocked archive/close to force")
            return
        project, state = self._pending_force
        record = self._selected_record()
        if record is None or record.project_name != project:
            self._set_status(f"Select {project} before forcing")
            return

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                self._set_status("Force cancelled")
                return
            self._set_project_state(state, force=True)

        self.app.push_screen(
            ConfirmActionModal(
                title="Force Project State Change",
                message=(
                    f"Force {project} to {state} even though live work was found?"
                ),
            ),
            _on_confirm,
        )

    def _set_project_state(self, state: str, *, force: bool = False) -> None:
        record = self._selected_record()
        if record is None:
            self._set_status("No project selected")
            return
        if record.state == state:
            self._pending_force = None
            self._set_status(f"{record.project_name} is already {state}")
            return

        try:
            updated = set_project_state_locked(
                record.project_name,
                state,
                force=force,
            )
        except ProjectLifecycleBlockedError as exc:
            self._pending_force = (record.project_name, state)
            message = f"Blocked: {exc}. Press F to force."
            self._set_status(message)
            self.notify(message, severity="warning")
            return
        except Exception as exc:
            self._set_status(f"Failed: {exc}")
            self.notify(f"Project state change failed: {exc}", severity="error")
            return

        self._pending_force = None
        self._status_message = f"{updated.project_name} -> {updated.state}"
        try:
            self._load_records()
        except Exception as exc:
            self._set_status(f"Updated, reload failed: {exc}")
        self._refresh_options(preferred_project=updated.project_name)
        self._notify_lifecycle_changed()
        self.notify(f"Project '{updated.project_name}' state is now {updated.state}")

    def _project_dir_for(self, record: ProjectRecordWire) -> Path:
        root = (
            self._projects_root
            if self._projects_root is not None
            else sase_projects_dir()
        )
        return root.expanduser() / record.project_name

    def _delete_project_confirmed(self, project: str) -> None:
        try:
            delete_project_locked(project, projects_root=self._projects_root)
        except ProjectLifecycleBlockedError as exc:
            self._pending_force = None
            message = f"Blocked: {exc}"
            self._set_status(message)
            self.notify(message, severity="warning")
            return
        except Exception as exc:
            self._pending_force = None
            self._set_status(f"Delete failed: {exc}")
            self.notify(f"Project deletion failed: {exc}", severity="error")
            return

        self._pending_force = None
        self._status_message = f"Deleted {project}"
        try:
            self._load_records()
        except Exception as exc:
            self._set_status(f"Deleted, reload failed: {exc}")
        self._refresh_options()
        self._notify_lifecycle_changed()
        self.notify(f"Deleted project '{project}'")

    def _notify_lifecycle_changed(self) -> None:
        app = self.app
        for method_name, args, kwargs in (
            ("_schedule_changespecs_async_refresh", (), {}),
            (
                "_schedule_agents_async_refresh",
                (),
                {"source": "project_lifecycle", "full_history": False},
            ),
            ("_schedule_axe_async_refresh", (), {}),
            ("_refresh_current_tab", (), {}),
        ):
            method = getattr(app, method_name, None)
            if method is None:
                continue
            try:
                method(*args, **kwargs)
            except TypeError:
                try:
                    method()
                except Exception:
                    pass
            except Exception:
                pass

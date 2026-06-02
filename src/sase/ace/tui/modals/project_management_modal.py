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
from .confirm_action_modal import ConfirmActionModal

ProjectStateFilter = Literal["all", "active", "archived", "closed"]
_PendingForce = tuple[tuple[str, ...], str]
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
        text = Text()
        if record.project_name in self._marked_projects:
            text.append("[✓] ", style="bold #00D700")
        else:
            text.append("    ", style="dim")
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
        mark_count = len(self._marked_projects)
        text.append("  marked:", style="dim")
        text.append(
            str(mark_count),
            style="bold #00D700" if mark_count else "dim",
        )
        if self._text_filter:
            text.append(f"  search:{self._text_filter}", style="dim")
        if self._status_message:
            text.append(f"  {self._status_message}", style="#87D7FF")
        return text

    def _footer_text(self) -> str:
        base = (
            "j/k navigate  / filter  Tab state  Enter highlighted  "
            "m mark  u unmark all  a activate  r archive  c close  "
            "Ctrl+D delete  F force after block  R reload  q close"
        )
        mark_count = len(self._marked_projects)
        if not mark_count:
            return base
        return f"{base}  marked:{mark_count} (a/r/c/Ctrl+D target marked set)"

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
        if self._marked_projects:
            row_state = (
                "marked"
                if record.project_name in self._marked_projects
                else "not marked"
            )
            text.append(
                "\nMarked set: "
                f"{len(self._marked_projects)} project(s); "
                "a/r/c/Ctrl+D target marked projects; "
                f"this row is {row_state}.",
                style="#87D7FF",
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

    def action_activate_project(self) -> None:
        self._set_project_state("active")

    def action_archive_project(self) -> None:
        self._set_project_state("archived")

    def action_close_project(self) -> None:
        self._set_project_state("closed")

    def action_delete_project(self) -> None:
        if self._marked_projects:
            records = self._marked_records()
            if not records:
                self._marked_projects.clear()
                self._pending_force = None
                self._set_status("No marked projects remain")
                self._refresh_options()
                return

            project_names = tuple(record.project_name for record in records)

            def _on_bulk_delete_confirm(confirmed: bool | None) -> None:
                if not confirmed:
                    self._set_status("Delete cancelled")
                    return
                self._delete_marked_projects_confirmed(project_names)

            self.app.push_screen(
                ConfirmActionModal(
                    title="Delete Marked Project Directories",
                    message=self._bulk_delete_message(records),
                ),
                _on_bulk_delete_confirm,
            )
            return

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

        def _on_single_delete_confirm(confirmed: bool | None) -> None:
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
            _on_single_delete_confirm,
        )

    def action_default_project_action(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        if record.state != "active":
            self._set_project_state_for_records([record], "active")
        else:
            self._set_status(f"{record.project_name} is already active")

    def action_force_current_state_change(self) -> None:
        if self._pending_force is None:
            self._set_status("No blocked archive/close to force")
            return
        projects, state = self._pending_force
        if len(projects) == 1 and projects[0] not in self._marked_projects:
            record = self._selected_record()
            if record is None or record.project_name != projects[0]:
                self._set_status(f"Select {projects[0]} before forcing")
                return

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                self._set_status("Force cancelled")
                return
            records = self._records_for_names(projects)
            if not records:
                self._pending_force = None
                self._set_status("No blocked projects remain")
                self._refresh_options()
                return
            self._set_project_state_for_records(records, state, force=True)

        self.app.push_screen(
            ConfirmActionModal(
                title="Force Project State Change",
                message=self._force_state_change_message(projects, state),
            ),
            _on_confirm,
        )

    def _set_project_state(self, state: str, *, force: bool = False) -> None:
        records = self._target_records()
        if not records:
            return
        self._set_project_state_for_records(records, state, force=force)

    def _set_project_state_for_records(
        self,
        records: Sequence[ProjectRecordWire],
        state: str,
        *,
        force: bool = False,
    ) -> None:
        if not records:
            self._set_status("No project selected")
            return

        bulk = len(records) > 1 or any(
            record.project_name in self._marked_projects for record in records
        )
        skipped: list[str] = []
        successes: list[ProjectRecordWire] = []
        blocked: list[tuple[str, ProjectLifecycleBlockedError]] = []
        failed: list[tuple[str, Exception]] = []

        for record in records:
            if record.state == state:
                skipped.append(record.project_name)
                continue
            try:
                updated = set_project_state_locked(
                    record.project_name,
                    state,
                    force=force,
                )
            except ProjectLifecycleBlockedError as exc:
                blocked.append((record.project_name, exc))
            except Exception as exc:
                failed.append((record.project_name, exc))
            else:
                successes.append(updated)

        cleared = set(skipped)
        cleared.update(updated.project_name for updated in successes)
        if cleared:
            self._marked_projects -= cleared

        if blocked:
            self._pending_force = (
                tuple(project for project, _exc in blocked),
                state,
            )
        else:
            self._pending_force = None

        status = self._state_change_status(
            records,
            state,
            bulk=bulk,
            skipped=skipped,
            successes=successes,
            blocked=blocked,
            failed=failed,
        )
        preferred_project = (
            successes[-1].project_name if successes else records[0].project_name
        )
        self._status_message = status

        if successes or bulk:
            self._load_records()
        self._refresh_options(preferred_project=preferred_project)

        if successes:
            self._notify_lifecycle_changed()
            if bulk:
                self.notify(f"Updated {len(successes)} marked project(s) to {state}")
            else:
                updated = successes[0]
                self.notify(
                    f"Project '{updated.project_name}' state is now {updated.state}"
                )
        if blocked:
            self.notify(status, severity="warning")
        if failed:
            self.notify(status, severity="error")

    def _state_change_status(
        self,
        records: Sequence[ProjectRecordWire],
        state: str,
        *,
        bulk: bool,
        skipped: Sequence[str],
        successes: Sequence[ProjectRecordWire],
        blocked: Sequence[tuple[str, ProjectLifecycleBlockedError]],
        failed: Sequence[tuple[str, Exception]],
    ) -> str:
        if not bulk:
            if successes:
                updated = successes[0]
                return f"{updated.project_name} -> {updated.state}"
            if skipped:
                return f"{records[0].project_name} is already {state}"
            if blocked:
                return f"Blocked: {blocked[0][1]}. Press F to force."
            if failed:
                return f"Failed: {failed[0][1]}"
            return "No project selected"

        parts: list[str] = []
        if successes:
            parts.append(f"{len(successes)} changed to {state}")
        if skipped:
            parts.append(f"{len(skipped)} already {state}")
        if blocked:
            parts.append(f"{len(blocked)} blocked")
        if failed:
            parts.append(f"{len(failed)} failed")
        if not parts:
            return "No marked projects changed"

        status = "Marked projects: " + ", ".join(parts)
        if blocked:
            blocked_names = ", ".join(project for project, _exc in blocked[:3])
            if len(blocked) > 3:
                blocked_names += f", ... +{len(blocked) - 3}"
            status += f". Press F to force blocked: {blocked_names}"
        if failed:
            project, exc = failed[0]
            status += f". First failure: {project}: {exc}"
        return status

    def _force_state_change_message(
        self,
        projects: Sequence[str],
        state: str,
    ) -> str:
        if len(projects) == 1:
            return f"Force {projects[0]} to {state} even though live work was found?"
        lines = [
            f"Force {len(projects)} projects to {state} "
            "even though live work was found?",
            "",
        ]
        lines.extend(self._truncated_project_lines(projects))
        return "\n".join(lines)

    def _project_dir_for(self, record: ProjectRecordWire) -> Path:
        root = (
            self._projects_root
            if self._projects_root is not None
            else sase_projects_dir()
        )
        return root.expanduser() / record.project_name

    def _truncated_project_lines(self, projects: Sequence[str]) -> list[str]:
        limit = 8
        lines = [f"  - {project}" for project in projects[:limit]]
        remaining = len(projects) - limit
        if remaining > 0:
            lines.append(f"  ... and {remaining} more")
        return lines

    def _bulk_delete_message(self, records: Sequence[ProjectRecordWire]) -> str:
        lines = [
            f"Delete SASE project directories for {len(records)} marked projects?",
            "",
            "Projects:",
        ]
        limit = 8
        for record in records[:limit]:
            lines.append(f"  - {record.project_name}: {self._project_dir_for(record)}")
        remaining = len(records) - limit
        if remaining > 0:
            lines.append(f"  ... and {remaining} more")
        lines.extend(
            [
                "",
                "This removes project specs, project-local config, artifacts, "
                "and other SASE state. It cannot be undone.",
                "",
                "Workspace checkouts are not deleted.",
            ]
        )
        return "\n".join(lines)

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
        self._marked_projects.discard(project)
        self._status_message = f"Deleted {project}"
        try:
            self._load_records()
        except Exception as exc:
            self._set_status(f"Deleted, reload failed: {exc}")
        self._refresh_options()
        self._notify_lifecycle_changed()
        self.notify(f"Deleted project '{project}'")

    def _delete_marked_projects_confirmed(self, project_names: Sequence[str]) -> None:
        records = self._records_for_names(project_names)
        if not records:
            self._marked_projects.clear()
            self._pending_force = None
            self._set_status("No marked projects remain")
            self._refresh_options()
            return

        deleted: list[str] = []
        blocked: list[tuple[str, ProjectLifecycleBlockedError]] = []
        failed: list[tuple[str, Exception]] = []
        for record in records:
            try:
                delete_project_locked(
                    record.project_name,
                    projects_root=self._projects_root,
                )
            except ProjectLifecycleBlockedError as exc:
                blocked.append((record.project_name, exc))
            except Exception as exc:
                failed.append((record.project_name, exc))
            else:
                deleted.append(record.project_name)

        self._pending_force = None
        if deleted:
            self._marked_projects -= set(deleted)
        self._status_message = self._bulk_delete_status(deleted, blocked, failed)
        self._load_records()
        self._refresh_options()

        if deleted:
            self._notify_lifecycle_changed()
            self.notify(f"Deleted {len(deleted)} marked project(s)")
        if blocked:
            self.notify(self._status_message, severity="warning")
        if failed:
            self.notify(self._status_message, severity="error")

    def _bulk_delete_status(
        self,
        deleted: Sequence[str],
        blocked: Sequence[tuple[str, ProjectLifecycleBlockedError]],
        failed: Sequence[tuple[str, Exception]],
    ) -> str:
        if deleted and not blocked and not failed:
            return f"Deleted {len(deleted)} project(s)"

        parts: list[str] = []
        if deleted:
            parts.append(f"{len(deleted)} deleted")
        if blocked:
            parts.append(f"{len(blocked)} blocked")
        if failed:
            parts.append(f"{len(failed)} failed")
        if not parts:
            return "No marked projects deleted"

        status = "Delete marked projects: " + ", ".join(parts)
        if blocked:
            status += f". Blocked: {blocked[0][1]}"
        if failed:
            project, exc = failed[0]
            status += f". First failure: {project}: {exc}"
        return status

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

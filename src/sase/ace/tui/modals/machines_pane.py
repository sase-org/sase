"""Admin Center Machines pane and persistent Connect guidance."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import platform
import time
from typing import Any, Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Vertical, VerticalScroll
from textual.worker import Worker, WorkerState
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.agent_query import machine_query_term
from sase.ace.tui.models.agent_runner_slots import format_capacity_value
from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.keymaps import (
    MachinesPaneKeymaps,
    build_machines_bindings,
    key_display_name,
    load_keymap_registry,
    split_key_alternatives,
)
from sase.ace.tui.util.selection import (
    ProgrammaticSelectionGuard,
    restore_selection_by_identity,
)
from sase.config import get_agent_owner_config_snapshot, get_max_running_agents
from sase.core.time import format_local
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import MachineRecord, MachineStatus

from .base import FilterInput, OptionListNavigationMixin
from .config_center_session import SelectionBookmark

_ALIAS_WIDTH = 18
_STATE_WIDTH = 13
_HEALTH_WIDTH = 15
_CAPACITY_WIDTH = 18
_OBSERVED_WIDTH = 19


@dataclass(frozen=True)
class _MachineStatusSnapshot:
    """One status result plus local observation time."""

    status: MachineStatus
    checked_at: float


@dataclass(frozen=True)
class _MachineRow:
    """Renderable local or enrolled-machine row."""

    alias: str
    kind: Literal["here", "remote"]
    record: MachineRecord | None = None

    @property
    def identity(self) -> str:
        return f"{self.kind}:{self.alias}"


@dataclass(frozen=True)
class _MachineFlow:
    """Persistent action guidance rendered beside the selected row."""

    title: str
    body: tuple[str, ...]
    commands: tuple[str, ...]


class _MachinesFilterInput(FilterInput):
    """Filter input that lets focused Machines bindings keep working."""


class MachinesPane(OptionListNavigationMixin, Vertical):
    """Machine administration home for local and enrolled origins."""

    _option_list_id = "machines-list"
    BINDINGS = []

    def __init__(
        self,
        *,
        service: MachineService | None = None,
        session_state: SelectionBookmark | None = None,
        keymaps: MachinesPaneKeymaps | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._service = service or MachineService()
        self._keymaps = keymaps or load_keymap_registry({}).machines
        self._bindings = BindingsMap(build_machines_bindings(self._keymaps))
        self._bookmark = session_state or SelectionBookmark()
        self._records: list[_MachineRow] = []
        self._filtered_records: list[_MachineRow] = []
        self._statuses: dict[str, _MachineStatusSnapshot] = {}
        self._last_success_by_alias: dict[str, float] = {}
        self._text_filter = ""
        self._loading = False
        self._reload_pending = False
        self._load_error = ""
        self._loaded_at = time.time()
        self._loaded_once = False
        self._load_worker: Worker[Any] | None = None
        self._status_worker: Worker[Any] | None = None
        self._checking_alias = ""
        self._flow: _MachineFlow | None = self._connect_flow()
        self._selection_guard = ProgrammaticSelectionGuard()

    def compose(self) -> ComposeResult:
        yield Static(self._summary_text(), id="machines-summary")
        yield _MachinesFilterInput(
            placeholder="Type to filter machines...",
            id="machines-filter",
        )
        machines_box = Vertical(id="machines-box")
        machines_box.border_title = "Machines"
        with machines_box:
            yield Static(_column_header_text(), id="machines-columns")
            yield OptionList(id=self._option_list_id)
        detail_box = VerticalScroll(id="machines-detail-scroll")
        detail_box.border_title = "Details"
        with detail_box:
            yield Static("", id="machines-detail")
        flow_box = VerticalScroll(id="machines-flow-scroll")
        flow_box.border_title = "Action"
        with flow_box:
            yield Static("", id="machines-flow")
        yield Static(self._hints_text(), id="machines-hints")

    def on_mount(self) -> None:
        self._refresh_options()
        self._start_load()

    def on_unmount(self) -> None:
        for worker in (self._load_worker, self._status_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def focus_default(self) -> None:
        try:
            self.query_one("#machines-list", OptionList).focus()
        except Exception:
            pass

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        if active:
            self.focus_default()

    def action_focus_filter(self) -> None:
        self.query_one("#machines-filter", _MachinesFilterInput).focus()

    def action_reload_machines(self) -> None:
        self._start_load()

    def action_connect_machine(self) -> None:
        self._flow = self._connect_flow()
        self._update_flow()

    def action_check_status(self) -> None:
        row = self._selected_record()
        if row is None:
            self.notify("No machine selected", severity="warning")
            return
        if row.kind == "here":
            self.notify("Here is the local controller")
            return
        if self._status_worker is not None and not self._status_worker.is_finished:
            self.notify("Machine status check already running", severity="warning")
            return
        alias = row.alias
        self._checking_alias = alias
        self._flow = _MachineFlow(
            title=f"Checking {alias}",
            body=("Running bounded authenticated hello for the selected machine.",),
            commands=(f"sase machine status {alias}",),
        )
        self._update_summary()
        self._update_flow()
        self._status_worker = self.run_worker(
            lambda: self._service.status((alias,)),
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )

    def action_repair_machine(self) -> None:
        row = self._selected_remote_row("repair")
        if row is None:
            return
        self._flow = self._repair_flow(row.alias)
        self._update_flow()

    def action_rename_machine(self) -> None:
        row = self._selected_remote_row("rename")
        if row is None:
            return
        self._flow = _MachineFlow(
            title=f"Rename {row.alias}",
            body=(
                "Rename changes this controller's alias only; gateway identity and credentials stay pinned.",
                "Selection and actions must follow the pinned installation identity, not a reused alias.",
            ),
            commands=(f"sase machine rename {row.alias} <new-alias>",),
        )
        self._update_flow()

    def action_remove_machine(self) -> None:
        row = self._selected_remote_row("remove")
        if row is None:
            return
        self._flow = _MachineFlow(
            title=f"Remove {row.alias}",
            body=(
                "Removal deletes this controller's enrollment and local credential reference.",
                "It does not stop agents or other work that may still be running on the target machine.",
            ),
            commands=(f"sase machine remove {row.alias}",),
        )
        self._update_flow()

    def action_show_agents(self) -> None:
        row = self._selected_record()
        if row is None:
            self.notify("No machine selected", severity="warning")
            return
        query = machine_query_term("here" if row.kind == "here" else row.alias)
        app: Any = self.app
        app.current_tab = "agents"
        app._agent_search_query = query
        app._agent_search_query_seeded = False
        refilter = getattr(app, "_refilter_agents", None)
        if callable(refilter):
            refilter()
        schedule = getattr(app, "_schedule_agents_async_refresh", None)
        if callable(schedule):
            schedule(source="machines_pane")
        self.notify(f"Showing Agents filtered by {query}")
        try:
            self.screen.dismiss("machines")
        except Exception:
            pass

    def action_copy_machine_command(self) -> None:
        flow = self._flow
        if flow is None or not flow.commands:
            self.notify("No machine command to copy", severity="warning")
            return
        schedule_copy_delivery(
            self,
            "\n".join(flow.commands),
            copied_label="machine command",
            task_name="sase-copy-machine-command",
        )

    def on_key(self, event: events.Key) -> None:
        if self._filter_has_focus():
            return
        if event.key in split_key_alternatives(self._keymaps.focus_filter):
            event.stop()
            event.prevent_default()
            self.action_focus_filter()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "machines-filter":
            return
        self._text_filter = event.value
        self._apply_filters()
        self._refresh_options()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.focus_default()

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        if event.option is None or event.option.id is None:
            return
        identity = str(event.option.id)
        index = event.option_index
        if index is None or not (0 <= index < len(self._filtered_records)):
            return
        current_identity = self._record_id(self._filtered_records[index])
        if identity != current_identity or self._selection_guard.should_ignore(
            identity,
            index,
            current_identity=current_identity,
            current_row=index,
        ):
            return
        self._bookmark.record(identity, index)
        self._update_detail()
        self._update_flow()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._load_worker:
            self._handle_load_worker_state(event)
            return
        if event.worker is self._status_worker:
            self._handle_status_worker_state(event)

    def _handle_load_worker_state(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            selected = self._selected_record_id()
            result = event.worker.result
            self._loading = False
            if isinstance(result, tuple):
                self._records = list(result)
                self._loaded_at = time.time()
                self._loaded_once = True
                self._apply_filters()
                self._refresh_options(preferred_id=selected)
            else:
                self._load_error = "machine inventory returned no result"
                self._update_summary()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._load_error = (
                str(event.worker.error)
                if event.worker.error
                else "machine inventory load failed"
            )
            self._update_summary()
        elif event.state == WorkerState.CANCELLED:
            self._loading = False

        if (
            event.state
            in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED)
            and self._reload_pending
        ):
            self._reload_pending = False
            self.call_later(self._start_load)

    def _handle_status_worker_state(self, event: Worker.StateChanged) -> None:
        alias = self._checking_alias
        if event.state == WorkerState.SUCCESS:
            statuses = event.worker.result
            checked_at = time.time()
            if isinstance(statuses, tuple):
                for status in statuses:
                    if isinstance(status, MachineStatus):
                        self._statuses[status.alias] = _MachineStatusSnapshot(
                            status=status,
                            checked_at=checked_at,
                        )
                        if status.ok:
                            self._last_success_by_alias[status.alias] = checked_at
                self._flow = _MachineFlow(
                    title=f"Status checked: {alias}",
                    body=("Status results were recorded in this ACE session.",),
                    commands=(f"sase machine status {alias}",),
                )
        elif event.state == WorkerState.ERROR:
            message = (
                str(event.worker.error)
                if event.worker.error
                else "machine status check failed"
            )
            self._flow = _MachineFlow(
                title=f"Status failed: {alias}",
                body=(message,),
                commands=(f"sase machine status {alias}",),
            )
        self._checking_alias = ""
        self._update_summary()
        self._refresh_options(preferred_id=self._selected_record_id())
        self._update_flow()

    def _start_load(self) -> None:
        if self._loading:
            self._reload_pending = True
            return
        self._loading = True
        self._load_error = ""
        self._update_summary()
        self._load_worker = self.run_worker(
            self._load_rows,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )

    def _load_rows(self) -> tuple[_MachineRow, ...]:
        rows = [_MachineRow(alias=_local_machine_label(), kind="here")]
        rows.extend(
            _MachineRow(alias=record.alias, kind="remote", record=record)
            for record in self._service.list_machines()
        )
        return tuple(rows)

    def _apply_filters(self) -> None:
        needle = self._text_filter.casefold().strip()
        self._filtered_records = [
            record
            for record in self._records
            if not needle or needle in _row_haystack(record).casefold()
        ]

    def _create_options(self) -> list[Option]:
        if not self._filtered_records:
            if self._loading and not self._records:
                message = "Loading machine inventory..."
            elif self._text_filter.strip():
                message = "No machines match the current search"
            else:
                message = "No machine rows available"
            return [Option(Text(message, style="dim"), id="empty")]
        return [
            Option(_record_label(record, self._statuses), id=self._record_id(record))
            for record in self._filtered_records
        ]

    def _refresh_options(self, *, preferred_id: str | None = None) -> None:
        try:
            option_list = self.query_one("#machines-list", OptionList)
        except Exception:
            return
        current = preferred_id or self._selected_record_id() or self._bookmark.identity
        self._selection_guard.clear()
        selected_index: int | None = None
        option_list.clear_options()
        for option in self._create_options():
            option_list.add_option(option)
        if self._filtered_records:
            index = restore_selection_by_identity(
                self._filtered_records,
                prior_identity=current,
                prior_visual_row=self._bookmark.row,
                identity_fn=self._record_id,
            )
            identity = self._record_id(self._filtered_records[index])
            self._selection_guard.prepare(identity, index)
            option_list.highlighted = index
            selected_index = index
        else:
            option_list.highlighted = None
        self._record_bookmark(selected_index)
        self._update_summary()
        self._update_detail()
        self._update_flow()
        self._update_hints()

    def _record_bookmark(self, index: int | None) -> None:
        if index is None or not (0 <= index < len(self._filtered_records)):
            if self._loaded_once and not self._text_filter.strip():
                self._bookmark.record(None, None)
            return
        self._bookmark.record(self._record_id(self._filtered_records[index]), index)

    def _selected_record(self) -> _MachineRow | None:
        try:
            highlighted = self.query_one("#machines-list", OptionList).highlighted
        except Exception:
            return None
        if highlighted is None or not (0 <= highlighted < len(self._filtered_records)):
            return None
        return self._filtered_records[highlighted]

    def _selected_record_id(self) -> str | None:
        record = self._selected_record()
        return self._record_id(record) if record is not None else None

    @staticmethod
    def _record_id(record: _MachineRow) -> str:
        return record.identity

    def _selected_remote_row(self, verb: str) -> _MachineRow | None:
        row = self._selected_record()
        if row is None:
            self.notify(f"Select a machine to {verb}", severity="warning")
            return None
        if row.kind != "remote":
            self.notify(
                f"Select an enrolled remote machine to {verb}", severity="warning"
            )
            return None
        return row

    def _summary_text(self) -> Text:
        remotes = [row for row in self._records if row.kind == "remote"]
        ok = sum(
            1
            for row in remotes
            if (snapshot := self._statuses.get(row.alias)) is not None
            and snapshot.status.ok
        )
        unknown = len([row for row in remotes if row.alias not in self._statuses])
        errors = sum(
            1
            for row in remotes
            if (snapshot := self._statuses.get(row.alias)) is not None
            and not snapshot.status.ok
        )
        text = Text()
        text.append("machines:", style="dim")
        text.append(str(1 + len(remotes)), style="bold")
        text.append("  ·  enrolled:", style="dim")
        text.append(str(len(remotes)), style="bold #87D7FF")
        text.append("  ·  ok:", style="dim")
        text.append(str(ok), style="bold #00D7AF")
        text.append("  ·  unknown:", style="dim")
        text.append(str(unknown), style="bold #FFD700")
        if errors:
            text.append("  ·  issues:", style="dim")
            text.append(str(errors), style="bold red")
        if self._checking_alias:
            text.append(f"  ·  checking {self._checking_alias}...", style="#87D7FF")
        if self._loading:
            text.append("  ·  refreshing...", style="#87D7FF")
        if self._load_error:
            text.append(f"  ·  {self._load_error}", style="bold red")
        return text

    def _detail_text(self, row: _MachineRow | None) -> Text:
        text = Text()
        if row is None:
            text.append("No machine selected", style="dim")
            return text
        snapshot = self._statuses.get(row.alias)
        text.append(row.alias, style="bold")
        text.append("   ")
        text.append("local controller" if row.kind == "here" else "enrolled origin")
        text.append("\nHealth: ", style="dim")
        text.append(
            _health_label(row, snapshot)[0], style=_health_label(row, snapshot)[1]
        )
        text.append("    Last successful observation: ", style="dim")
        text.append(self._last_success_label(row, snapshot))
        text.append("\nCapacity: ", style="dim")
        text.append(_capacity_label(row))
        text.append("\nCapabilities: ", style="dim")
        text.append(_capabilities_label(snapshot))
        if row.record is not None:
            record = row.record
            text.append("\nEndpoint: ", style="dim")
            text.append(record.endpoint)
            text.append("    Provider: ", style="dim")
            text.append(record.provider_ref)
            text.append("\nPinned installation: ", style="dim")
            text.append(record.pinned_installation_id)
            if record.quarantined:
                text.append("\nQuarantine: ", style="bold red")
                text.append(
                    record.quarantine_reason or "installation quarantined", style="red"
                )
        if snapshot is not None:
            status = snapshot.status
            text.append("\nStatus message: ", style="dim")
            text.append(status.message or "-")
            if status.machine_selector:
                text.append("    Selector: ", style="dim")
                text.append(status.machine_selector)
            text.append("\nChecked: ", style="dim")
            text.append(
                format_local(snapshot.checked_at, "%Y-%m-%d %H:%M:%S", default="-")
            )
        return text

    def _flow_text(self) -> Text:
        flow = self._flow
        text = Text()
        if flow is None:
            text.append("Choose an action for the selected machine.", style="dim")
            return text
        text.append(flow.title, style="bold")
        for line in flow.body:
            text.append(f"\n{line}")
        if flow.commands:
            text.append("\n\nCommands", style="bold")
            for command in flow.commands:
                text.append("\n  ")
                text.append(command, style="#87D7FF")
        return text

    def _last_success_label(
        self,
        row: _MachineRow,
        snapshot: _MachineStatusSnapshot | None,
    ) -> str:
        if row.kind == "here":
            return "local"
        if snapshot is not None and snapshot.status.ok:
            return format_local(snapshot.checked_at, "%Y-%m-%d %H:%M:%S", default="-")
        last_ok = self._last_success_by_alias.get(row.alias)
        if last_ok is not None:
            return format_local(last_ok, "%Y-%m-%d %H:%M:%S", default="-")
        return "not observed in this session"

    def _connect_flow(self) -> _MachineFlow:
        return _MachineFlow(
            title="Connect a machine",
            body=(
                "Prepare the target, issue a bootstrap bundle into a protected file, review it on this controller, activate, then verify.",
                "Bootstrap bytes stay in the protected file path; do not paste them into prompts, argv, logs, or notes.",
                "If setup partially succeeds, rerun the controller command with the same protected file to resume at the recovery step.",
            ),
            commands=(
                "sase machine bootstrap --json > /path/protected/sase-bootstrap.json",
                "sase machine init -B /path/protected/sase-bootstrap.json",
                "sase machine status <alias>",
            ),
        )

    def _repair_flow(self, alias: str) -> _MachineFlow:
        return _MachineFlow(
            title=f"Repair {alias}",
            body=(
                "Repair rotates this controller's enrollment with a fresh one-time bundle.",
                "Changed installation identity must be reviewed and activated; cached rows are not rebound just because the alias matches.",
            ),
            commands=(
                f"sase machine bootstrap --json > /path/protected/sase-{alias}-bootstrap.json",
                f"sase machine repair {alias} -B /path/protected/sase-{alias}-bootstrap.json",
                f"sase machine status {alias}",
            ),
        )

    def _update_summary(self) -> None:
        try:
            self.query_one("#machines-summary", Static).update(self._summary_text())
        except Exception:
            pass

    def _update_detail(self) -> None:
        try:
            self.query_one("#machines-detail", Static).update(
                self._detail_text(self._selected_record())
            )
        except Exception:
            pass

    def _update_flow(self) -> None:
        try:
            self.query_one("#machines-flow", Static).update(self._flow_text())
        except Exception:
            pass

    def _update_hints(self) -> None:
        try:
            self.query_one("#machines-hints", Static).update(self._hints_text())
        except Exception:
            pass

    def _hints_text(self) -> str:
        d = _primary_key_display
        m = self._keymaps
        return (
            f"{d(m.next_option)}/{d(m.prev_option)} move  "
            f"{d(m.focus_filter)} filter  {d(m.connect_machine)} connect  "
            f"{d(m.check_status)} status  {d(m.show_agents)} agents  "
            f"{d(m.copy_command)} copy command"
        )

    def _filter_has_focus(self) -> bool:
        try:
            return self.query_one("#machines-filter", _MachinesFilterInput).has_focus
        except Exception:
            return False


def _local_machine_label() -> str:
    try:
        snapshot = get_agent_owner_config_snapshot()
        if snapshot.owner is not None:
            return snapshot.owner.machine_name
        if snapshot.selector:
            return snapshot.selector
    except Exception:
        pass
    return platform.node() or "here"


def _column_header_text() -> Text:
    text = Text(style="bold dim")
    text.append(f"{'ALIAS':<{_ALIAS_WIDTH}}")
    text.append(f"{'STATE':<{_STATE_WIDTH}}")
    text.append(f"{'HEALTH':<{_HEALTH_WIDTH}}")
    text.append(f"{'CAPACITY':<{_CAPACITY_WIDTH}}")
    text.append(f"{'LAST OBSERVED':<{_OBSERVED_WIDTH}}")
    text.append("ENDPOINT")
    return text


def _record_label(
    row: _MachineRow,
    statuses: dict[str, _MachineStatusSnapshot],
) -> Text:
    snapshot = statuses.get(row.alias)
    health, health_style = _health_label(row, snapshot)
    state = "here" if row.kind == "here" else _state_label(row, snapshot)
    text = Text()
    text.append(f"{row.alias:<{_ALIAS_WIDTH}.{_ALIAS_WIDTH}}", style="bold")
    text.append(f"{state:<{_STATE_WIDTH}.{_STATE_WIDTH}}", style=_state_style(state))
    text.append(f"{health:<{_HEALTH_WIDTH}.{_HEALTH_WIDTH}}", style=health_style)
    text.append(f"{_capacity_label(row):<{_CAPACITY_WIDTH}.{_CAPACITY_WIDTH}}")
    text.append(
        f"{_observed_label(row, snapshot):<{_OBSERVED_WIDTH}.{_OBSERVED_WIDTH}}",
        style="dim",
    )
    text.append(_endpoint_label(row), style="dim")
    return text


def _state_label(
    row: _MachineRow,
    snapshot: _MachineStatusSnapshot | None,
) -> str:
    if row.record is not None and row.record.quarantined:
        return "quarantined"
    if snapshot is None:
        return "not checked"
    return snapshot.status.state


def _state_style(state: str) -> str:
    if state in {"here", "ok"}:
        return "#00D7AF"
    if state in {"not checked", "skipped"}:
        return "#FFD700"
    return "bold red"


def _health_label(
    row: _MachineRow,
    snapshot: _MachineStatusSnapshot | None,
) -> tuple[str, str]:
    if row.kind == "here":
        return "local", "#00D7AF"
    if row.record is not None and row.record.quarantined:
        return "quarantined", "bold red"
    if snapshot is None:
        return "unknown", "#FFD700"
    if snapshot.status.ok:
        return "hello ok", "#00D7AF"
    return snapshot.status.state, "bold red"


def _capacity_label(row: _MachineRow) -> str:
    if row.kind == "here":
        try:
            return (
                "local capacity "
                f"{format_capacity_value(float(get_max_running_agents()))}"
            )
        except Exception:
            return "local capacity unknown"
    return "not reported"


def _observed_label(
    row: _MachineRow,
    snapshot: _MachineStatusSnapshot | None,
) -> str:
    if row.kind == "here":
        return "local"
    if snapshot is None:
        return "never checked"
    return format_local(snapshot.checked_at, "%H:%M:%S", default="-")


def _endpoint_label(row: _MachineRow) -> str:
    if row.kind == "here":
        return "local controller"
    return row.record.endpoint if row.record is not None else "-"


def _capabilities_label(snapshot: _MachineStatusSnapshot | None) -> str:
    if snapshot is None or not snapshot.status.capabilities:
        return "not reported"
    groups: list[str] = []
    for name, values in sorted(snapshot.status.capabilities.items()):
        if values:
            groups.append(f"{name}: {', '.join(values)}")
        else:
            groups.append(name)
    return "; ".join(groups)


def _row_haystack(row: _MachineRow) -> str:
    record = row.record
    return " ".join(
        part
        for part in (
            row.alias,
            row.kind,
            record.provider_ref if record is not None else "",
            record.endpoint if record is not None else "",
            record.pinned_installation_id if record is not None else "",
            "quarantined" if record is not None and record.quarantined else "",
        )
        if part
    )


def _primary_key_display(key: str) -> str:
    return key_display_name(split_key_alternatives(key)[0])


def machines_help_bindings(
    keymaps: MachinesPaneKeymaps,
) -> list[tuple[str, str]]:
    """Return effective Machines pane bindings for help surfaces."""

    d = _primary_key_display
    return [
        (
            f"{d(keymaps.next_option)} / {d(keymaps.prev_option)}",
            "Move through machines",
        ),
        (d(keymaps.focus_filter), "Filter machines"),
        (d(keymaps.connect_machine), "Open Connect flow"),
        (d(keymaps.check_status), "Check selected machine status"),
        (d(keymaps.repair_machine), "Show repair flow"),
        (d(keymaps.rename_machine), "Show rename command"),
        (d(keymaps.remove_machine), "Show removal command"),
        (d(keymaps.show_agents), "Show Agents for selected machine"),
        (d(keymaps.copy_command), "Copy current action command"),
        (d(keymaps.reload), "Reload machine inventory"),
    ]


__all__ = ["MachinesPane", "machines_help_bindings"]

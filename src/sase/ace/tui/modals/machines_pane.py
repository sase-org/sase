"""Admin Center Machines pane and persistent Connect guidance."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Vertical, VerticalScroll
from textual.worker import Worker, WorkerState
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.keymaps import (
    MachinesPaneKeymaps,
    build_machines_bindings,
    load_keymap_registry,
    split_key_alternatives,
)
from sase.ace.tui.util.selection import (
    ProgrammaticSelectionGuard,
    restore_selection_by_identity,
)
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import MachineStatus

from .base import OptionListNavigationMixin
from .config_center_session import SelectionBookmark
from .machines_pane_keybindings import machines_help_bindings
from .machines_pane_rendering import (
    column_header_text,
    connect_flow,
    create_options,
    detail_text,
    flow_text,
    hints_text,
    local_machine_label,
    repair_flow,
    row_haystack,
    summary_text,
)
from .machines_pane_types import (
    MachineFlow,
    MachineRow,
    MachineStatusSnapshot,
    MachinesFilterInput,
)


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
        self._records: list[MachineRow] = []
        self._filtered_records: list[MachineRow] = []
        self._statuses: dict[str, MachineStatusSnapshot] = {}
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
        self._flow: MachineFlow | None = connect_flow()
        self._selection_guard = ProgrammaticSelectionGuard()

    def compose(self) -> ComposeResult:
        yield Static(self._summary_text(), id="machines-summary")
        yield MachinesFilterInput(
            placeholder="Type to filter machines...",
            id="machines-filter",
        )
        machines_box = Vertical(id="machines-box")
        machines_box.border_title = "Machines"
        with machines_box:
            yield Static(column_header_text(), id="machines-columns")
            yield OptionList(id=self._option_list_id)
        detail_box = VerticalScroll(id="machines-detail-scroll")
        detail_box.border_title = "Details"
        with detail_box:
            yield Static("", id="machines-detail")
        flow_box = VerticalScroll(id="machines-flow-scroll")
        flow_box.border_title = "Action"
        with flow_box:
            yield Static("", id="machines-flow")
        yield Static(hints_text(self._keymaps), id="machines-hints")

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
        self.query_one("#machines-filter", MachinesFilterInput).focus()

    def action_reload_machines(self) -> None:
        self._start_load()

    def action_connect_machine(self) -> None:
        self._flow = connect_flow()
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
        self._flow = MachineFlow(
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
        self._flow = repair_flow(row.alias)
        self._update_flow()

    def action_rename_machine(self) -> None:
        row = self._selected_remote_row("rename")
        if row is None:
            return
        self._flow = MachineFlow(
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
        self._flow = MachineFlow(
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
        machine_name = "here" if row.kind == "here" else row.alias
        from sase.ace.tui.models.agent_live_query_engine import (
            agents_live_property_query_term,
            agents_unified_query_enabled,
        )

        if agents_unified_query_enabled():
            query = agents_live_property_query_term("machine", machine_name)
        else:
            from sase.ace.agent_query import machine_query_term

            query = machine_query_term(machine_name)
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
                        self._statuses[status.alias] = MachineStatusSnapshot(
                            status=status,
                            checked_at=checked_at,
                        )
                        if status.ok:
                            self._last_success_by_alias[status.alias] = checked_at
                self._flow = MachineFlow(
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
            self._flow = MachineFlow(
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

    def _load_rows(self) -> tuple[MachineRow, ...]:
        rows = [MachineRow(alias=local_machine_label(), kind="here")]
        rows.extend(
            MachineRow(alias=record.alias, kind="remote", record=record)
            for record in self._service.list_machines()
        )
        return tuple(rows)

    def _apply_filters(self) -> None:
        needle = self._text_filter.casefold().strip()
        self._filtered_records = [
            record
            for record in self._records
            if not needle or needle in row_haystack(record).casefold()
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
        for option in create_options(
            self._filtered_records,
            self._records,
            self._statuses,
            loading=self._loading,
            text_filter=self._text_filter,
        ):
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

    def _selected_record(self) -> MachineRow | None:
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
    def _record_id(record: MachineRow) -> str:
        return record.identity

    def _selected_remote_row(self, verb: str) -> MachineRow | None:
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
        return summary_text(
            self._records,
            self._statuses,
            checking_alias=self._checking_alias,
            loading=self._loading,
            load_error=self._load_error,
        )

    def _update_summary(self) -> None:
        try:
            self.query_one("#machines-summary", Static).update(self._summary_text())
        except Exception:
            pass

    def _update_detail(self) -> None:
        try:
            self.query_one("#machines-detail", Static).update(
                detail_text(
                    self._selected_record(),
                    self._statuses,
                    self._last_success_by_alias,
                )
            )
        except Exception:
            pass

    def _update_flow(self) -> None:
        try:
            self.query_one("#machines-flow", Static).update(flow_text(self._flow))
        except Exception:
            pass

    def _update_hints(self) -> None:
        try:
            self.query_one("#machines-hints", Static).update(hints_text(self._keymaps))
        except Exception:
            pass

    def _filter_has_focus(self) -> bool:
        try:
            return self.query_one("#machines-filter", MachinesFilterInput).has_focus
        except Exception:
            return False


__all__ = ["MachinesPane", "machines_help_bindings"]

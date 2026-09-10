"""Admin Center Machines pane behavior."""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.modals.config_center_session import SelectionBookmark
from sase.ace.tui.modals.machines_pane import MachinesPane
from sase.dispatch.models import MachineRecord, MachineStatus


def _machine(alias: str = "apollo") -> MachineRecord:
    return MachineRecord(
        alias=alias,
        provider_ref="tailnet",
        endpoint=f"https://{alias}.example.test",
        credential_ref=f"fleet:{alias}",
        pinned_installation_id="sase_inst_v1_" + "a" * 64,
    )


class _MachineService:
    def __init__(self, records: tuple[MachineRecord, ...]) -> None:
        self.records = records
        self.status_calls: list[tuple[str, ...]] = []

    def list_machines(self) -> tuple[MachineRecord, ...]:
        return self.records

    def status(
        self,
        aliases: tuple[str, ...],
    ) -> tuple[MachineStatus, ...]:
        self.status_calls.append(tuple(aliases))
        return tuple(
            MachineStatus(
                alias=alias,
                state="ok",
                provider_ref="tailnet",
                endpoint=f"https://{alias}.example.test",
                machine_selector=alias,
                installation_id="sase_inst_v1_" + "a" * 64,
                protocol_version=1,
                capabilities={"protocol": ("fleet.v1",), "lifecycle": ("stop",)},
                message="hello ok",
            )
            for alias in aliases
        )


class _MachinesPaneApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, service: _MachineService) -> None:
        super().__init__()
        self.service = service
        self.current_tab = "artifacts"
        self.refilter_count = 0
        self.refresh_sources: list[str] = []
        self.notifications: list[str] = []

    def compose(self) -> ComposeResult:
        yield MachinesPane(
            service=self.service,  # type: ignore[arg-type]
            session_state=SelectionBookmark(),
            id="machines",
        )

    def _refilter_agents(self) -> None:
        self.refilter_count += 1

    def _schedule_agents_async_refresh(self, *, source: str) -> None:
        self.refresh_sources.append(source)

    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.notifications.append(message)
        super().notify(message, *args, **kwargs)


async def test_machines_pane_loads_here_and_enrolled_machine() -> None:
    service = _MachineService((_machine("apollo"),))
    async with _MachinesPaneApp(service).run_test(size=(120, 36)) as pilot:
        pane = pilot.app.query_one("#machines", MachinesPane)
        await wait_for(pilot, lambda: pane._loaded_once)

        assert [row.kind for row in pane._records] == ["here", "remote"]
        assert pane._records[1].alias == "apollo"
        assert "Connect a machine" in pane.query_one("#machines-flow").render().plain


async def test_status_check_is_user_triggered_and_records_observation() -> None:
    service = _MachineService((_machine("apollo"),))
    async with _MachinesPaneApp(service).run_test(size=(120, 36)) as pilot:
        pane = pilot.app.query_one("#machines", MachinesPane)
        await wait_for(pilot, lambda: pane._loaded_once)
        pane.query_one("#machines-list", OptionList).highlighted = 1
        await wait_for(
            pilot,
            lambda: (
                (row := pane._selected_record()) is not None and row.alias == "apollo"
            ),
        )

        pane.action_check_status()
        await wait_for(pilot, lambda: service.status_calls == [("apollo",)])
        await wait_for(pilot, lambda: not pane._checking_alias)

        assert service.status_calls == [("apollo",)]
        assert pane._statuses["apollo"].status.ok
        detail = pane.query_one("#machines-detail").render().plain
        assert "hello ok" in detail
        assert "protocol: fleet.v1" in detail


async def test_show_agents_seeds_machine_query() -> None:
    service = _MachineService((_machine("apollo"),))
    async with _MachinesPaneApp(service).run_test(size=(120, 36)) as pilot:
        pane = pilot.app.query_one("#machines", MachinesPane)
        await wait_for(pilot, lambda: pane._loaded_once)
        pane.query_one("#machines-list", OptionList).highlighted = 1
        await wait_for(
            pilot,
            lambda: (
                (row := pane._selected_record()) is not None and row.alias == "apollo"
            ),
        )

        pane.action_show_agents()

        assert pilot.app.current_tab == "agents"
        assert pilot.app._agent_search_query == "machine:apollo"
        assert pilot.app.refilter_count == 1
        assert pilot.app.refresh_sources == ["machines_pane"]


async def test_remote_actions_render_persistent_copyable_commands() -> None:
    service = _MachineService((_machine("apollo"),))
    async with _MachinesPaneApp(service).run_test(size=(120, 36)) as pilot:
        pane = pilot.app.query_one("#machines", MachinesPane)
        await wait_for(pilot, lambda: pane._loaded_once)
        pane.query_one("#machines-list", OptionList).highlighted = 1
        await wait_for(
            pilot,
            lambda: (
                (row := pane._selected_record()) is not None and row.alias == "apollo"
            ),
        )

        pane.action_repair_machine()

        flow = pane.query_one("#machines-flow").render().plain
        assert "Repair apollo" in flow
        assert "sase machine repair apollo -B" in flow

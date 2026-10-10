"""Admin Center Machines pane behavior."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agents._query_persistence import AgentQueryPersistenceMixin
from sase.ace.tui.models import agent_query_persistence as query_store
from sase.ace.tui.models.agent_tab_index import AgentTabIndex
from sase.ace.tui.modals.config_center_session import SelectionBookmark
from sase.ace.tui.modals.machines_pane import MachinesPane
from sase.core.agent_tab import (
    DEFAULT_AGENT_TAB_KEY,
    AgentTabCatalogEntry,
    AgentTabKey,
)
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


class _MachinesPaneApp(AgentQueryPersistenceMixin, App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, service: _MachineService) -> None:
        super().__init__()
        self.service = service
        self.current_tab = "artifacts"
        self._agent_search_query = ""
        self._agent_search_query_seeded = False
        self._agent_search_query_seed_attempted = False
        self._ensure_agents_query_persistence_state()
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
        await wait_for(
            pilot,
            lambda: not pane._checking_alias and "apollo" in pane._statuses,
        )

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
        await pilot.app._flush_agents_query_state()
        result = query_store.load_agent_query_snapshot(
            active_dialect=query_store.DIALECT_UNIFIED
        )
        assert result.snapshot is not None
        assert result.snapshot.record.source == "machine:apollo"


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


async def test_show_agents_filter_uses_local_for_here_row() -> None:
    service = _MachineService((_machine("apollo"),))
    async with _MachinesPaneApp(service).run_test(size=(120, 36)) as pilot:
        pane = pilot.app.query_one("#machines", MachinesPane)
        await wait_for(pilot, lambda: pane._loaded_once)
        pane.query_one("#machines-list", OptionList).highlighted = 0
        await wait_for(
            pilot,
            lambda: (row := pane._selected_record()) is not None and row.kind == "here",
        )

        pane.action_show_agents_filter()

        assert pilot.app.current_tab == "agents"
        assert pilot.app._agent_search_query == "machine:local"


async def test_show_agents_selects_machine_tab_when_strip_visible() -> None:
    service = _MachineService((_machine("apollo"),))
    async with _MachinesPaneApp(service).run_test(size=(120, 36)) as pilot:
        pane = pilot.app.query_one("#machines", MachinesPane)
        await wait_for(pilot, lambda: pane._loaded_once)
        machine_key = AgentTabKey.machine("sase_inst_v1_" + "a" * 64)
        pilot.app._agent_tab_index = AgentTabIndex(
            (
                AgentTabCatalogEntry(DEFAULT_AGENT_TAB_KEY, "default", "main", 1),
                AgentTabCatalogEntry(machine_key, "machine", "⌨ apollo", 2),
            ),
            {},
            {},
        )
        pilot.app._active_agent_tab = DEFAULT_AGENT_TAB_KEY
        pilot.app._agent_tab_latched_key = None
        switches: list[Any] = []

        def _switch(key: Any, reason: str = "") -> bool:
            switches.append(key)
            return True

        pilot.app._switch_agents_tab = _switch  # type: ignore[attr-defined]
        pane.query_one("#machines-list", OptionList).highlighted = 1
        await wait_for(
            pilot,
            lambda: (
                (row := pane._selected_record()) is not None and row.alias == "apollo"
            ),
        )

        pane.action_show_agents()

        assert pilot.app.current_tab == "agents"
        assert switches == [machine_key]
        assert pilot.app._agent_search_query == ""


async def test_show_agents_falls_back_to_filter_when_strip_hidden() -> None:
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


def test_machine_tab_key_resolves_local_remote_and_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui import agent_tabs_settings as settings_mod
    from sase.ace.tui.modals.machines_pane_types import MachineRow

    pane = MachinesPane.__new__(MachinesPane)
    local = MachineRow(alias="athena", kind="here")
    assert pane._machine_tab_key(local) == DEFAULT_AGENT_TAB_KEY
    remote = MachineRow(alias="apollo", kind="remote", record=_machine("apollo"))
    assert pane._machine_tab_key(remote) == AgentTabKey.machine(
        "sase_inst_v1_" + "a" * 64
    )
    monkeypatch.setattr(
        settings_mod,
        "agent_tabs_view_config",
        lambda: SimpleNamespace(pinned_by_alias={}),
    )
    unknown = MachineRow(alias="zeus", kind="remote", record=None)
    assert pane._machine_tab_key(unknown) is None

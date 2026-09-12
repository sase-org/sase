"""TUI-level Fleet refresh laziness regressions."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.ace.tui.actions.agents._fleet import AgentFleetMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fleet_agents import FleetRowsProjection
from sase.dispatch.federation import FederationConfig, FederationWorkerSettings
from sase.ace.tui.util.nav_gate import NavigationGate
from tests.ace.tui.fleet_fixture import (
    OfflineFleetFacade,
    fleet_counts,
    fleet_catalog_cursor,
    fleet_catalog_snapshot_id,
    fleet_config,
    fleet_host_response,
    fleet_summary,
)


class _FleetRefreshHarness(AgentFleetMixin):
    """Minimal Agents-tab host for exercising fleet refresh projection."""

    def __init__(self, *, mode: str = "focus") -> None:
        self.current_agents_subtab = mode
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_local_with_children: list[Agent] = []
        self._agents_local_visible: list[Agent] = []
        self._agents_fleet_rows: list[Agent] = []
        self._agents_fleet_focus_rows: list[Agent] = []
        self._agents_fleet_projection = FleetRowsProjection()
        self._agents_fleet_async_tasks: set[Any] = set()
        self._agents_fleet_refresh_generation = 1
        self._agents_fleet_loading = True
        self._agents_fleet_available = False
        self._agents_fleet_last_error = None
        self._agents_refresh_active_source = "unknown"
        self.header_updates = 0
        self.reproject_sources: list[str] = []
        self.attention_announcements: list[FleetRowsProjection] = []
        self._nav_gate = NavigationGate()
        self.timers: list[tuple[float, Callable[[], None]]] = []

    def _update_agents_header(self) -> None:
        self.header_updates += 1

    def _reproject_agents_from_current_mode(
        self,
        *,
        source: str,
        selected_identity: object | None = None,
    ) -> None:
        del selected_identity
        self.reproject_sources.append(source)
        local_base = list(self._agents_local_with_children)
        self._agents_with_children = self._agents_source_for_current_mode(local_base)
        self._agents = list(self._agents_with_children)

    def _announce_remote_attention(self, projection: FleetRowsProjection) -> None:
        self.attention_announcements.append(projection)

    def notify(self, *_args: object, **_kwargs: object) -> None:
        pass

    def set_timer(self, delay: float, callback: Callable[[], None]) -> None:
        self.timers.append((delay, callback))


def test_unified_agents_status_text_labels_scope_and_staleness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FleetRefreshHarness(mode="focus")
    app._agents_fleet_loading = False
    app._agents = [
        Agent(
            AgentType.RUNNING,
            "local-work",
            "/tmp/local-project.yml",
            "QUESTION",
            None,
            status_bucket="question",
            agent_name="local-work",
        ),
        Agent(
            AgentType.RUNNING,
            "remote-work",
            "/fleet/apollo/project.yml",
            "RUNNING",
            None,
            status_bucket="running",
            agent_name="remote-work",
            fleet_origin_alias="apollo",
            fleet_logical_key="remote-logical-key",
            fleet_attention={"kind": "question", "state": "pending"},
        ),
    ]
    app._agents_fleet_projection = FleetRowsProjection(
        configured_host_count=2,
        diagnostics=(
            {
                "code": "host_stale",
                "severity": "warning",
                "alias": "mac",
                "message": "cached projection is stale",
            },
        ),
    )
    monkeypatch.setattr(fleet_mod, "get_machine_name", lambda: "athena")

    assert app._unified_agents_status_text() == (
        "here: athena · 2 active · 2 needs you · 2 machines · mac unknown"
    )


@pytest.mark.asyncio
async def test_agents_refresh_hydrates_catalog_in_focus_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    response = fleet_host_response(summaries=(summary,))
    facade = OfflineFleetFacade(summary_response=response, catalog_response=response)
    app = _FleetRefreshHarness(mode="focus")
    local = Agent(
        AgentType.RUNNING,
        "local-work",
        "/tmp/local-project.yml",
        "RUNNING",
        None,
        agent_name="local-work",
    )
    app._agents_local_with_children = [local]

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: fleet_config())
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="apply")

    assert facade.calls == ["summary", "catalog"]
    assert app.current_agents_subtab == "focus"
    assert [row.cl_name for row in app._agents] == ["local-work", "sase-main"]
    assert [row.fleet_logical_key for row in app._agents_fleet_rows] == [
        summary["logical_key"]
    ]
    assert app._agents_fleet_focus_rows == []


@pytest.mark.asyncio
async def test_zero_machine_config_refresh_performs_no_remote_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FleetRefreshHarness(mode="focus")
    built_facades: list[FederationConfig] = []
    empty_config = FederationConfig(
        worker=FederationWorkerSettings(enabled=True),
        hosts=(),
    )

    def build_facade(config: FederationConfig) -> OfflineFleetFacade:
        built_facades.append(config)
        raise AssertionError("zero-machine refresh must not build a federation facade")

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: empty_config)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", build_facade)

    await app._run_agents_fleet_refresh(generation=1, source="manual")

    assert built_facades == []
    assert app.current_agents_subtab == "focus"
    assert app._agents_fleet_available is False
    assert app._agents_fleet_rows == []
    assert app._agents_fleet_focus_rows == []
    assert app._agents == []
    assert app.reproject_sources == ["fleet_refresh"]


@pytest.mark.asyncio
async def test_fleet_refresh_apply_defers_behind_active_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    response = fleet_host_response(summaries=(summary,))
    facade = OfflineFleetFacade(summary_response=response, catalog_response=response)
    app = _FleetRefreshHarness(mode="focus")
    app._nav_gate.record()

    monkeypatch.setattr(fleet_mod, "load_federation_config", fleet_config)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="manual")

    assert app._agents == []
    assert app._agents_fleet_loading is True
    assert len(app.timers) == 1

    app._nav_gate = NavigationGate(window_s=0)
    _delay, callback = app.timers.pop()
    callback()

    assert [row.fleet_logical_key for row in app._agents_fleet_rows] == [
        summary["logical_key"]
    ]
    assert app._agents_fleet_loading is False
    assert app.reproject_sources == ["fleet_refresh"]


@pytest.mark.asyncio
async def test_fleet_catalog_refresh_requests_legal_pages_and_logical_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def serialized(response: Mapping[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(response))

    summary = fleet_summary(agent_id="agent-a")
    page_one = fleet_host_response(summaries=(summary,))
    next_cursor = fleet_catalog_cursor(fleet_catalog_snapshot_id("apollo"), 100)
    page_one["hosts"][0]["payload"]["page"]["next_cursor"] = next_cursor
    page_one["hosts"][0]["payload"]["page"]["has_more"] = True
    page_one["hosts"][0]["payload"]["page"]["total_matching_rows"] = 2
    page_one["hosts"][0]["payload"]["counts"] = fleet_counts(
        (summary,),
        running=1,
    )
    page_two_summary = fleet_summary(agent_id="agent-b", status="done")
    page_two = fleet_host_response(summaries=(page_two_summary,))
    page_two["hosts"][0]["payload"]["counts"] = fleet_counts(
        (page_two_summary,),
        running=1,
    )

    class _PagingFacade(OfflineFleetFacade):
        async def summary(
            self,
            *,
            cache_only: bool = False,
            timeout_seconds: float | None = None,
        ) -> dict[str, Any]:
            response = await super().summary(
                cache_only=cache_only,
                timeout_seconds=timeout_seconds,
            )
            return serialized(response)

        async def catalog(
            self,
            query: dict[str, Any],
            *,
            cache_only: bool = False,
            timeout_seconds: float | None = None,
        ) -> dict[str, Any]:
            self.calls.append("catalog")
            self.requests.append(
                {
                    "operation": "catalog",
                    "request": dict(query),
                    "cache_only": cache_only,
                    "timeout_seconds": timeout_seconds,
                }
            )
            if query.get("cursor") == next_cursor:
                return serialized(page_two)
            return serialized(page_one)

        async def catalog_hosts(
            self,
            queries: Iterable[Mapping[str, Any]],
            *,
            cache_only: bool = False,
            timeout_seconds: float | None = None,
        ) -> dict[str, Any]:
            self.calls.append("catalog_hosts")
            request = [dict(query) for query in queries]
            self.requests.append(
                {
                    "operation": "catalog_hosts",
                    "request": request,
                    "cache_only": cache_only,
                    "timeout_seconds": timeout_seconds,
                }
            )
            query = request[0]["query"] if request else {}
            if query.get("cursor") == next_cursor:
                return serialized(page_two)
            return serialized(page_one)

    facade = _PagingFacade(
        summary_response=page_one,
    )
    app = _FleetRefreshHarness(mode="focus")
    monkeypatch.setattr(fleet_mod, "load_federation_config", fleet_config)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="manual")

    catalog_requests = [
        item["request"] for item in facade.requests if item["operation"] == "catalog"
    ]
    assert catalog_requests[0] == {
        "schema_version": 1,
        "limit": 100,
        "include_terminal": True,
    }
    catalog_host_requests = [
        item["request"]
        for item in facade.requests
        if item["operation"] == "catalog_hosts"
    ]
    assert catalog_host_requests == [
        [
            {
                "schema_version": 1,
                "installation_id": summary["logical_locator"]["project"]["origin"][
                    "installation_id"
                ],
                "query": {
                    "schema_version": 1,
                    "limit": 100,
                    "include_terminal": True,
                    "cursor": next_cursor,
                },
            }
        ]
    ]
    assert [request["operation"] for request in facade.requests] == [
        "summary",
        "catalog",
        "catalog_hosts",
    ]
    assert {row.fleet_logical_key for row in app._agents_fleet_rows} == {
        summary["logical_key"],
        page_two_summary["logical_key"],
    }

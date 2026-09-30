"""Fleet refresh orchestration: catalog hydration and remote-work gating."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.dispatch.federation import FederationConfig, FederationWorkerSettings
from sase.dispatch.models import MachineDiagnostic
from tests.ace.tui._agents_fleet_refresh_laziness_shared import FleetRefreshHarness
from tests.ace.tui.fleet_fixture import (
    OfflineFleetFacade,
    fleet_catalog_cursor,
    fleet_catalog_snapshot_id,
    fleet_config,
    fleet_counts,
    fleet_host_response,
    fleet_invalid_host_response,
    fleet_summary,
)

__all__ = [
    "test_agents_refresh_hydrates_catalog",
    "test_fleet_catalog_refresh_requests_legal_pages_and_logical_keys",
    "test_fleet_refresh_apply_defers_behind_active_navigation",
    "test_fleet_refresh_preserves_feed_issues_with_config_diagnostics",
    "test_zero_machine_config_refresh_performs_no_remote_work",
]


@pytest.mark.asyncio
async def test_agents_refresh_hydrates_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    response = fleet_host_response(summaries=(summary,))
    facade = OfflineFleetFacade(summary_response=response, catalog_response=response)
    app = FleetRefreshHarness()
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
    assert [row.cl_name for row in app._agents] == ["local-work", "sase-main"]
    assert [row.fleet_logical_key for row in app._agents_fleet_rows] == [
        summary["logical_key"]
    ]
    assert app._agents_fleet_focus_rows == []


@pytest.mark.asyncio
async def test_zero_machine_config_refresh_performs_no_remote_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FleetRefreshHarness()
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
    assert app._agents_fleet_available is False
    assert app._agents_fleet_rows == []
    assert app._agents_fleet_focus_rows == []
    assert app._agents == []
    assert app.reproject_sources == ["fleet_refresh"]


@pytest.mark.asyncio
async def test_fleet_refresh_preserves_feed_issues_with_config_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = fleet_invalid_host_response(
        alias="apollo",
        error="invalid_envelope",
        cached=True,
        age_seconds=18_000.0,
    )
    facade = OfflineFleetFacade(summary_response=response, catalog_response=response)
    config = replace(
        fleet_config(),
        diagnostics=(
            MachineDiagnostic(
                code="dispatch_config_warning",
                severity="warning",
                alias="mac",
                message="dispatch config warning",
            ),
        ),
    )
    app = FleetRefreshHarness()

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: config)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="manual")

    projection = app._agents_fleet_projection
    assert [item["code"] for item in projection.diagnostics] == [
        "dispatch_config_warning"
    ]
    assert len(projection.host_feed_issues) == 1
    assert projection.host_feed_issues[0].alias == "apollo"
    assert projection.host_feed_issues[0].diagnostic == "invalid_envelope"
    assert app._agents_fleet_rows == []
    assert "apollo: feed invalid: invalid_envelope (cached 5h ago)" in (
        app._agents_fleet_problem_text()
    )


@pytest.mark.asyncio
async def test_fleet_refresh_apply_defers_behind_active_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    response = fleet_host_response(summaries=(summary,))
    facade = OfflineFleetFacade(summary_response=response, catalog_response=response)
    app = FleetRefreshHarness()
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
    app = FleetRefreshHarness()
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

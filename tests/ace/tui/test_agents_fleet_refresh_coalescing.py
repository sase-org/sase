"""Single-flight fleet refresh: coalescing, forced restart, valid fallbacks."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.dispatch.counts import normalize_fleet_federation_response
from sase.dispatch.federation import FederationWorkerUnavailable
from tests.ace.tui._agents_fleet_refresh_laziness_shared import FleetRefreshHarness
from tests.ace.tui.fleet_fixture import (
    OfflineFleetFacade,
    ScriptedFleetFacade,
    fleet_config,
    fleet_host_response,
    fleet_summary,
)

__all__ = [
    "test_fleet_call_fallback_round_trips_through_normalizer",
    "test_forced_refresh_cancels_and_restarts",
    "test_nonforced_refreshes_coalesce_into_one_rerun",
    "test_normalization_failure_becomes_visible_fleet_error",
    "test_unavailable_catalog_degrades_to_projection",
]


async def _drain_refresh_tasks(app: FleetRefreshHarness) -> None:
    for _ in range(500):
        if (
            not app._agents_fleet_async_tasks
            and not app._agents_fleet_refresh_pending
            and not app._agents_fleet_loading
        ):
            return
        await asyncio.sleep(0.01)  # sase-test-wait: poll for task settlement
    raise AssertionError("fleet refresh tasks did not settle")


async def _wait_until_in_flight(facade: ScriptedFleetFacade) -> None:
    for _ in range(500):
        if "summary" in facade.calls:
            return
        await asyncio.sleep(0.01)  # sase-test-wait: wait for in-flight refresh
    raise AssertionError("fleet refresh did not start")


@pytest.mark.asyncio
async def test_nonforced_refreshes_coalesce_into_one_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    response = fleet_host_response(summaries=(summary,))
    facade = ScriptedFleetFacade(
        summary_response=response,
        catalog_response=response,
        delays={"summary": 0.05, "catalog": 0.05},
    )
    app = FleetRefreshHarness()

    monkeypatch.setattr(fleet_mod, "load_federation_config", fleet_config)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    app._schedule_agents_fleet_refresh(source="first")
    app._schedule_agents_fleet_refresh(source="second")
    app._schedule_agents_fleet_refresh(source="third")

    assert app._agents_fleet_refresh_pending is True
    assert app._agents_fleet_refresh_pending_source == "third"
    await _drain_refresh_tasks(app)

    assert facade.calls.count("summary") == 2
    assert app._agents_fleet_refresh_pending is False
    assert app._agents_fleet_refresh_generation == 3
    assert [row.fleet_logical_key for row in app._agents_fleet_rows] == [
        summary["logical_key"]
    ]


@pytest.mark.asyncio
async def test_forced_refresh_cancels_and_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    response = fleet_host_response(summaries=(summary,))
    facade = ScriptedFleetFacade(
        summary_response=response,
        catalog_response=response,
        delays={"summary": 0.05, "catalog": 0.05},
    )
    app = FleetRefreshHarness()

    monkeypatch.setattr(fleet_mod, "load_federation_config", fleet_config)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    app._schedule_agents_fleet_refresh(source="stale")
    # Let the first refresh get in flight (inside its summary delay) so the
    # forced refresh genuinely cancels a running refresh and restarts it.
    await _wait_until_in_flight(facade)
    app._schedule_agents_fleet_refresh(source="forced", force=True)
    await _drain_refresh_tasks(app)

    assert facade.calls.count("summary") == 2
    assert app._agents_fleet_refresh_pending is False
    assert [row.fleet_logical_key for row in app._agents_fleet_rows] == [
        summary["logical_key"]
    ]


@pytest.mark.asyncio
async def test_fleet_call_fallback_round_trips_through_normalizer() -> None:
    app = FleetRefreshHarness()

    async def _unavailable() -> Mapping[str, Any]:
        raise FederationWorkerUnavailable("worker gone")

    payload = await app._fleet_call("summary", _unavailable)
    normalized = normalize_fleet_federation_response(payload)

    assert normalized["diagnostics"][0]["code"] == "fleet_summary_unavailable"


@pytest.mark.asyncio
async def test_unavailable_catalog_degrades_to_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    response = fleet_host_response(summaries=(summary,))

    class _CatalogDownFacade(OfflineFleetFacade):
        async def catalog(
            self,
            query: Mapping[str, Any],
            *,
            cache_only: bool = False,
            timeout_seconds: float | None = None,
        ) -> dict[str, Any]:
            raise FederationWorkerUnavailable("catalog worker is slow")

    facade = _CatalogDownFacade(summary_response=response)
    app = FleetRefreshHarness()

    monkeypatch.setattr(fleet_mod, "load_federation_config", fleet_config)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="manual")

    assert app._agents_fleet_last_error is None
    codes = [item["code"] for item in app._agents_fleet_projection.diagnostics]
    assert "fleet_catalog_unavailable" in codes


@pytest.mark.asyncio
async def test_normalization_failure_becomes_visible_fleet_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BadWireFacade(OfflineFleetFacade):
        async def catalog(
            self,
            query: Mapping[str, Any],
            *,
            cache_only: bool = False,
            timeout_seconds: float | None = None,
        ) -> dict[str, Any]:
            raise ValueError("missing field schema_version")

    app = FleetRefreshHarness()

    monkeypatch.setattr(fleet_mod, "load_federation_config", fleet_config)
    monkeypatch.setattr(
        fleet_mod, "build_federation_facade", lambda _config: _BadWireFacade()
    )

    await app._run_agents_fleet_refresh(generation=1, source="manual")

    assert app._agents_fleet_last_error == "missing field schema_version"

"""Fleet fault j/k key-to-paint benchmark cases."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.dispatch.federation import FederationConfig
from sase.dispatch.follow_store import FollowStoreSnapshot
from tests.ace.tui._bench_tui_jk_helpers import (
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
    _warm_agents_navigation,
)
from tests.ace.tui.fleet_fixture import (
    ScriptedFleetFacade,
    fleet_config_for_hosts,
    fleet_fault_diagnostic,
    fleet_host_payload,
    fleet_installation_id,
    fleet_multi_host_response,
    fleet_summary,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

_FLEET_FAULT_P95_BUDGET_MS = 16.0
_FLEET_FAULT_DELAY_SECONDS = 4.5
_FLEET_FAULT_KEYS_PER_DIRECTION = 80


@pytest.mark.parametrize(
    "scenario",
    ("hung_host", "reconnect_churn", "event_burst"),
)
async def test_bench_agents_fleet_jk_fault_scenarios(
    _perf_jsonl: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    """Keep Fleet j/k p95 below 16 ms while offline fault scripts are active."""
    apollo_id = fleet_installation_id("a")
    zeus_id = fleet_installation_id("b")
    config = fleet_config_for_hosts(("apollo", apollo_id), ("zeus", zeus_id))
    stable_response = _fleet_response(
        ("apollo", apollo_id, 18),
        ("zeus", zeus_id, 18),
    )
    fault_response = _fault_response(scenario, apollo_id=apollo_id, zeus_id=zeus_id)
    stable_facade = ScriptedFleetFacade(
        summary_response=stable_response,
        catalog_response=stable_response,
    )
    fault_facade = ScriptedFleetFacade(
        summary_response=fault_response,
        catalog_response=fault_response,
        delays={"catalog": _FLEET_FAULT_DELAY_SECONDS},
    )

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: config)
    monkeypatch.setattr(
        fleet_mod,
        "_load_reconciled_follow_snapshot",
        _empty_follow_snapshot,
    )
    monkeypatch.setattr(
        fleet_mod,
        "build_federation_facade",
        lambda _config: stable_facade,
    )

    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_fleet_rows(app, stable_response, config=config)
        await pilot.pause(0.2)
        await _warm_agents_navigation(pilot)

        monkeypatch.setattr(
            fleet_mod,
            "build_federation_facade",
            lambda _config: fault_facade,
        )
        _install_fleet_rows(app, fault_response, config=config)
        await pilot.pause(0.2)
        app._schedule_agents_fleet_refresh(source=f"bench_{scenario}", force=True)
        await pilot.pause(0.01)
        await _warm_agents_navigation(pilot)
        before = len(_read_samples(_perf_jsonl))
        for _ in range(_FLEET_FAULT_KEYS_PER_DIRECTION):
            await pilot.press("j")
            await pilot.pause()
        for _ in range(_FLEET_FAULT_KEYS_PER_DIRECTION):
            await pilot.press("k")
            await pilot.pause()
        await _wait_for_fleet_refresh(app)

    samples = [
        sample
        for sample in _read_samples(_perf_jsonl)[before:]
        if sample.get("tab") == "agents" and sample.get("action") in {"next", "prev"}
    ]
    summary = _summarize(samples)
    _print_table(f"Agents Fleet j/k fault scenario {scenario}:", summary)
    assert set(summary) == {"next", "prev"}
    assert all(
        stats["p95"] < _FLEET_FAULT_P95_BUDGET_MS for stats in summary.values()
    ), f"Fleet fault scenario {scenario} exceeded 16 ms p95: {summary}"
    stall_path = _perf_jsonl.with_name("tui_stalls.jsonl")
    assert not stall_path.exists() or not stall_path.read_text().strip()


def _fleet_response(*host_specs: tuple[str, str, int]) -> dict[str, Any]:
    hosts = []
    for alias, installation_id, count in host_specs:
        hosts.append(
            fleet_host_payload(
                alias=alias,
                installation_id=installation_id,
                summaries=(
                    fleet_summary(
                        installation_id=installation_id,
                        agent_id=f"{alias}-agent-{index:03d}",
                        run_id=f"{alias}-run-{index:03d}",
                        revision=index + 1,
                        patch_name=f"{alias}-fleet",
                        bounded_intent="exercise Fleet j/k under faults",
                    )
                    for index in range(count)
                ),
            )
        )
    return fleet_multi_host_response(*hosts, configured_hosts=len(host_specs))


def _fault_response(
    scenario: str,
    *,
    apollo_id: str,
    zeus_id: str,
) -> dict[str, Any]:
    if scenario == "hung_host":
        return fleet_multi_host_response(
            fleet_host_payload(
                alias="apollo",
                installation_id=apollo_id,
                summaries=(
                    fleet_summary(
                        installation_id=apollo_id,
                        agent_id=f"apollo-agent-{index:03d}",
                        run_id=f"apollo-run-{index:03d}",
                        revision=index + 2,
                    )
                    for index in range(18)
                ),
            ),
            configured_hosts=2,
            diagnostics=(
                fleet_fault_diagnostic(
                    alias="zeus",
                    operation="catalog",
                    code="host_deadline_exceeded",
                    message="zeus catalog exceeded the offline deadline",
                ),
            ),
            partial=True,
        )
    if scenario == "reconnect_churn":
        return fleet_multi_host_response(
            fleet_host_payload(
                alias="apollo",
                installation_id=apollo_id,
                summaries=(
                    fleet_summary(
                        installation_id=apollo_id,
                        agent_id=f"apollo-agent-{index:03d}",
                        run_id=f"apollo-run-{index:03d}",
                        revision=index + 2,
                    )
                    for index in range(18)
                ),
            ),
            fleet_host_payload(
                alias="zeus",
                installation_id=zeus_id,
                summaries=(
                    fleet_summary(
                        installation_id=zeus_id,
                        agent_id=f"zeus-agent-{index:03d}",
                        run_id=f"zeus-run-{index:03d}",
                        revision=index + 2,
                        status="starting" if index % 2 else "running",
                    )
                    for index in range(18)
                ),
                freshness="aging",
                connection_health="reconnecting",
            ),
            diagnostics=(
                fleet_fault_diagnostic(
                    alias="zeus",
                    operation="summary",
                    code="host_reconnect_churn",
                    message="zeus reconnected during the offline refresh",
                ),
            ),
            partial=True,
        )
    if scenario == "event_burst":
        return _fleet_response(("apollo", apollo_id, 24), ("zeus", zeus_id, 24))
    raise AssertionError(f"unknown Fleet fault scenario: {scenario}")


def _install_fleet_rows(
    app: AceApp,
    response: dict[str, Any],
    *,
    config: FederationConfig,
) -> None:
    projection = project_fleet_agents(catalog_response=response)
    app._agents_local_with_children = []
    app._agents_local_visible = []
    app._agents_fleet_projection = projection
    app._agents_fleet_rows = list(projection.fleet_rows)
    app._agents_fleet_focus_rows = list(projection.focus_rows)
    app._agents_fleet_available = True
    app.current_idx = 0
    app.current_agents_subtab = "fleet"
    app._apply_fleet_projection(
        projection,
        config=config,
        generation=app._agents_fleet_refresh_generation,
    )
    app._refresh_agents_display(list_changed=True, defer_detail=True)


async def _wait_for_fleet_refresh(app: AceApp) -> None:
    deadline = asyncio.get_running_loop().time() + 5.0
    while any(not task.done() for task in app._agents_fleet_async_tasks):
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Fleet benchmark refresh did not settle within 5s")
        await asyncio.sleep(0.01)  # sase-test-wait: poll Fleet refresh task completion


def _empty_follow_snapshot() -> FollowStoreSnapshot:
    return FollowStoreSnapshot(
        schema_version=1,
        records=(),
        tombstones=(),
        path="/tmp/sase-fleet-follows.json",
    )

"""Off-loop fleet projection with generation/tab/selection revalidation."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fleet_agents import FleetRowsProjection
from tests.ace.tui._agents_fleet_refresh_laziness_shared import FleetRefreshHarness
from tests.ace.tui.fleet_fixture import (
    OfflineFleetFacade,
    fleet_config,
    fleet_host_response,
    fleet_summary,
)


def _remote_row() -> Agent:
    return Agent(
        AgentType.RUNNING,
        "sase-main",
        "/fleet/apollo/project.yml",
        "RUNNING",
        None,
        agent_name="sase-main",
        fleet_origin_alias="apollo",
        fleet_logical_key="apollo:sase-main",
    )


def test_apply_skips_stale_generation() -> None:
    app = FleetRefreshHarness()
    projection = FleetRowsProjection(
        fleet_rows=(_remote_row(),), configured_host_count=1
    )
    app._agents_fleet_refresh_generation = 2
    app._apply_fleet_projection(
        projection, config=fleet_config(), generation=1, source="apply"
    )
    assert app._agents_fleet_rows == []
    assert app.reproject_sources == []


def test_apply_skips_changed_tab() -> None:
    app = FleetRefreshHarness()
    projection = FleetRowsProjection(
        fleet_rows=(_remote_row(),), configured_host_count=1
    )
    app.current_tab = "other"
    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
        expected_tab="agents",
        expected_selected_identity=None,
        _selection_checked=True,
    )
    assert app._agents_fleet_rows == []
    assert app.reproject_sources == []


def test_apply_skips_moved_selection() -> None:
    app = FleetRefreshHarness()
    first = Agent(
        AgentType.RUNNING, "alpha", "/tmp/a.yml", "RUNNING", None, agent_name="alpha"
    )
    second = Agent(
        AgentType.RUNNING, "beta", "/tmp/b.yml", "RUNNING", None, agent_name="beta"
    )
    app._agents = [first]
    app._agents_with_children = [first]
    app.current_idx = 0
    projection = FleetRowsProjection(
        fleet_rows=(_remote_row(),), configured_host_count=1
    )
    # Selection moved after the worker snapshot was taken.
    app._agents = [second]
    app._agents_with_children = [second]
    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
        expected_tab="agents",
        expected_selected_identity=first.identity,
        _selection_checked=True,
    )
    assert app._agents_fleet_rows == []
    assert app.reproject_sources == []


def test_apply_accepts_matching_generation_and_selection() -> None:
    app = FleetRefreshHarness()
    local = Agent(
        AgentType.RUNNING,
        "local-work",
        "/tmp/local-project.yml",
        "RUNNING",
        None,
        agent_name="local-work",
    )
    app._agents = [local]
    app._agents_with_children = [local]
    app._agents_local_with_children = [local]
    app.current_idx = 0
    projection = FleetRowsProjection(
        fleet_rows=(_remote_row(),), configured_host_count=1
    )
    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
        expected_tab="agents",
        expected_selected_identity=local.identity,
        _selection_checked=True,
    )
    assert [row.cl_name for row in app._agents_fleet_rows] == ["sase-main"]
    assert app.reproject_sources == ["fleet_refresh"]


@pytest.mark.asyncio
async def test_run_projects_fleet_agents_off_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    response = fleet_host_response(summaries=(summary,))
    facade = OfflineFleetFacade(summary_response=response, catalog_response=response)
    app = FleetRefreshHarness()
    app._agents_local_with_children = []

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: fleet_config())
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    seen_threads: list[int] = []
    from sase.ace.tui.actions.agents import _fleet_refresh as refresh_mod

    real_project = refresh_mod.project_fleet_agents

    def recording_project(**kwargs):  # type: ignore[no-untyped-def]
        import threading

        seen_threads.append(threading.get_ident())
        return real_project(**kwargs)

    monkeypatch.setattr(refresh_mod, "project_fleet_agents", recording_project)

    import threading

    main_ident = threading.get_ident()
    await app._run_agents_fleet_refresh(generation=1, source="manual")

    assert seen_threads, "expected project_fleet_agents to run"
    assert all(tid != main_ident for tid in seen_threads)
    assert [row.fleet_logical_key for row in app._agents_fleet_rows] == [
        summary["logical_key"]
    ]

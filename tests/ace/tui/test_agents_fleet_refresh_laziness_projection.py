"""Fleet projection laziness: apply-path and tree-reproject skipping."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents import _fleet_projection as fleet_projection_mod
from sase.ace.tui.actions.agents._roster_generation import (
    notify_roster_status_mutation,
)
from sase.ace.tui.models import _agent_tree as agent_tree_mod
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fleet_agents import FleetRowsProjection
from tests.ace.tui._agents_fleet_refresh_laziness_shared import FleetRefreshHarness
from tests.ace.tui.fleet_fixture import fleet_config

__all__ = [
    "test_agents_fleet_problem_text_reports_only_actionable_problems",
    "test_apply_fleet_projection_forced_remote_sources_repaint",
    "test_apply_fleet_projection_repaints_changed_row",
    "test_apply_fleet_projection_skips_unchanged_reproject",
    "test_host_freshness_only_change_patches_rows_without_reprojecting",
    "test_local_roster_change_reprojects_tree",
    "test_revision_bump_reprojects_tree",
    "test_snapshot_identity_change_reprojects_tree",
    "test_unchanged_refresh_skips_tree_projection",
]


def _remote_row(
    name: str = "sase-main",
    *,
    status: str = "RUNNING",
    revision: int = 1,
    freshness: str | None = None,
    observed_at_unix: float | None = None,
    host_cache_age_seconds: float | None = None,
    host_running_count: int | None = None,
    host_total_count: int | None = None,
) -> Agent:
    return Agent(
        AgentType.RUNNING,
        name,
        "/fleet/apollo/project.yml",
        status,
        None,
        agent_name=name,
        raw_suffix=f"apollo:{name}",
        fleet_origin_alias="apollo",
        fleet_origin_installation_id="install-apollo",
        fleet_logical_key=f"apollo:{name}",
        fleet_exact_key=f"apollo:{name}:exact",
        fleet_revision=revision,
        fleet_freshness=freshness,
        fleet_observed_at_unix=observed_at_unix,
        fleet_host_cache_age_seconds=host_cache_age_seconds,
        fleet_host_running_count=host_running_count,
        fleet_host_total_count=host_total_count,
    )


def _count_tree_projections(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[int, int]]:
    """Count project_mixed_agent_tree runs (local-size, remote-size)."""
    calls: list[tuple[int, int]] = []
    real = agent_tree_mod.project_mixed_agent_tree

    def _counting(
        local_agents: list[Agent],
        remote_agents: list[Agent],
    ) -> list[Agent]:
        calls.append((len(local_agents), len(remote_agents)))
        return real(local_agents, remote_agents)

    monkeypatch.setattr(
        agent_tree_mod,
        "project_mixed_agent_tree",
        _counting,
    )
    return calls


def test_agents_fleet_problem_text_reports_only_actionable_problems() -> None:
    app = FleetRefreshHarness()
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

    assert app._agents_fleet_problem_text() == "mac unknown"

    app._agents_fleet_projection = FleetRowsProjection(configured_host_count=2)
    app._agents_fleet_last_error = None
    assert app._agents_fleet_problem_text() == ""


def test_apply_fleet_projection_skips_unchanged_reproject() -> None:
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
    projection = FleetRowsProjection(
        fleet_rows=(_remote_row(),),
        configured_host_count=1,
    )

    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    header_updates_after_first = app.header_updates

    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
    )

    assert app.reproject_sources == ["fleet_refresh"]
    assert [row.cl_name for row in app._agents] == ["local-work", "sase-main"]
    assert app.header_updates == header_updates_after_first + 1


def test_apply_fleet_projection_repaints_changed_row() -> None:
    app = FleetRefreshHarness()
    app._apply_fleet_projection(
        FleetRowsProjection(fleet_rows=(_remote_row(revision=1),)),
        config=fleet_config(),
        generation=1,
        source="apply",
    )

    app._apply_fleet_projection(
        FleetRowsProjection(fleet_rows=(_remote_row(revision=2),)),
        config=fleet_config(),
        generation=1,
        source="apply",
    )

    assert app.reproject_sources == ["fleet_refresh", "fleet_refresh"]
    assert app._agents[0].fleet_revision == 2


def test_apply_fleet_projection_forced_remote_sources_repaint() -> None:
    app = FleetRefreshHarness()
    projection = FleetRowsProjection(fleet_rows=(_remote_row(),))

    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="remote_mutation",
    )
    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="remote_attention",
    )

    assert app.reproject_sources == [
        "fleet_refresh",
        "fleet_refresh",
        "fleet_refresh",
    ]


def test_unchanged_refresh_skips_tree_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not hasattr(fleet_projection_mod, "_agents_projection_signature")
    assert not hasattr(fleet_projection_mod, "_freeze_projection_value")
    tree_calls = _count_tree_projections(monkeypatch)
    app = FleetRefreshHarness()
    projection = FleetRowsProjection(
        fleet_rows=(_remote_row(),),
        snapshot_identities=(("snapshot", "snap-1"),),
        configured_host_count=1,
    )

    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    assert len(tree_calls) == 1
    header_updates_after_first = app.header_updates

    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
    )

    assert len(tree_calls) == 1
    assert app.reproject_sources == ["fleet_refresh"]
    assert app.header_updates == header_updates_after_first + 1


def test_revision_bump_reprojects_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree_calls = _count_tree_projections(monkeypatch)
    app = FleetRefreshHarness()
    snapshot = (("snapshot", "snap-1"),)

    app._apply_fleet_projection(
        FleetRowsProjection(
            fleet_rows=(_remote_row(revision=1),),
            snapshot_identities=snapshot,
            configured_host_count=1,
        ),
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    app._apply_fleet_projection(
        FleetRowsProjection(
            fleet_rows=(_remote_row(revision=2),),
            snapshot_identities=snapshot,
            configured_host_count=1,
        ),
        config=fleet_config(),
        generation=1,
        source="apply",
    )

    assert len(tree_calls) == 2
    assert app.reproject_sources == ["fleet_refresh", "fleet_refresh"]
    assert app._agents[0].fleet_revision == 2


def test_host_freshness_only_change_patches_rows_without_reprojecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree_calls = _count_tree_projections(monkeypatch)
    app = FleetRefreshHarness()
    snapshot = (("snapshot", "snap-1"),)

    app._apply_fleet_projection(
        FleetRowsProjection(
            fleet_rows=(
                _remote_row(
                    freshness="fresh",
                    observed_at_unix=100.0,
                    host_cache_age_seconds=2.0,
                    host_running_count=3,
                    host_total_count=5,
                ),
            ),
            snapshot_identities=snapshot,
            configured_host_count=1,
        ),
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    assert len(tree_calls) == 1
    header_updates_after_first = app.header_updates

    refreshed = FleetRowsProjection(
        fleet_rows=(
            _remote_row(
                freshness="stale",
                observed_at_unix=200.0,
                host_cache_age_seconds=95.0,
                host_running_count=4,
                host_total_count=5,
            ),
        ),
        snapshot_identities=snapshot,
        configured_host_count=1,
    )
    app._apply_fleet_projection(
        refreshed,
        config=fleet_config(),
        generation=1,
        source="apply",
    )

    assert len(tree_calls) == 1
    assert app.reproject_sources == ["fleet_refresh"]
    assert app._agents_fleet_projection is refreshed
    assert app.header_updates == header_updates_after_first + 1
    live = app._agents[0]
    assert live.fleet_freshness == "stale"
    assert live.fleet_observed_at_unix == 200.0
    assert live.fleet_host_cache_age_seconds == 95.0
    assert live.fleet_host_running_count == 4


def test_snapshot_identity_change_reprojects_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree_calls = _count_tree_projections(monkeypatch)
    app = FleetRefreshHarness()

    app._apply_fleet_projection(
        FleetRowsProjection(
            fleet_rows=(_remote_row(),),
            snapshot_identities=(("snapshot", "snap-a"),),
            configured_host_count=1,
        ),
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    app._apply_fleet_projection(
        FleetRowsProjection(
            fleet_rows=(_remote_row(),),
            snapshot_identities=(("snapshot", "snap-b"),),
            configured_host_count=1,
        ),
        config=fleet_config(),
        generation=1,
        source="apply",
    )

    assert len(tree_calls) == 2
    assert app.reproject_sources == ["fleet_refresh", "fleet_refresh"]


def test_local_roster_change_reprojects_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree_calls = _count_tree_projections(monkeypatch)
    app = FleetRefreshHarness()
    projection = FleetRowsProjection(
        fleet_rows=(_remote_row(),),
        snapshot_identities=(("snapshot", "snap-1"),),
        configured_host_count=1,
    )

    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    assert len(tree_calls) == 1

    notify_roster_status_mutation(app)
    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    assert len(tree_calls) == 2

    app._agents_removal_generation += 1
    app._apply_fleet_projection(
        projection,
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    assert len(tree_calls) == 3
    assert app.reproject_sources == [
        "fleet_refresh",
        "fleet_refresh",
        "fleet_refresh",
    ]

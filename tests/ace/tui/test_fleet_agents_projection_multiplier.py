"""Fleet multiplier projection tests for phase sase-19f.6.1."""

from __future__ import annotations

from sase.ace.tui.models.fleet_agents import project_fleet_agents
from tests.ace.tui._fleet_summary_fixture import fleet_summary
from tests.ace.tui.fleet_fixture import fleet_host_response


def _project_row(summary: dict) -> object:
    response = fleet_host_response(alias="apollo", summaries=(summary,))
    projection = project_fleet_agents(catalog_response=response)
    return projection.fleet_rows[0]


def test_fleet_row_carries_multiplier() -> None:
    summary = fleet_summary(agent_id="mult", agent_name="apollo.mult")
    summary["queue_capacity_multiplier"] = 1.5
    row = _project_row(summary)
    assert row.queue_capacity is None
    assert row.queue_capacity_multiplier == 1.5
    assert row.wait_runners is None


def test_fleet_row_integer_wins_over_multiplier() -> None:
    summary = fleet_summary(
        agent_id="both",
        agent_name="apollo.both",
        queue_capacity=4,
        queue_capacity_explicit=True,
    )
    summary["queue_capacity_multiplier"] = 1.5
    row = _project_row(summary)
    assert row.queue_capacity == 4
    assert row.queue_capacity_multiplier is None


def test_fleet_row_invalid_multiplier_ignored() -> None:
    summary = fleet_summary(agent_id="bad", agent_name="apollo.bad")
    summary["queue_capacity_multiplier"] = 0.0
    row = _project_row(summary)
    assert row.queue_capacity is None
    assert row.queue_capacity_multiplier is None


def test_fleet_row_absent_multiplier_stays_quiet() -> None:
    summary = fleet_summary(agent_id="plain", agent_name="apollo.plain")
    row = _project_row(summary)
    assert row.queue_capacity is None
    assert row.queue_capacity_multiplier is None

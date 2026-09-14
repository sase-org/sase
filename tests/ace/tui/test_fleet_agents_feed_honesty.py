"""An invalid or stale-cached host feed must never render as silently healthy."""

from __future__ import annotations

from sase.ace.tui.actions.agents._fleet_common import host_feed_issue_text
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from tests.ace.tui.fleet_fixture import (
    fleet_host_response,
    fleet_installation_id,
    fleet_invalid_host_response,
    fleet_summary,
)


def test_invalid_host_snapshot_yields_no_rows_and_a_host_feed_issue() -> None:
    """A host normalized to ``invalid_federation_host`` must stay visible.

    It produces zero summaries by construction, so the only way its error
    reaches the viewer is the host-level feed-issue channel.
    """
    response = fleet_invalid_host_response(
        alias="apollo",
        error="invalid_envelope",
        cached=True,
        age_seconds=18_000.0,
    )

    projection = project_fleet_agents(summary_response=response)

    assert projection.fleet_rows == ()
    assert projection.focus_rows == ()
    assert len(projection.host_feed_issues) == 1
    issue = projection.host_feed_issues[0]
    assert issue.alias == "apollo"
    assert issue.status == "invalid"
    assert issue.error == "invalid_envelope"
    assert issue.cache_age_seconds == 18_000.0
    assert issue.diagnostic == "invalid_envelope"


def test_healthy_snapshot_reports_no_host_feed_issues() -> None:
    installation_id = fleet_installation_id()
    summary = fleet_summary(
        installation_id=installation_id,
        agent_id="agent-a",
        run_id="run-a",
        status="running",
    )
    response = fleet_host_response(
        alias="apollo",
        installation_id=installation_id,
        summaries=(summary,),
        freshness="fresh",
        connection_health="online",
    )

    projection = project_fleet_agents(summary_response=response)

    assert len(projection.fleet_rows) == 1
    assert projection.host_feed_issues == ()
    agent = projection.fleet_rows[0]
    assert agent.fleet_freshness in (None, "fresh")
    assert agent.fleet_host_status != "invalid"
    assert agent.fleet_host_feed_error is None


def test_cached_stale_snapshot_carries_staleness_on_every_row() -> None:
    """A cached snapshot beyond the staleness threshold never renders bare.

    Even though the host and summary both self-report as healthy ("ok"
    status, no explicit ``freshness``/``connection_health`` override), the
    viewer's own cache-age classification must still mark every row from
    it stale rather than plain ``RUNNING``.
    """
    installation_id = fleet_installation_id()
    summary = fleet_summary(
        installation_id=installation_id,
        agent_id="agent-a",
        run_id="run-a",
        status="running",
    )
    response = fleet_host_response(
        alias="apollo",
        installation_id=installation_id,
        summaries=(summary,),
        freshness="fresh",
        connection_health="online",
    )
    response["hosts"][0]["cached"] = True
    response["hosts"][0]["age_seconds"] = 18_000.0

    projection = project_fleet_agents(summary_response=response)

    assert len(projection.fleet_rows) == 1
    agent = projection.fleet_rows[0]
    assert agent.status == "RUNNING"
    assert agent.fleet_freshness == "stale"
    assert agent.fleet_host_cache_age_seconds == 18_000.0


def test_host_feed_issue_text_reports_invalid_host_with_cache_age() -> None:
    response = fleet_invalid_host_response(
        alias="apollo",
        error="invalid_envelope",
        cached=True,
        age_seconds=18_000.0,
    )

    projection = project_fleet_agents(summary_response=response)

    assert host_feed_issue_text(projection) == "apollo: feed invalid (cached 5h ago)"


def test_host_feed_issue_text_empty_for_healthy_projection() -> None:
    installation_id = fleet_installation_id()
    summary = fleet_summary(
        installation_id=installation_id,
        agent_id="agent-a",
        run_id="run-a",
        status="running",
    )
    response = fleet_host_response(
        alias="apollo",
        installation_id=installation_id,
        summaries=(summary,),
        freshness="fresh",
        connection_health="online",
    )

    projection = project_fleet_agents(summary_response=response)

    assert host_feed_issue_text(projection) == ""

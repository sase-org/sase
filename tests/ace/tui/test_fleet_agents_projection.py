from __future__ import annotations

from sase.ace.tui.models.fleet_agents import project_fleet_agents
from tests.ace.tui.fleet_fixture import (
    fleet_attention_response,
    fleet_counts,
    fleet_follow_snapshot,
    fleet_host_response,
    fleet_installation_id,
    fleet_logical_locator,
    fleet_summary,
)


def test_project_fleet_agents_marks_followed_and_preserves_machine_sections() -> None:
    installation_id = fleet_installation_id("a")
    logical_a = fleet_logical_locator(
        installation_id=installation_id,
        project_id="sase",
        agent_id="agent-a",
    )
    first = fleet_summary(
        installation_id=installation_id,
        project_id="sase",
        project_name="SASE",
        agent_id="agent-a",
        run_id="run-a",
        agent_name="same.name",
        bounded_intent="hydrate",
        revision=4,
    )
    second = fleet_summary(
        installation_id=installation_id,
        project_id="sase",
        project_name="SASE",
        agent_id="agent-b",
        run_id="run-b",
        agent_name="same.name",
        status="done",
    )
    follow_snapshot = fleet_follow_snapshot(logical_a, path="/tmp/follows.json")
    response = fleet_host_response(
        alias="apollo",
        installation_id=installation_id,
        summaries=(first, second),
    )

    projection = project_fleet_agents(
        catalog_response=response,
        followed_response=response,
        follow_snapshot=follow_snapshot,
        local_agent_count=3,
    )

    assert len(projection.fleet_rows) == 2
    assert len(projection.focus_rows) == 1
    assert projection.counts["local"] == 3
    assert projection.counts["focus_total"] == 4
    assert projection.counts["fleet"] == 1
    followed = projection.focus_rows[0]
    assert followed.fleet_origin_alias == "apollo"
    assert followed.project_display_name == "SASE"
    assert followed.project_file == "/fleet/sase/project.yml"
    assert followed.fleet_followed is True
    assert followed.fleet_revision == 4
    assert followed.fleet_bounded_intent == "hydrate"
    assert {row.identity for row in projection.fleet_rows} == {
        row.identity for row in projection.fleet_rows
    }
    assert projection.fleet_rows[0].identity != projection.fleet_rows[1].identity


def test_project_fleet_agents_maps_pending_attention_onto_local_statuses() -> None:
    first = fleet_summary(agent_id="agent-a")
    second = fleet_summary(agent_id="agent-b", status="asking")
    response = fleet_host_response(alias="apollo", summaries=(first, second))
    attention_response = fleet_attention_response(
        (
            {
                "kind": "question",
                "state": "pending",
                "logical_key": first["logical_key"],
            },
            {
                "kind": "gate",
                "state": "settled",
                "logical_key": second["logical_key"],
            },
        ),
        alias="apollo",
    )

    projection = project_fleet_agents(
        catalog_response=response,
        attention_response=attention_response,
    )

    by_key = {row.fleet_logical_key: row for row in projection.fleet_rows}
    assert by_key[first["logical_key"]].status == "QUESTION"
    assert by_key[first["logical_key"]].fleet_attention == {
        "kind": "question",
        "state": "pending",
        "logical_key": first["logical_key"],
    }
    # A settled attention entry never overrides status; the row's own
    # lifecycle ("asking") is the fallback signal instead.
    assert by_key[second["logical_key"]].status == "WAITING INPUT"
    assert by_key[second["logical_key"]].fleet_attention is not None


def test_offline_fleet_fixture_projects_rows_counts_and_diagnostics() -> None:
    installation_id = fleet_installation_id("c")
    logical = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="fixture-agent",
    )
    summary = fleet_summary(
        installation_id=installation_id,
        agent_id="fixture-agent",
        needs_attention=True,
        bounded_intent="reuse from visual and perf tests",
    )
    response = fleet_host_response(
        alias="apollo",
        installation_id=installation_id,
        summaries=(summary,),
        diagnostics=(
            {
                "code": "fixture_warning",
                "severity": "warning",
                "message": "offline fixture diagnostic",
            },
        ),
        partial=True,
    )
    attention = fleet_attention_response(
        (
            {
                "kind": "question",
                "state": "pending",
                "logical_key": summary["logical_key"],
            },
        ),
        alias="apollo",
    )

    projection = project_fleet_agents(
        summary_response=response,
        catalog_response=response,
        followed_response=response,
        attention_response=attention,
        follow_snapshot=fleet_follow_snapshot(logical),
        local_agent_count=2,
    )

    assert len(projection.fleet_rows) == 1
    assert len(projection.focus_rows) == 1
    assert projection.configured_host_count == 1
    assert projection.partial is True
    assert projection.counts["local"] == 2
    assert projection.counts["focus_total"] == 3
    assert projection.counts["fleet"] == 1
    assert [diagnostic["code"] for diagnostic in projection.diagnostics] == [
        "fixture_warning",
        "fleet_host_partial",
        "fixture_warning",
        "fleet_host_partial",
        "fixture_warning",
        "fleet_host_partial",
    ]
    row = projection.focus_rows[0]
    assert row.fleet_origin_alias == "apollo"
    assert row.fleet_followed is True
    assert row.status == "QUESTION"
    assert row.fleet_bounded_intent == "reuse from visual and perf tests"


def test_project_fleet_agents_sources_host_running_and_total_counts() -> None:
    """Every row from a host carries that host's own authoritative counts."""
    running = fleet_summary(agent_id="running-agent", status="running")
    done = fleet_summary(agent_id="done-agent", status="done")
    counts = fleet_counts((running, done), running=1)
    response = fleet_host_response(
        alias="apollo",
        summaries=(running, done),
        counts=counts,
    )

    projection = project_fleet_agents(catalog_response=response)

    assert len(projection.fleet_rows) == 2
    for row in projection.fleet_rows:
        assert row.fleet_host_running_count == 1
        assert row.fleet_host_total_count == 2

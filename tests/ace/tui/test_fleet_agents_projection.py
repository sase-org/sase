from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_live_query import agent_live_query_entry
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
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


def test_project_fleet_agents_carries_remote_queue_weight_without_local_charge() -> (
    None
):
    summary = fleet_summary(
        agent_id="weighted",
        agent_name="apollo.weighted",
        queue_weight=0.25,
        queue_weight_explicit=True,
    )
    response = {
        "schema_version": 1,
        "operation": "catalog",
        "configured_host_count": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "summaries": [summary],
            }
        ],
        "count_hosts": [],
    }

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_weight == 0.25
    assert row.queue_weight_explicit is True
    assert row.queue_weight_invalid is False
    left, _, _ = format_agent_option(row, 0, is_selected=False)
    header, _ = build_header_text(row, cheap=True)
    assert "w0.25 (RUNNING)" in left.plain
    assert "apollo.weighted" in left.plain
    assert "Weight: 0.25 capacity units" in header.plain

    local = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="local",
        project_file="/tmp/project/project.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix="20260712120000",
        artifacts_dir="/tmp/project/artifacts/ace-run/20260712120000",
        pid=1234,
        run_start_time=datetime(2026, 7, 12, 12, 0, 0),
    )
    capacity = refresh_runner_slot_context([local, row], effective_limit=1)
    assert capacity.slots_in_use == 1
    assert capacity.occupied_capacity == 1.0


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


def test_project_fleet_agents_never_renders_running_for_a_dead_liveness_row() -> None:
    """A definitively-dead owner liveness never presents as RUNNING.

    Simulates a demoted dead-active-tier record: the raw display status
    still says "running" (sase-core's ``status_for_record`` does not
    consult liveness), but the owner-resolved ``liveness``/``status_bucket``
    already say the process is gone. The viewer must not fabricate an
    active state from the stale status text.
    """
    summary = fleet_summary(status="running")
    summary["liveness"] = "dead"
    summary["status_bucket"] = "stopped"
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    assert len(projection.fleet_rows) == 1
    row = projection.fleet_rows[0]
    assert row.status == "WAS RUNNING"
    assert row.status_bucket == "Stopped"


def test_project_fleet_agents_keeps_running_for_alive_liveness() -> None:
    """A genuinely alive/running row keeps its ordinary RUNNING status."""
    summary = fleet_summary(status="running")
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    row = projection.fleet_rows[0]
    assert row.status == "RUNNING"
    assert row.status_bucket == "Running"


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


def test_project_fleet_agents_carries_remote_family_lineage_into_agent_rows() -> None:
    """Remote family metadata feeds the common Agent model and agents-live."""
    root = fleet_summary(
        agent_id="family-root",
        run_id="20260910120000",
        agent_name="remote-family",
        family_id="remote-family",
    )
    root["family_role"] = "root"
    child = fleet_summary(
        agent_id="family-code",
        run_id="20260910120100",
        agent_name="remote-family--code",
        family_id="remote-family",
    )
    child["family_role"] = "member"
    child["parent_timestamp"] = "20260910120000"
    response = fleet_host_response(alias="apollo", summaries=(root, child))

    projection = project_fleet_agents(catalog_response=response)

    by_name = {row.agent_name: row for row in projection.fleet_rows}
    root_row = by_name["remote-family"]
    child_row = by_name["remote-family--code"]
    assert root_row.agent_family is None
    assert root_row.agent_family_role == "root"
    assert child_row.agent_family == "remote-family"
    assert child_row.agent_family_role == "member"
    assert child_row.role_suffix == "--code"
    assert child_row.parent_timestamp == root_row.raw_suffix
    assert child_row.is_family_member_child is True
    entry = agent_live_query_entry(child_row)
    assert entry["fields"]["kind"] == ("member",)
    assert entry["fields"]["role"] == ("member", "code")
    assert entry["fields"]["family"] == ("remote-family",)


def test_project_fleet_agents_downgrades_fresh_chip_for_a_cached_aged_host() -> None:
    """A cached, aged client response must not render the fresh chip.

    The owner honestly stamped this row "fresh" at build time, but the
    viewer's own federation-worker cache is serving a copy fetched 120s
    ago, well past the fresh/stale thresholds - the rendered freshness must
    reflect the worse (viewer) signal, not the owner's stamp alone.
    """
    summary = fleet_summary(status="running", freshness="fresh")
    response = fleet_host_response(
        alias="apollo", summaries=(summary,), freshness="fresh"
    )
    response["hosts"][0]["cached"] = True
    response["hosts"][0]["age_seconds"] = 120.0

    projection = project_fleet_agents(catalog_response=response)

    assert projection.fleet_rows[0].fleet_freshness == "stale"


def test_project_fleet_agents_keeps_fresh_chip_for_a_live_fetch() -> None:
    """A live (non-cached) fetch keeps the owner's honest freshness stamp."""
    summary = fleet_summary(status="running", freshness="fresh")
    response = fleet_host_response(
        alias="apollo", summaries=(summary,), freshness="fresh"
    )

    projection = project_fleet_agents(catalog_response=response)

    assert projection.fleet_rows[0].fleet_freshness == "fresh"

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets._queue_weight_badge import append_agent_queue_badges
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests._fleet_contract_sase_core_rs_helpers import (
    _binding,
    _known_installation_id,
    _projection_request,
)
from tests.ace.tui.fleet_fixture import fleet_host_response, fleet_summary


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


def test_project_fleet_agents_carries_remote_explicit_zero_queue_weight() -> None:
    """An explicit-zero remote weight (e.g. a remote epic-launch monitor) is

    valid and non-occupying -- unlike an implicit zero, which stays
    invalid/fail-closed like any other non-positive weight -- and never
    renders a misleading ``w0`` badge or "Weight: 0" header text.
    """
    summary = fleet_summary(
        agent_id="epic-launch-monitor",
        agent_name="apollo.epic-launch-monitor",
        queue_weight=0.0,
        queue_weight_explicit=True,
    )
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_weight == 0.0
    assert row.queue_weight_explicit is True
    assert row.queue_weight_invalid is False
    text = Text()
    assert append_agent_queue_badges(text, row) is False
    assert text.plain == ""
    header, _ = build_header_text(row, cheap=True)
    assert "Weight:" not in header.plain

    local = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="local",
        project_file="/tmp/project/project.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix="20260712120002",
        artifacts_dir="/tmp/project/artifacts/ace-run/20260712120002",
        pid=1236,
        run_start_time=datetime(2026, 7, 12, 12, 0, 0),
    )
    capacity = refresh_runner_slot_context([local, row], effective_limit=1)
    assert capacity.slots_in_use == 1
    assert capacity.occupied_capacity == 1.0


def test_project_fleet_agents_carries_remote_queue_capacity_without_local_charge() -> (
    None
):
    summary = fleet_summary(
        agent_id="capacitated",
        agent_name="apollo.capacitated",
        queue_capacity=100,
        queue_capacity_explicit=True,
    )
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_capacity == 100
    assert row.queue_capacity_explicit is True
    assert row.wait_runners == 100
    assert row.wait_runners_explicit is True
    left, _, _ = format_agent_option(row, 0, is_selected=False)
    header, _ = build_header_text(row, cheap=True)
    assert "c100 (RUNNING)" in left.plain
    assert "apollo.capacitated" in left.plain
    assert "Capacity: 100 capacity units" in header.plain

    local = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="local",
        project_file="/tmp/project/project.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix="20260712120001",
        artifacts_dir="/tmp/project/artifacts/ace-run/20260712120001",
        pid=1235,
        run_start_time=datetime(2026, 7, 12, 12, 0, 0),
    )
    capacity = refresh_runner_slot_context([local, row], effective_limit=1)
    assert capacity.slots_in_use == 1
    assert capacity.occupied_capacity == 1.0


def test_project_fleet_agents_carries_remote_explicit_zero_queue_capacity() -> None:
    summary = fleet_summary(
        agent_id="drained",
        agent_name="apollo.drained",
        queue_capacity=0,
        queue_capacity_explicit=True,
    )
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_capacity == 0
    assert row.queue_capacity_explicit is True
    left, _, _ = format_agent_option(row, 0, is_selected=False)
    header, _ = build_header_text(row, cheap=True)
    assert "c0 (RUNNING)" in left.plain
    assert "legacy 0" in header.plain


def test_project_fleet_agents_keeps_absent_queue_capacity_quiet() -> None:
    summary = fleet_summary(agent_id="unbudgeted", agent_name="apollo.unbudgeted")
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_capacity is None
    assert row.queue_capacity_explicit is False
    text = Text()
    assert append_agent_queue_badges(text, row) is False
    assert text.plain == ""
    header, _ = build_header_text(row, cheap=True)
    assert "Capacity:" not in header.plain


def test_project_fleet_agents_normalizes_legacy_owner_wait_runners_into_capacity() -> (
    None
):
    """An owner-side summary built from legacy ``wait_runners`` metadata already
    carries canonical ``queue_capacity`` by the time it reaches the fleet-row
    adapter; this proves the real projection boundary, not a hand-built fixture.
    """
    installation_id = _known_installation_id("a")
    request = _projection_request(installation_id, agent_id="legacy-capacity")
    request["record"]["agent_meta"]["wait_runners"] = 0
    request["record"]["agent_meta"]["wait_runners_explicit"] = True
    owner_summary = _binding("fleet_project_resolved_agent_summary")(request)
    assert owner_summary["queue_capacity"] == 0
    assert owner_summary["queue_capacity_explicit"] is True
    assert "wait_runners" not in owner_summary

    response = fleet_host_response(alias="apollo", summaries=(owner_summary,))
    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_capacity == 0
    assert row.queue_capacity_explicit is True
    assert row.wait_runners == 0
    assert row.wait_runners_explicit is True
    header, _ = build_header_text(row, cheap=True)
    assert "legacy 0" in header.plain

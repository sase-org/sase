"""Held staged-monitor projection: NOT ADOPTED, Failed, nonterminal, settled."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.cells import cell_len

from sase.ace.tui.models._loaders._meta_enrichment_filesystem import (
    enrich_agent_from_meta,
)
from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_session_members import (
    agent_row_is_in_flight,
    monitor_row_is_settled,
    turn_lane_counts,
)
from sase.ace.tui.models.agent_time import runtime_suffix_ticks
from sase.agent.status_buckets import agent_status_bucket, status_bucket_for_values
from sase.core.agent_scan_wire import (
    AgentMetaWire,
    AgentSessionTurnMonitorWire,
    AgentSessionTurnWire,
)
from sase.monitor_state import (
    MONITOR_HELD_STATE,
    NOT_ADOPTED_GLYPH,
    NOT_ADOPTED_STATUS,
    monitor_state_bucket,
    monitor_state_is_terminal,
)
from tests.ace.tui.models._agent_session_members_helpers import _agent, _monitor_member


def _held_member_meta() -> dict[str, object]:
    return {
        "name": "alpha--mon-0",
        "monitor_id": "m-held",
        "monitor_state": "staged",
        "monitor_stage_held": True,
        "monitor_command": "just check",
        "monitor_label": "just check",
        "monitor_start_status": "MONITORING",
        "agent_session": "alpha",
        "agent_session_role": "monitor",
        "role_suffix": "--mon-0",
        "run_started_at": "2026-11-21T23:59:00Z",
    }


def _blank_agent(*, status: str = "STARTING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="held-row",
        project_file="/tmp/monitor.sase",
        status=status,
        start_time=datetime(2026, 11, 21, 23, 59, 0),
        raw_suffix="20261121235900",
    )


def test_held_glyph_is_single_width() -> None:
    assert cell_len(NOT_ADOPTED_GLYPH) == 1


def test_held_buckets_as_failed_and_stays_nonterminal() -> None:
    assert monitor_state_bucket(MONITOR_HELD_STATE) == "Failed"
    assert monitor_state_is_terminal(MONITOR_HELD_STATE) is False
    assert monitor_state_is_terminal("staged") is False
    assert monitor_state_is_terminal("failed") is True
    assert status_bucket_for_values(NOT_ADOPTED_STATUS) == "Failed"


def test_filesystem_incident_meta_projects_not_adopted(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(json.dumps(_held_member_meta()))
    agent = _blank_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.monitor_state == MONITOR_HELD_STATE
    assert agent.status == NOT_ADOPTED_STATUS
    assert agent.status_bucket == "Failed"
    assert agent_status_bucket(agent) == "Failed"
    assert monitor_state_is_terminal(agent.monitor_state) is False
    assert agent_row_is_in_flight(agent) is False
    assert runtime_suffix_ticks(agent) is False
    assert monitor_row_is_settled(agent) is True


def test_filesystem_staged_without_flag_stays_running(tmp_path: Path) -> None:
    meta = _held_member_meta()
    del meta["monitor_stage_held"]
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    agent = _blank_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.monitor_state == "staged"
    assert agent.status != NOT_ADOPTED_STATUS
    assert agent.status_bucket == "Running"
    assert agent_row_is_in_flight(agent) is False
    assert monitor_row_is_settled(agent) is False


def test_wire_held_state_projects_not_adopted() -> None:
    agent = _blank_agent()
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            name="alpha--mon-0",
            agent_session_turn=AgentSessionTurnWire(
                kind="monitor",
                id="m-held",
                state=MONITOR_HELD_STATE,
                label="just check",
                start_status="MONITORING",
                monitor=AgentSessionTurnMonitorWire(command="just check"),
            ),
            run_started_at="2026-11-21T23:59:00Z",
            agent_session="alpha",
            agent_session_role="monitor",
            role_suffix="--mon-0",
        ),
        waiting=None,
    )

    assert agent.monitor_state == MONITOR_HELD_STATE
    assert agent.status == NOT_ADOPTED_STATUS
    assert agent.status_bucket == "Failed"
    assert agent_status_bucket(agent) == "Failed"
    assert monitor_state_is_terminal(agent.monitor_state) is False
    assert agent_row_is_in_flight(agent) is False
    assert runtime_suffix_ticks(agent) is False
    assert monitor_row_is_settled(agent) is True


def test_wire_staged_without_held_stays_running() -> None:
    agent = _blank_agent()
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            name="alpha--mon-0",
            agent_session_turn=AgentSessionTurnWire(
                kind="monitor",
                id="m-staged",
                state="staged",
                label="just check",
                start_status="MONITORING",
                monitor=AgentSessionTurnMonitorWire(command="just check"),
            ),
            run_started_at="2026-11-21T23:59:00Z",
            agent_session="alpha",
            agent_session_role="monitor",
            role_suffix="--mon-0",
        ),
        waiting=None,
    )

    assert agent.monitor_state == "staged"
    assert agent.status != NOT_ADOPTED_STATUS
    assert agent.status_bucket == "Running"
    assert monitor_row_is_settled(agent) is False


def test_readopted_running_row_is_in_flight_again() -> None:
    agent = _blank_agent(status=NOT_ADOPTED_STATUS)
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            name="alpha--mon-0",
            agent_session_turn=AgentSessionTurnWire(
                kind="monitor",
                id="m-held",
                state="running",
                label="just check",
                start_status="MONITORING",
                monitor=AgentSessionTurnMonitorWire(command="just check"),
            ),
            run_started_at="2026-11-21T23:59:00Z",
            agent_session="alpha",
            agent_session_role="monitor",
            role_suffix="--mon-0",
        ),
        waiting=None,
    )

    assert agent.monitor_state == "running"
    assert agent.status == "MONITORING"
    assert agent.status_bucket == "Running"
    assert agent_row_is_in_flight(agent) is True
    assert monitor_row_is_settled(agent) is False
    assert runtime_suffix_ticks(agent) is True


def test_held_monitor_counts_in_the_grey_lane() -> None:
    root = _agent("alpha--0", role="root")
    held = _monitor_member(
        "alpha--mon-held",
        root=root,
        monitor_id="m-held",
        monitor_state=MONITOR_HELD_STATE,
    )
    running = _monitor_member(
        "alpha--mon-running",
        root=root,
        monitor_id="m-running",
        monitor_state="running",
    )
    root.followup_agents = [held, running]
    lanes = turn_lane_counts(root).monitor
    assert lanes.settled == 1
    assert lanes.running == 1
    assert lanes.running + lanes.settled == 2
    assert monitor_row_is_settled(held) is True
    assert monitor_row_is_settled(running) is False
    assert agent_row_is_in_flight(held) is False
    assert agent_row_is_in_flight(running) is True

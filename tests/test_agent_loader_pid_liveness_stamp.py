"""Loader PID-liveness stamp: rows kept without probing are marked."""

from __future__ import annotations

from sase.ace.tui.models._agent_loader_normalization import (
    _filter_dead_pids,
    normalize_loaded_agents,
)
from sase.ace.tui.models.agent import Agent, AgentType

DEAD_PID = 99_999_999
LIVE_PID = 12345


def _done_agent() -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="done-row",
        project_file="/tmp/demo.sase",
        status="DONE",
        start_time=None,
        pid=DEAD_PID,
    )


def _gate_turn_agent() -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="alpha--gate",
        project_file="/tmp/demo.sase",
        status="EPIC",
        start_time=None,
        pid=DEAD_PID,
        agent_session_role="gate",
        gate_id="g123",
        gate_state="pending",
        appears_as_agent=True,
    )


def test_done_row_with_dead_pid_is_kept_and_stamped() -> None:
    kept = _filter_dead_pids([_done_agent()], is_process_running=lambda _pid: False)
    assert [agent.cl_name for agent in kept] == ["done-row"]
    assert kept[0].pid_liveness_unverified is True


def test_session_turn_row_with_pid_is_kept_and_stamped() -> None:
    kept = _filter_dead_pids(
        [_gate_turn_agent()], is_process_running=lambda _pid: False
    )
    assert [agent.cl_name for agent in kept] == ["alpha--gate"]
    assert kept[0].pid_liveness_unverified is True


def test_running_row_with_live_pid_is_kept_and_not_stamped() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alive",
        project_file="/tmp/demo.sase",
        status="RUNNING",
        start_time=None,
        pid=LIVE_PID,
    )
    kept = _filter_dead_pids([agent], is_process_running=lambda pid: pid == LIVE_PID)
    assert [row.cl_name for row in kept] == ["alive"]
    assert kept[0].pid_liveness_unverified is False


def test_running_row_with_dead_pid_is_still_dropped() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="dead",
        project_file="/tmp/demo.sase",
        status="RUNNING",
        start_time=None,
        pid=DEAD_PID,
    )
    kept = _filter_dead_pids([agent], is_process_running=lambda _pid: False)
    assert kept == []


def test_normalize_keeps_stamp_on_done_row() -> None:
    kept = normalize_loaded_agents(
        [_done_agent()],
        [],
        is_process_running=lambda _pid: False,
    )
    assert [agent.cl_name for agent in kept] == ["done-row"]
    assert kept[0].pid_liveness_unverified is True

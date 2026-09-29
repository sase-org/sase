"""Session, monitor, and runner scenarios for agent cleanup facade tests."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent
from sase.core.agent_cleanup_wire import (
    CLEANUP_MODE_DISMISS_COMPLETED,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_SCOPE_ALL_PANELS,
    CLEANUP_SCOPE_CLAN,
    CLEANUP_SCOPE_CUSTOM_SELECTION,
    CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
    AgentCleanupRequestWire,
)
from tests.test_core_facade._agent_cleanup_builders import (
    STOP_TIME,
    make_agent,
    make_identity,
    make_request,
)


def scenario_explicit_child_running() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = make_agent(cl_name="parent", raw_suffix="parent-ts", pid=1001)
    child = make_agent(
        cl_name="child",
        raw_suffix="child-ts",
        pid=1002,
        parent_timestamp="parent-ts",
        workspace_num=8,
    )
    sibling = make_agent(
        cl_name="sibling",
        raw_suffix="sibling-ts",
        pid=1003,
        parent_timestamp="parent-ts",
        workspace_num=9,
    )
    return [
        parent,
        child,
        sibling,
    ], make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(child),),
    )


def scenario_explicit_child_done() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = make_agent(cl_name="parent", raw_suffix="parent-ts", pid=1001)
    child = make_agent(
        cl_name="child",
        raw_suffix="child-ts",
        status="DONE",
        pid=None,
        parent_timestamp="parent-ts",
        stop_time=STOP_TIME,
    )
    return [
        parent,
        child,
    ], make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(child),),
    )


def scenario_custom_child_running() -> tuple[list[Agent], AgentCleanupRequestWire]:
    parent = make_agent(cl_name="parent", raw_suffix="parent-ts", pid=1001)
    child = make_agent(
        cl_name="child",
        raw_suffix="child-ts",
        pid=1002,
        parent_timestamp="parent-ts",
    )
    return [
        parent,
        child,
    ], make_request(
        scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(child),),
    )


def scenario_parallel_agent_session_root() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    root = make_agent(
        cl_name="sase-6g",
        raw_suffix="root-ts",
        pid=1001,
        agent_session_parallel=True,
    )
    member = make_agent(
        cl_name="sase-6g.1",
        raw_suffix="member-ts",
        pid=1002,
        parent_timestamp="root-ts",
        agent_session_parallel=True,
    )
    serial_child = make_agent(
        cl_name="sase-6g--code",
        raw_suffix="serial-ts",
        pid=1003,
        parent_timestamp="root-ts",
    )
    return [root, member, serial_child], make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(root),),
    )


def _clan_sequential_agent_session_agents() -> list[Agent]:
    plan_root = make_agent(
        cl_name="sase-ps.plan",
        raw_suffix="20260818102050",
        status="DONE",
        pid=None,
        agent_clan="sase-ps",
        agent_clan_generation="20260818102050",
        agent_session_parallel=False,
        stop_time=STOP_TIME,
    )
    agent_session_root = make_agent(
        cl_name="sase-ps.plan--1",
        raw_suffix="20260818114621",
        status="DONE",
        pid=None,
        parent_timestamp="20260818102050",
        agent_clan="sase-ps",
        agent_clan_generation="20260818102050",
        agent_session_parallel=False,
        stop_time=STOP_TIME,
    )
    monitor = make_agent(
        cl_name="sase-ps.plan--mon",
        raw_suffix="20260818114457",
        status="DONE",
        pid=None,
        parent_timestamp="20260818114621",
        agent_clan="sase-ps",
        agent_clan_generation="20260818102050",
        agent_session_parallel=False,
        stop_time=STOP_TIME,
    )
    return [plan_root, agent_session_root, monitor]


def scenario_clan_sequential_agent_session_dismiss() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    agents = _clan_sequential_agent_session_agents()
    return agents, make_request(
        scope=CLEANUP_SCOPE_CLAN,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        clan_name="sase-ps",
        clan_generation="20260818102050",
        include_pidless_as_dismissable=True,
    )


def scenario_explicit_clan_sequential_agent_session_dismiss() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    agents = _clan_sequential_agent_session_agents()
    return agents, make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=tuple(make_identity(agent) for agent in agents),
        include_pidless_as_dismissable=True,
    )


def _live_monitor(
    *,
    cl_name: str,
    raw_suffix: str,
    parent_timestamp: str,
    monitor_id: str,
    pid: int | None = 1665545,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
) -> Agent:
    return make_agent(
        cl_name=cl_name,
        raw_suffix=raw_suffix,
        parent_timestamp=parent_timestamp,
        status="MONITORING",
        pid=pid,
        workspace_num=15,
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id=monitor_id,
        monitor_state="running",
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
    )


def scenario_direct_live_monitor() -> tuple[list[Agent], AgentCleanupRequestWire]:
    owner = make_agent(
        cl_name="owner",
        raw_suffix="owner-ts",
        status="DONE",
        pid=None,
        stop_time=STOP_TIME,
    )
    monitor = _live_monitor(
        cl_name="owner--mon",
        raw_suffix="mon-ts",
        parent_timestamp="owner-ts",
        monitor_id="monid123456",
    )
    return [owner, monitor], make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(monitor),),
    )


def scenario_owner_cascades_live_monitor() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    owner = make_agent(
        cl_name="sase-ru.6",
        raw_suffix="owner-ts",
        status="DONE",
        pid=None,
        stop_time=STOP_TIME,
    )
    agent_session = make_agent(
        cl_name="sase-ru.6--1",
        raw_suffix="agent-session-ts",
        parent_timestamp="owner-ts",
        status="DONE",
        pid=None,
        stop_time=STOP_TIME,
    )
    monitor = _live_monitor(
        cl_name="sase-ru.6--mon-1",
        raw_suffix="mon-ts",
        parent_timestamp="agent-session-ts",
        monitor_id="0fmbm91hgytw",
    )
    sibling = _live_monitor(
        cl_name="sase-ru.7--mon",
        raw_suffix="sib-mon-ts",
        parent_timestamp="sib-ts",
        monitor_id="unrelatedmon1",
    )
    return [owner, agent_session, monitor, sibling], make_request(
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(make_identity(owner),),
    )


def scenario_failed_live_runner_kill() -> tuple[list[Agent], AgentCleanupRequestWire]:
    retry = make_agent(
        cl_name="retry",
        raw_suffix="retry-ts",
        status="FAILED",
        pid=77,
        runner_is_live=True,
    )
    return [retry], make_request(
        scope=CLEANUP_SCOPE_ALL_PANELS,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
    )


def scenario_failed_live_runner_dismiss_completed() -> tuple[
    list[Agent], AgentCleanupRequestWire
]:
    retry = make_agent(
        cl_name="retry",
        raw_suffix="retry-ts",
        status="FAILED",
        pid=77,
        runner_is_live=True,
    )
    return [retry], make_request(
        scope=CLEANUP_SCOPE_ALL_PANELS,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
    )


def scenario_done_live_runner_dismiss() -> tuple[list[Agent], AgentCleanupRequestWire]:
    done = make_agent(
        cl_name="done-live",
        raw_suffix="done-live-ts",
        status="DONE",
        pid=78,
        runner_is_live=True,
    )
    failed = make_agent(
        cl_name="failed-still",
        raw_suffix="failed-still-ts",
        status="FAILED",
        pid=None,
        runner_is_live=False,
    )
    return [done, failed], make_request(
        scope=CLEANUP_SCOPE_ALL_PANELS,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
    )


__all__ = [
    "scenario_clan_sequential_agent_session_dismiss",
    "scenario_custom_child_running",
    "scenario_direct_live_monitor",
    "scenario_done_live_runner_dismiss",
    "scenario_explicit_child_done",
    "scenario_explicit_child_running",
    "scenario_explicit_clan_sequential_agent_session_dismiss",
    "scenario_failed_live_runner_dismiss_completed",
    "scenario_failed_live_runner_kill",
    "scenario_owner_cascades_live_monitor",
    "scenario_parallel_agent_session_root",
]

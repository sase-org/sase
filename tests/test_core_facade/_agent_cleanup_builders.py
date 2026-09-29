"""Shared builders for agent cleanup facade tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    AgentCleanupIdentityWire,
    AgentCleanupRequestWire,
)


START_TIME = datetime(2026, 4, 30, 9, 0, 0)
STOP_TIME = datetime(2026, 4, 30, 9, 5, 0)


def make_agent(
    *,
    agent_type: AgentType = AgentType.RUNNING,
    cl_name: str = "cl",
    status: str = "RUNNING",
    pid: int | None = 123,
    raw_suffix: str | None = "20260430090000",
    workflow: str | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    agent_session_parallel: bool = False,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
    tribe: str | None = None,
    agent_name: str | None = None,
    agent_session_role: str | None = None,
    role_suffix: str | None = None,
    monitor_id: str | None = None,
    monitor_state: str | None = None,
    workspace_num: int | None = 7,
    artifacts_dir: str | None = "/tmp/artifacts",
    start_time: datetime | None = START_TIME,
    stop_time: datetime | None = None,
    runner_is_live: bool = False,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/project.sase",
        status=status,
        start_time=start_time,
        stop_time=stop_time,
        workspace_num=workspace_num,
        workflow=workflow,
        pid=pid,
        raw_suffix=raw_suffix,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        agent_session_parallel=agent_session_parallel,
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
        tribe=tribe,
        agent_name=agent_name,
        agent_session_role=agent_session_role,
        role_suffix=role_suffix,
        monitor_id=monitor_id,
        monitor_state=monitor_state,
        artifacts_dir=artifacts_dir,
        runner_is_live=runner_is_live,
    )


def make_identity(agent: Agent) -> AgentCleanupIdentityWire:
    return AgentCleanupIdentityWire(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        raw_suffix=agent.raw_suffix,
    )


def make_request(
    *,
    scope: str,
    mode: str,
    focused_panel_tribe: str | None = None,
    tribe: str | None = None,
    clan_name: str | None = None,
    clan_generation: str | None = None,
    identities: tuple[AgentCleanupIdentityWire, ...] = (),
    include_pidless_as_dismissable: bool = False,
) -> AgentCleanupRequestWire:
    return AgentCleanupRequestWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        scope=scope,
        mode=mode,
        focused_panel_tribe=focused_panel_tribe,
        tribe=tribe,
        clan_name=clan_name,
        clan_generation=clan_generation,
        identities=identities,
        include_pidless_as_dismissable=include_pidless_as_dismissable,
    )


__all__ = [
    "START_TIME",
    "STOP_TIME",
    "make_agent",
    "make_identity",
    "make_request",
]

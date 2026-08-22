"""Shared helpers for the ``test_agent_family_*`` test modules."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models.agent import Agent, AgentType

_STARTED = datetime(2026, 7, 19, 9, 0, 0)


def _agent(
    name: str,
    *,
    role: str,
    parent_timestamp: str | None = None,
    workflow_child: bool = False,
    start_offset: int = 0,
    stop_offset: int | None = None,
    status: str = "DONE",
    status_bucket: str | None = None,
    step_type: str = "agent",
) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/family.sase",
        status=status,
        start_time=_STARTED + timedelta(minutes=start_offset),
        status_bucket=status_bucket,
        stop_time=(
            _STARTED + timedelta(minutes=stop_offset)
            if stop_offset is not None
            else None
        ),
        raw_suffix=f"suffix-{name}",
        parent_timestamp=parent_timestamp,
        agent_name=name,
        agent_family="alpha",
        agent_family_role=role,
        role_suffix=f"--{role}",
    )
    if workflow_child:
        agent.parent_workflow = "ace-run"
        agent.step_type = step_type
    return agent


def _plan_root(*, name: str = "alpha--plan") -> Agent:
    root = _agent(name, role="root")
    root.plan_chain_root = True
    root.role_suffix = "--plan"
    return root


def _monitor_member(
    name: str,
    *,
    root: Agent,
    monitor_id: str,
    monitor_state: str | None,
    stop_offset: int | None = None,
) -> Agent:
    monitor = _agent(
        name,
        role="monitor",
        parent_timestamp=root.raw_suffix,
        status="MONITORING" if monitor_state == "running" else "MONITORED",
        status_bucket="Running" if monitor_state == "running" else "Done",
        stop_offset=stop_offset,
    )
    monitor.monitor_id = monitor_id
    monitor.monitor_state = monitor_state
    return monitor

"""Shared helpers for the ``test_agent_session_*`` test modules.

Public helpers used by more than one ``test_agent_session_members_*`` module
live here under public names so no new module imports a ``_``-prefixed
name from another new module.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models.agent import Agent, AgentType

__all__ = [
    "make_agent",
    "make_gate_member",
    "make_monitor_member",
    "make_plan_root",
    "make_plan_root_with_main_step",
]

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
        project_file="/tmp/session.sase",
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
        agent_session="alpha",
        agent_session_role=role,
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


def _plan_root_with_main_step(*, name: str = "alpha--plan") -> tuple[Agent, Agent]:
    """Build a plan root with its loaded concrete ``main`` workflow step.

    Production plan-session containers share ``raw_suffix`` (and artifacts dir)
    with the ``main`` step but differ in ``cl_name``, so the step becomes the
    first shell anchor while the container itself is dropped from the list.
    """
    root = _plan_root(name=name)
    step = _agent(
        "main",
        role="plan",
        parent_timestamp=root.raw_suffix,
        workflow_child=True,
    )
    step.raw_suffix = root.raw_suffix
    step.step_index = 0
    step.parent_step_index = None
    root.runtime_children = [step]
    return root, step


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


def _gate_member(
    name: str,
    *,
    root: Agent,
    gate_id: str,
    gate_state: str | None,
    stop_offset: int | None = None,
) -> Agent:
    gate = _agent(
        name,
        role="gate",
        parent_timestamp=root.raw_suffix,
        status="GATE" if gate_state in {None, "pending", "settling"} else "GATED",
        status_bucket="Running" if gate_state == "settling" else "Done",
        stop_offset=stop_offset,
    )
    gate.gate_id = gate_id
    gate.gate_kind = "test"
    gate.gate_state = gate_state
    gate.gate_start_status = "GATE"
    gate.gate_stop_status = "GATED"
    gate.gate_label = name
    return gate


def make_agent(
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
    """Build a session-member test agent (public alias of ``_agent``)."""
    return _agent(
        name,
        role=role,
        parent_timestamp=parent_timestamp,
        workflow_child=workflow_child,
        start_offset=start_offset,
        stop_offset=stop_offset,
        status=status,
        status_bucket=status_bucket,
        step_type=step_type,
    )


def make_plan_root(*, name: str = "alpha--plan") -> Agent:
    """Build a plan-chain root (public alias of ``_plan_root``)."""
    return _plan_root(name=name)


def make_plan_root_with_main_step(*, name: str = "alpha--plan") -> tuple[Agent, Agent]:
    """Build a plan root with its loaded ``main`` step (public alias)."""
    return _plan_root_with_main_step(name=name)


def make_monitor_member(
    name: str,
    *,
    root: Agent,
    monitor_id: str,
    monitor_state: str | None,
    stop_offset: int | None = None,
) -> Agent:
    """Build a monitor member (public alias of ``_monitor_member``)."""
    return _monitor_member(
        name,
        root=root,
        monitor_id=monitor_id,
        monitor_state=monitor_state,
        stop_offset=stop_offset,
    )


def make_gate_member(
    name: str,
    *,
    root: Agent,
    gate_id: str,
    gate_state: str | None,
    stop_offset: int | None = None,
) -> Agent:
    """Build a gate member (public alias of ``_gate_member``)."""
    return _gate_member(
        name,
        root=root,
        gate_id=gate_id,
        gate_state=gate_state,
        stop_offset=stop_offset,
    )

"""Conversion and relationship helpers for agent cleanup targets."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sase.core.agent_cleanup_wire import (
    AgentCleanupIdentityWire,
    AgentCleanupTargetWire,
)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def agent_to_cleanup_target(agent: Any) -> AgentCleanupTargetWire:
    """Convert a TUI ``Agent`` object into cleanup planner wire data."""

    agent_type_value = getattr(agent.agent_type, "value", agent.agent_type)
    raw_suffix = agent.raw_suffix
    artifacts_dir = agent.artifacts_dir
    if artifacts_dir is None:
        get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
        if callable(get_artifacts_dir):
            artifacts_dir = get_artifacts_dir()
    return AgentCleanupTargetWire(
        identity=AgentCleanupIdentityWire(
            agent_type=str(agent_type_value),
            cl_name=str(agent.cl_name),
            raw_suffix=raw_suffix,
        ),
        agent_type=str(agent_type_value),
        status=str(agent.status),
        pid=agent.pid,
        workflow=agent.workflow,
        parent_workflow=agent.parent_workflow,
        parent_timestamp=agent.parent_timestamp,
        raw_suffix=raw_suffix,
        project_file=agent.project_file,
        artifacts_dir=artifacts_dir,
        from_patch=bool(getattr(agent, "_from_patch", False)),
        workspace=agent.effective_workspace_num,
        tribe=agent.tribe,
        agent_clan=agent.agent_clan,
        agent_clan_generation=agent.agent_clan_generation,
        agent_name=agent.agent_name,
        display_name=agent.display_name,
        start_time=_iso_or_none(agent.start_time),
        stop_time=_iso_or_none(agent.stop_time),
        is_workflow_child=agent.is_workflow_child,
        agent_family_parallel=bool(getattr(agent, "agent_family_parallel", False)),
        appears_as_agent=agent.appears_as_agent,
        step_type=agent.step_type,
        monitor_id=getattr(agent, "monitor_id", None),
        is_live_monitor=bool(
            getattr(agent, "is_monitor", False)
            and getattr(agent, "monitor_state", None) == "running"
        ),
    )


def agents_to_cleanup_targets(
    agents: Iterable[Any],
) -> tuple[AgentCleanupTargetWire, ...]:
    """Convert an iterable of TUI ``Agent`` objects to cleanup target wires."""

    return tuple(agent_to_cleanup_target(agent) for agent in agents)


def is_workflow_child(target: AgentCleanupTargetWire) -> bool:
    """True for any child row: workflow steps, family members, and monitors.

    The wire's ``is_workflow_child`` flag is a historical alias for this
    broader predicate. New cascade-only decisions must use
    :func:`is_workflow_step_child` instead.
    """
    return (
        target.is_workflow_child
        or target.parent_workflow is not None
        or target.parent_timestamp is not None
    )


def is_workflow_step_child(target: AgentCleanupTargetWire) -> bool:
    """True only for a workflow step child covered by its parent's cascade.

    Family members and monitor proc shells carry a ``parent_timestamp`` but
    are independent agent rows with their own PID, artifacts, and dismissal
    record.
    """
    return target.parent_workflow is not None

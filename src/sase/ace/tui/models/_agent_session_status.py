"""Concrete agent rows and effective statuses for session projections."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sase.agent.status_buckets import agent_status_bucket
from ._agent_session_lanes import (
    agent_session_member_status_buckets,
    is_sequential_agent_session_container,
    row_is_agent_session_turn,
)
from ._agent_session_turns import concrete_agent_session_member_rows
from .agent import Agent, AgentType


@dataclass(frozen=True, slots=True)
class ConcreteAgentStatus:
    """One concrete agent row and its presentation-side status bucket."""

    agent: Agent
    bucket: str


def _is_workflow_aggregate_row(agent: Agent) -> bool:
    """Return whether ``agent`` owns workflow-step presentation rows."""
    if agent.is_workflow_child:
        return False
    return agent.agent_type == AgentType.WORKFLOW or any(
        child.is_workflow_step_child
        for child in (*agent.runtime_children, *agent.followup_agents)
    )


def _concrete_agent_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return concrete agents represented by one non-container row.

    A loaded workflow aggregate is represented by its real agent-type steps.
    Python/bash steps never count as agents.  When no agent step is loaded,
    the aggregate row remains the compatibility fallback and counts once.
    """
    if agent.is_workflow_step_child:
        if (
            agent.step_type == "agent"
            and not agent.agent_session_parallel
            and not row_is_agent_session_turn(agent)
        ):
            return (agent,)
        return ()
    if row_is_agent_session_turn(agent):
        return ()
    if agent.is_named_proc:
        return ()

    if _is_workflow_aggregate_row(agent):
        agent_steps = _dedupe_rows(
            tuple(
                child
                for child in (*agent.runtime_children, *agent.followup_agents)
                if child.is_workflow_step_child
                and child.step_type == "agent"
                and not child.agent_session_parallel
                and not row_is_agent_session_turn(child)
            )
        )
        if agent_steps:
            return agent_steps
    return (agent,)


def agent_session_roster_container(agent: Agent) -> Agent | None:
    """Return the container row whose SESSION TURNS roster lists ``agent``.

    Container rows render their own roster and are never members of another
    row's roster, so they resolve to ``None``.
    """
    if agent.is_agent_session_container_row:
        return None
    container = agent.agent_session_container
    if container is None or container is agent:
        return None
    return container


def _dedupe_rows(rows: Sequence[Agent]) -> tuple[Agent, ...]:
    ordered: list[Agent] = []
    seen: set[int] = set()
    for row in rows:
        object_identity = id(row)
        if object_identity in seen:
            continue
        seen.add(object_identity)
        ordered.append(row)
    return tuple(ordered)


def concrete_agent_statuses(agent: Agent) -> tuple[ConcreteAgentStatus, ...]:
    """Project one non-clan unit into concrete rows and effective buckets."""
    if is_sequential_agent_session_container(agent):
        rows = concrete_agent_session_member_rows(agent)
        buckets = agent_session_member_status_buckets(rows)
    else:
        rows = _concrete_agent_rows(agent)
        buckets = tuple(agent_status_bucket(row) for row in rows)
    pairs = tuple(
        (row, bucket)
        for row, bucket in zip(rows, buckets, strict=True)
        if not row_is_agent_session_turn(row)
    )
    return tuple(ConcreteAgentStatus(agent=row, bucket=bucket) for row, bucket in pairs)

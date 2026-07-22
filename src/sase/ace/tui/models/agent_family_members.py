"""Pure in-memory projection of concrete agents and sequential families."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sase.agent.status_buckets import (
    APPROVED_PLAN_STATUSES,
    status_bucket_for_values,
)
from .agent import Agent, AgentType


@dataclass(frozen=True, slots=True)
class ConcreteAgentStatus:
    """One concrete agent row and its presentation-side status bucket."""

    agent: Agent
    bucket: str


def is_sequential_family_container(agent: Agent) -> bool:
    """Return whether ``agent`` represents a loaded sequential family.

    The second branch preserves compatibility with clan projections whose
    direct family root may predate the explicit ``agent_family_role`` marker
    but still owns loaded, serial family-member children.
    """
    if agent.agent_family_parallel:
        return False
    if agent.is_family_container_row:
        return True
    return bool(
        agent.agent_family
        and any(
            child.is_family_member_child and not child.agent_family_parallel
            for child in (*agent.runtime_children, *agent.followup_agents)
        )
    )


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
            and not agent.is_synthetic_planner
            and not agent.agent_family_parallel
        ):
            return (agent,)
        return ()

    if _is_workflow_aggregate_row(agent):
        agent_steps = _dedupe_rows(
            tuple(
                child
                for child in (*agent.runtime_children, *agent.followup_agents)
                if child.is_workflow_step_child
                and child.step_type == "agent"
                and not child.is_synthetic_planner
                and not child.agent_family_parallel
            )
        )
        if agent_steps:
            return agent_steps
    return (agent,)


def concrete_family_member_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return the ordered real rows represented by a family container.

    Plan workflow roots are aggregate rows.  When their concrete main agent
    step is loaded, that step owns the planner phase; otherwise the root stays
    as the compatibility fallback.  Rename-on-attach roots remain real first
    members for families that do not have a concrete planner step.
    """
    planner = _concrete_planner_child(agent)
    candidates: list[Agent] = []
    if planner is not None:
        candidates.append(planner)
    elif _root_represents_member(agent):
        candidates.append(agent)

    candidates.extend(_concrete_continuations(agent.runtime_children, planner))
    candidates.extend(_concrete_continuations(agent.followup_agents, planner))
    return _dedupe_rows(candidates)


def family_member_status_buckets(
    members: Sequence[Agent],
) -> tuple[str, ...]:
    """Return effective buckets for an ordered sequential family.

    An approved planner/tale member with a successor has handed the work off
    and is therefore settled.  The final member keeps the global bucket so a
    planner-only family that is still mid-handoff continues to read Running.
    """
    final_index = len(members) - 1
    return tuple(
        "Done"
        if index < final_index and member.status in APPROVED_PLAN_STATUSES
        else status_bucket_for_values(member.status)
        for index, member in enumerate(members)
    )


def concrete_agent_statuses(agent: Agent) -> tuple[ConcreteAgentStatus, ...]:
    """Project one non-clan unit into concrete rows and effective buckets."""
    if is_sequential_family_container(agent):
        rows = concrete_family_member_rows(agent)
        buckets = family_member_status_buckets(rows)
    else:
        rows = _concrete_agent_rows(agent)
        buckets = tuple(status_bucket_for_values(row.status) for row in rows)
    return tuple(
        ConcreteAgentStatus(agent=row, bucket=bucket)
        for row, bucket in zip(rows, buckets, strict=True)
    )


def _concrete_planner_child(agent: Agent) -> Agent | None:
    if not agent.is_plan_family_root_entry:
        return None
    return next(
        (
            child
            for child in agent.runtime_children
            if child.is_workflow_step_child
            and child.step_type == "agent"
            and child.parent_step_index is None
            and not child.is_synthetic_planner
            and not child.agent_family_parallel
        ),
        None,
    )


def _root_represents_member(agent: Agent) -> bool:
    if agent.is_plan_family_root_entry:
        return True
    family_name = agent.agent_family or agent.family_reference_name()
    return not bool(
        agent.agent_name and family_name and agent.agent_name == family_name
    )


def _concrete_continuations(
    rows: Sequence[Agent],
    planner: Agent | None,
) -> tuple[Agent, ...]:
    return tuple(
        row
        for row in rows
        if row is not planner
        and not row.is_workflow_step_child
        and not row.is_synthetic_planner
        and not row.agent_family_parallel
    )


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


__all__ = [
    "ConcreteAgentStatus",
    "concrete_agent_statuses",
    "concrete_family_member_rows",
    "family_member_status_buckets",
    "is_sequential_family_container",
]

"""Pure status/count aggregation for rootless agent clans."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.agent.status_buckets import (
    QUEUED_STATUS_BUCKET,
    aggregate_agent_group_status,
    agent_is_asking,
    status_bucket_for_values,
)

if TYPE_CHECKING:
    from .agent import Agent
    from .agent_types import AgentType

from .agent_status import DISMISSABLE_STATUSES
from .agent_family_members import (
    ConcreteAgentStatus,
    concrete_agent_statuses,
    is_sequential_family_container,
)

_CLAN_MEMBER_STATUS_PRIORITIES: dict[str, int] = {
    "Failed": 0,
    "Stopped": 1,
    "Running": 2,
    "Starting": 2,
    QUEUED_STATUS_BUCKET: 3,
    "Waiting": 4,
    "Done": 5,
}


@dataclass(frozen=True, slots=True)
class ClanStatusCounts:
    """Visible status counts for one clan's members.

    Queued counts refine the Waiting bucket and are excluded from waiting.
    """

    awaiting: int = 0
    failed: int = 0
    running: int = 0
    queued: int = 0
    waiting: int = 0
    unread: int = 0
    done: int = 0


@dataclass(frozen=True, slots=True)
class _AgentSummaryStatusCounts:
    """Summary counts with queued rows excluded from the Waiting bucket."""

    total: int = 0
    stopped: int = 0
    running: int = 0
    queued: int = 0
    waiting: int = 0
    failed: int = 0
    unread: int = 0
    done: int = 0


@dataclass(frozen=True, slots=True)
class _ProjectedSummaryAgent:
    """Concrete status projection plus summary-only counting context."""

    status: ConcreteAgentStatus
    projected_from_container: bool
    is_unread: bool


def aggregate_clan_status(statuses: Iterable[str]) -> str | None:
    """Return the shared aggregate agent-group display status."""
    return aggregate_agent_group_status(statuses)


def clan_member_status_priority(
    status: str | None,
    retried_as_timestamp: str | None = None,
) -> int:
    """Return the within-clan display rank for one direct member.

    The rank intentionally differs from the Agents tab's top-level
    ``BY_STATUS`` bucket order. Starting rows share Running's rank, and a
    future bucket unknown to this presentation helper sorts after every known
    bucket.
    """
    bucket = status_bucket_for_values(status, retried_as_timestamp)
    return _CLAN_MEMBER_STATUS_PRIORITIES.get(
        bucket,
        len(_CLAN_MEMBER_STATUS_PRIORITIES),
    )


def clan_members(agent: Agent) -> tuple[Agent, ...]:
    """Return already-loaded members belonging to ``agent``'s clan container."""
    clan_reference = agent.presented_clan_reference_name()
    if agent.is_clan_container:
        return tuple(
            child
            for child in agent.runtime_children
            if not child.is_clan_container
            and child.presented_clan_reference_name() == clan_reference
            and child.agent_clan_generation == agent.agent_clan_generation
        )
    clan = agent.agent_clan
    if clan:
        return tuple(
            child
            for child in agent.runtime_children
            if child is not agent
            and not child.is_clan_container
            and child.presented_clan_reference_name() == clan_reference
            and child.agent_clan_generation == agent.agent_clan_generation
        )
    # Legacy archives project parallel-family metadata into a clan at the wire
    # boundary, but directly constructed compatibility fixtures may still carry
    # only the old marker.
    return tuple(
        child
        for child in agent.runtime_children
        if child is not agent and child.agent_family_parallel
    )


def clan_member_counts(
    agent: Agent,
    unread_ids: Collection[tuple[AgentType, str, str | None]] = (),
) -> ClanStatusCounts:
    """Count a clan container's loaded members by display bucket."""
    awaiting = failed = running = queued = waiting = unread = done = 0
    seen: set[tuple[AgentType, str, str | None]] = set()
    for member in clan_members(agent):
        if member.identity in seen:
            continue
        seen.add(member.identity)
        projected_statuses = agent_status_projections((member,))
        aggregate_status = aggregate_clan_status(
            status.agent.status for status in projected_statuses
        )
        bucket = status_bucket_for_values(aggregate_status or member.status)
        is_unread = member.identity in unread_ids
        if is_unread:
            unread += 1
        if bucket == "Stopped":
            awaiting += 1
        elif bucket == "Failed":
            failed += 1
        elif bucket in {"Running", "Starting"}:
            running += 1
        elif bucket == QUEUED_STATUS_BUCKET:
            queued += 1
        elif bucket == "Waiting":
            waiting += 1
        elif bucket == "Done" and not is_unread:
            done += 1
    return ClanStatusCounts(
        awaiting=awaiting,
        failed=failed,
        running=running,
        queued=queued,
        waiting=waiting,
        unread=unread,
        done=done,
    )


def agent_summary_status_counts(
    agents: Iterable[Agent],
    unread_ids: Collection[tuple[AgentType, str, str | None]],
) -> _AgentSummaryStatusCounts:
    """Project containers into concrete-agent status counts for summaries."""
    projected = _dedupe_summary_projections(
        projection
        for agent in agents
        for projection in _summary_projections(agent, unread_ids)
    )
    return _status_counts_for_projections(projected)


def agent_lane_status_counts(
    agents: Iterable[Agent],
    unread_ids: Collection[tuple[AgentType, str, str | None]],
) -> _AgentSummaryStatusCounts:
    """Project containers into deduplicated agent-lane status counts."""
    projected = _dedupe_summary_projections(
        projection
        for agent in agents
        for projection in _lane_summary_projections(agent, unread_ids)
    )
    return _status_counts_for_projections(projected)


def _status_counts_for_projections(
    projected: Iterable[_ProjectedSummaryAgent],
) -> _AgentSummaryStatusCounts:
    total = stopped = running = queued = waiting = failed = unread = done = 0
    for projection in projected:
        projected_agent = projection.status.agent
        bucket = projection.status.bucket
        total += 1
        if bucket == QUEUED_STATUS_BUCKET:
            queued += 1
        if projection.is_unread:
            unread += 1
        if agent_is_asking(projected_agent.status):
            stopped += 1
        elif bucket == "Failed":
            failed += 1
        elif bucket == "Waiting":
            waiting += 1
        elif bucket == "Done":
            if not projection.is_unread:
                done += 1
        elif bucket == "Running" and (
            projected_agent.status not in DISMISSABLE_STATUSES
        ):
            running += 1
        elif bucket == "Starting" and projection.projected_from_container:
            running += 1
    return _AgentSummaryStatusCounts(
        total=total,
        stopped=stopped,
        running=running,
        queued=queued,
        waiting=waiting,
        failed=failed,
        unread=unread,
        done=done,
    )


def agent_status_projections(
    agents: Iterable[Agent],
) -> tuple[ConcreteAgentStatus, ...]:
    """Return deduped concrete rows and effective buckets for summaries."""
    projected = _dedupe_summary_projections(
        projection for agent in agents for projection in _summary_projections(agent, ())
    )
    return tuple(projection.status for projection in projected)


def _lane_summary_projections(
    agent: Agent,
    unread_ids: Collection[tuple[AgentType, str, str | None]],
    *,
    projected_from_container: bool = False,
) -> tuple[_ProjectedSummaryAgent, ...]:
    if agent.is_clan_container:
        return tuple(
            projection
            for member in clan_members(agent)
            for projection in _lane_summary_projections(
                member,
                unread_ids,
                projected_from_container=True,
            )
        )
    if agent.agent_family_parallel:
        members = clan_members(agent)
        if members:
            return tuple(
                _ProjectedSummaryAgent(
                    status=ConcreteAgentStatus(
                        agent=member,
                        bucket=status_bucket_for_values(member.status),
                    ),
                    projected_from_container=True,
                    is_unread=member.identity in unread_ids,
                )
                for member in members
            )
    return (
        _ProjectedSummaryAgent(
            status=ConcreteAgentStatus(
                agent=agent,
                bucket=status_bucket_for_values(agent.status),
            ),
            projected_from_container=projected_from_container,
            is_unread=agent.identity in unread_ids,
        ),
    )


def _summary_projections(
    agent: Agent,
    unread_ids: Collection[tuple[AgentType, str, str | None]],
) -> tuple[_ProjectedSummaryAgent, ...]:
    members = (
        clan_members(agent)
        if agent.is_clan_container or agent.agent_family_parallel
        else ()
    )
    if members:
        if agent.is_clan_container:
            projected = tuple(
                projection
                for member in members
                for projection in _summary_projections(member, unread_ids)
            )
        else:
            # Preserve the legacy parallel-family projection: only the loaded
            # parallel members replace their compatibility aggregate root.
            projected = tuple(
                _ProjectedSummaryAgent(
                    status=status,
                    projected_from_container=True,
                    is_unread=status.agent.identity in unread_ids,
                )
                for member in members
                for status in concrete_agent_statuses(member)
            )
        projected = tuple(
            _ProjectedSummaryAgent(
                status=item.status,
                projected_from_container=True,
                is_unread=item.is_unread,
            )
            for item in projected
        )
    else:
        statuses = concrete_agent_statuses(agent)
        projected_from_container = is_sequential_family_container(agent) or any(
            status.agent.identity != agent.identity for status in statuses
        )
        projected = tuple(
            _ProjectedSummaryAgent(
                status=status,
                projected_from_container=projected_from_container,
                is_unread=status.agent.identity in unread_ids,
            )
            for status in statuses
        )

    if (
        projected
        and agent.identity in unread_ids
        and not any(item.is_unread for item in projected)
    ):
        last = projected[-1]
        projected = (
            *projected[:-1],
            _ProjectedSummaryAgent(
                status=last.status,
                projected_from_container=last.projected_from_container,
                is_unread=True,
            ),
        )
    return projected


def _dedupe_summary_projections(
    projections: Iterable[_ProjectedSummaryAgent],
) -> tuple[_ProjectedSummaryAgent, ...]:
    ordered: list[_ProjectedSummaryAgent] = []
    position_by_identity: dict[tuple[AgentType, str, str | None], int] = {}
    for projection in projections:
        identity = projection.status.agent.identity
        existing_position = position_by_identity.get(identity)
        if existing_position is None:
            position_by_identity[identity] = len(ordered)
            ordered.append(projection)
            continue
        existing = ordered[existing_position]
        if (projection.is_unread and not existing.is_unread) or (
            projection.projected_from_container
            and not existing.projected_from_container
        ):
            ordered[existing_position] = _ProjectedSummaryAgent(
                status=existing.status,
                projected_from_container=(
                    existing.projected_from_container
                    or projection.projected_from_container
                ),
                is_unread=existing.is_unread or projection.is_unread,
            )
    return tuple(ordered)


__all__ = [
    "ClanStatusCounts",
    "agent_lane_status_counts",
    "agent_status_projections",
    "agent_summary_status_counts",
    "aggregate_clan_status",
    "clan_member_status_priority",
    "clan_member_counts",
    "clan_members",
]

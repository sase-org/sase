"""Pure status/count aggregation for rootless agent clans."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.agent.status_buckets import agent_is_asking, status_bucket_for_values

if TYPE_CHECKING:
    from .agent import Agent
    from .agent_types import AgentType

from .agent_status import DISMISSABLE_STATUSES

_QUESTION_STATUSES = frozenset({"QUESTION", "WAITING INPUT"})


@dataclass(frozen=True, slots=True)
class ClanStatusCounts:
    """Visible status counts for one clan's members."""

    awaiting: int = 0
    failed: int = 0
    running: int = 0
    waiting: int = 0
    done: int = 0


@dataclass(frozen=True, slots=True)
class _AgentSummaryStatusCounts:
    total: int = 0
    stopped: int = 0
    running: int = 0
    waiting: int = 0
    failed: int = 0
    unread: int = 0
    done: int = 0


def aggregate_clan_status(statuses: Iterable[str]) -> str | None:
    """Return aggregate clan status in display-priority order."""
    values = tuple(statuses)
    if not values:
        return None
    if any(status in _QUESTION_STATUSES for status in values):
        return "QUESTION"
    if "PLAN" in values:
        return "PLAN"
    buckets = tuple(status_bucket_for_values(status) for status in values)
    if "Failed" in buckets or "KILLED" in values:
        return "FAILED"
    if "Running" in buckets or "Starting" in buckets:
        return "RUNNING"
    if "Waiting" in buckets:
        return "WAITING"
    if all(bucket == "Done" for bucket in buckets):
        return "DONE"
    return "RUNNING"


def clan_members(agent: Agent) -> tuple[Agent, ...]:
    """Return already-loaded members belonging to ``agent``'s clan container."""
    clan = agent.agent_clan
    if clan:
        return tuple(
            child
            for child in agent.runtime_children
            if child is not agent and child.agent_clan == clan
        )
    # Legacy archives project parallel-family metadata into a clan at the wire
    # boundary, but directly constructed compatibility fixtures may still carry
    # only the old marker.
    return tuple(
        child
        for child in agent.runtime_children
        if child is not agent and child.agent_family_parallel
    )


def clan_member_counts(agent: Agent) -> ClanStatusCounts:
    """Count a clan container's loaded members by display bucket."""
    awaiting = failed = running = waiting = done = 0
    for member in clan_members(agent):
        bucket = status_bucket_for_values(member.status)
        if bucket == "Stopped":
            awaiting += 1
        elif bucket == "Failed":
            failed += 1
        elif bucket in {"Running", "Starting"}:
            running += 1
        elif bucket == "Waiting":
            waiting += 1
        elif bucket == "Done":
            done += 1
    return ClanStatusCounts(
        awaiting=awaiting,
        failed=failed,
        running=running,
        waiting=waiting,
        done=done,
    )


def agent_summary_status_counts(
    agents: Iterable[Agent],
    unread_ids: Collection[tuple[AgentType, str, str | None]],
) -> _AgentSummaryStatusCounts:
    """Project clan containers into the status counts used by summaries."""
    total = stopped = running = waiting = failed = unread = done = 0
    for agent in agents:
        members = clan_members(agent)
        projected_agents = members or (agent,)
        for projected_agent in projected_agents:
            total += 1
            bucket = status_bucket_for_values(projected_agent.status)
            is_unread = projected_agent.identity in unread_ids
            if is_unread:
                unread += 1
            if agent_is_asking(projected_agent.status):
                stopped += 1
            elif bucket == "Failed":
                failed += 1
            elif bucket == "Waiting":
                waiting += 1
            elif bucket == "Done":
                if not is_unread:
                    done += 1
            elif bucket == "Running" and (
                projected_agent.status not in DISMISSABLE_STATUSES
            ):
                running += 1
            elif bucket == "Starting" and members:
                running += 1
    return _AgentSummaryStatusCounts(
        total=total,
        stopped=stopped,
        running=running,
        waiting=waiting,
        failed=failed,
        unread=unread,
        done=done,
    )


__all__ = [
    "ClanStatusCounts",
    "agent_summary_status_counts",
    "aggregate_clan_status",
    "clan_member_counts",
    "clan_members",
]

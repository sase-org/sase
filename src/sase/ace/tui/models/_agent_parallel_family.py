"""Pure status/count aggregation for parallel agent families."""

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
class ParallelFamilyStatusCounts:
    """Visible status counts for the parallel members under one root."""

    awaiting: int = 0
    failed: int = 0
    running: int = 0
    waiting: int = 0
    done: int = 0


@dataclass(frozen=True, slots=True)
class _AgentSummaryStatusCounts:
    """Status counts projected into Agents-tab summary categories."""

    stopped: int = 0
    running: int = 0
    waiting: int = 0
    failed: int = 0
    unread: int = 0
    done: int = 0


def aggregate_parallel_family_status(statuses: Iterable[str]) -> str | None:
    """Return the root status for a parallel family in display-priority order."""
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


def parallel_family_members(agent: Agent) -> tuple[Agent, ...]:
    """Return already-loaded direct children marked as parallel members."""
    return tuple(
        child
        for child in agent.runtime_children
        if child is not agent and child.agent_family_parallel
    )


def parallel_family_member_counts(agent: Agent) -> ParallelFamilyStatusCounts:
    """Count the root's already-loaded parallel members by display bucket."""
    awaiting = failed = running = waiting = done = 0
    for member in parallel_family_members(agent):
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
    return ParallelFamilyStatusCounts(
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
    """Project top-level rows into the status counts used by summary surfaces.

    A parallel family root contributes its already-loaded parallel members
    instead of its aggregate root status. Rows without loaded parallel members
    retain their ordinary single-row contribution. Serial runtime children are
    ignored by :func:`parallel_family_members`.
    """
    stopped = running = waiting = failed = unread = done = 0
    for agent in agents:
        family_members = parallel_family_members(agent)
        projected_agents = family_members or (agent,)
        for projected_agent in projected_agents:
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
            elif bucket == "Starting" and family_members:
                # Family rows already render STARTING members in their running
                # count so the summary surfaces must use the same projection.
                running += 1

    return _AgentSummaryStatusCounts(
        stopped=stopped,
        running=running,
        waiting=waiting,
        failed=failed,
        unread=unread,
        done=done,
    )

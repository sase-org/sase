"""Pure status/count aggregation for parallel agent families."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.agent.status_buckets import status_bucket_for_values

if TYPE_CHECKING:
    from .agent import Agent


_QUESTION_STATUSES = frozenset({"QUESTION", "WAITING INPUT"})


@dataclass(frozen=True, slots=True)
class _ParallelFamilyStatusCounts:
    """Visible status counts for the parallel members under one root."""

    awaiting: int = 0
    failed: int = 0
    running: int = 0
    waiting: int = 0
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


def parallel_family_member_counts(agent: Agent) -> _ParallelFamilyStatusCounts:
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
    return _ParallelFamilyStatusCounts(
        awaiting=awaiting,
        failed=failed,
        running=running,
        waiting=waiting,
        done=done,
    )


def parallel_family_summary_text(agent: Agent) -> str:
    """Return a compact ``"2 running · 1 done"`` member summary."""
    counts = parallel_family_member_counts(agent)
    parts: list[str] = []
    for count, label in (
        (counts.awaiting, "awaiting"),
        (counts.failed, "failed"),
        (counts.running, "running"),
        (counts.waiting, "waiting"),
        (counts.done, "done"),
    ):
        if count:
            parts.append(f"{count} {label}")
    return " · ".join(parts)

"""In-memory runner-slot display context for Agents-tab rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.agent.status_buckets import (
    PRE_RUN_WAIT_STATUSES,
    runner_slot_display_status,
)
from sase.core.runner_slots import (
    normalize_wait_priority,
    runner_slot_waiter_sort_key,
)

from .agent import Agent, AgentType


@dataclass(frozen=True, slots=True)
class RunnerQueueEntry:
    """Presentation facts for one waiter in canonical admission order."""

    identity: tuple[AgentType, str, str | None]
    presented_name: str
    threshold: int | None
    wait_runners_explicit: bool
    priority: int
    slot_requested_at: str | None
    status: str


@dataclass(frozen=True)
class RunnerCapacitySnapshot:
    """Immutable global user-agent runner capacity for one Agents load."""

    effective_limit: int = 0
    slots_in_use: int = 0
    queued_count: int = 0
    queue: tuple[RunnerQueueEntry, ...] = ()


def refresh_runner_slot_context(
    agents: list[Agent],
    *,
    effective_limit: int | None = None,
) -> RunnerCapacitySnapshot:
    """Attach live count and admission-queue position from the loaded snapshot.

    The loader has already PID-filtered active rows. Deriving this context
    after the Tier-1/artifact-delta merge keeps the operation O(rows), pure,
    and consistent across full and selective refreshes. When the caller does
    not supply an effective limit, row context is still refreshed while the
    returned capacity snapshot remains the deterministic neutral fallback.
    """
    running_count = sum(1 for agent in agents if _holds_runner_slot(agent))
    waiters = sorted(
        (agent for agent in agents if _is_live_slot_waiter(agent)),
        key=_waiter_sort_key,
    )
    queue_positions: dict[int, int] = {}
    queue_entries: list[RunnerQueueEntry] = []
    queue_size = len(waiters)

    # Promote real waiters before refreshing synthetic clan aggregates below.
    # Clan projection runs before this display-only slot pass, so doing this
    # first keeps an all-queued clan from retaining its earlier WAITING status
    # until the next refresh. Reuse the queue-position traversal rather than
    # adding another pass over the loaded rows.
    for index, agent in enumerate(waiters, 1):
        queue_positions[id(agent)] = index
        agent.status = runner_slot_display_status(
            agent.status,
            slot_queued=True,
        )
        queue_entries.append(
            RunnerQueueEntry(
                identity=agent.identity,
                presented_name=(
                    agent.presented_agent_name
                    or agent.agent_name
                    or agent.cl_name
                    or "unassigned"
                ),
                threshold=agent.wait_runners,
                wait_runners_explicit=agent.wait_runners_explicit,
                priority=normalize_wait_priority(agent.wait_priority),
                slot_requested_at=agent.slot_requested_at,
                status=agent.status,
            )
        )
    from ._agent_clan import aggregate_clan_status, clan_members

    for agent in agents:
        if agent.slot_requested_at:
            agent.runner_slots_in_use = running_count
            agent.runner_slot_queue_position = queue_positions.get(id(agent))
            agent.runner_slot_queue_size = queue_size
        else:
            agent.runner_slots_in_use = None
            agent.runner_slot_queue_position = None
            agent.runner_slot_queue_size = None
        if agent.is_clan_container:
            aggregate = aggregate_clan_status(
                member.status for member in clan_members(agent)
            )
            agent.status = aggregate or runner_slot_display_status(
                agent.status,
                slot_queued=False,
            )
        else:
            agent.status = runner_slot_display_status(
                agent.status,
                slot_queued=_is_live_slot_waiter(agent),
            )

    if effective_limit is None:
        return RunnerCapacitySnapshot(queue=tuple(queue_entries))
    return RunnerCapacitySnapshot(
        effective_limit=effective_limit,
        slots_in_use=running_count,
        queued_count=len(queue_entries),
        queue=tuple(queue_entries),
    )


def _is_ace_run_root(agent: Agent) -> bool:
    if agent.is_clan_container or agent.is_child_row:
        return False
    if agent.slot_requested_at:
        return True
    if agent.artifacts_dir and Path(agent.artifacts_dir).parent.name == "ace-run":
        return True
    if agent.appears_as_agent:
        return True
    workflow = agent.workflow or ""
    return workflow == "ace-run" or workflow.startswith("ace(run)")


def _participates_in_runner_slots(agent: Agent) -> bool:
    return _is_ace_run_root(agent) or (
        agent.is_family_member_child and agent.agent_family_parallel
    )


def _holds_runner_slot(agent: Agent) -> bool:
    return (
        _participates_in_runner_slots(agent)
        and agent.pid is not None
        and agent.run_start_time is not None
        and agent.stop_time is None
        and not agent.runner_slot_yielded
        and agent.status not in {"DONE", "FAILED", "FAILED (RETRIED)"}
    )


def _is_live_slot_waiter(agent: Agent) -> bool:
    return (
        _participates_in_runner_slots(agent)
        and agent.pid is not None
        and bool(agent.slot_requested_at)
        and agent.status in PRE_RUN_WAIT_STATUSES
    )


def _waiter_sort_key(agent: Agent) -> tuple[int, int, datetime, str, str]:
    # Snapshot-backed running rows use the source record timestamp as
    # ``raw_suffix``; claim-backed rows normalize the same artifact timestamp.
    return runner_slot_waiter_sort_key(
        priority=agent.wait_priority,
        slot_requested_at=agent.slot_requested_at,
        timestamp=agent.raw_suffix,
        artifact_dir=agent.artifacts_dir,
    )


__all__ = [
    "RunnerCapacitySnapshot",
    "RunnerQueueEntry",
    "refresh_runner_slot_context",
]

"""In-memory runner-slot display context for Agents-tab rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sase.agent.status_buckets import (
    PRE_RUN_WAIT_STATUSES,
    QUEUED_STATUS_BUCKET,
    runner_slot_display_status,
    status_bucket_for_values,
)
from sase.core.runner_slots import normalize_wait_priority

from .agent import Agent


@dataclass(frozen=True)
class RunnerCapacitySnapshot:
    """Immutable global user-agent runner capacity for one Agents load."""

    effective_limit: int = 0
    slots_in_use: int = 0
    global_cap_queue_count: int = 0


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
    queue_size = len(waiters)
    queued_count = 0

    # Promote real waiters before refreshing synthetic clan aggregates below.
    # Clan projection runs before this display-only slot pass, so doing this
    # first keeps an all-queued clan from retaining its earlier WAITING status
    # until the next refresh. Reuse the queue-position traversal rather than
    # adding another pass over the loaded rows.
    for index, agent in enumerate(waiters, 1):
        queue_positions[id(agent)] = index
        agent.status = runner_slot_display_status(
            agent.status,
            globally_queued=_agent_is_globally_queued(agent),
        )
        if status_bucket_for_values(agent.status) == QUEUED_STATUS_BUCKET:
            queued_count += 1

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
                globally_queued=False,
            )
        else:
            agent.status = runner_slot_display_status(
                agent.status,
                globally_queued=_agent_is_globally_queued(agent),
            )

    if effective_limit is None:
        return RunnerCapacitySnapshot()
    return RunnerCapacitySnapshot(
        effective_limit=effective_limit,
        slots_in_use=running_count,
        global_cap_queue_count=queued_count,
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


def _agent_is_globally_queued(agent: Agent) -> bool:
    """Return whether ``agent`` is waiting specifically on the global cap."""
    return _is_live_slot_waiter(agent) and not agent.wait_runners_explicit


def _waiter_sort_key(agent: Agent) -> tuple[int, int, datetime, str, str]:
    requested_at = agent.slot_requested_at or ""
    try:
        parsed = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
        invalid = 0
    except ValueError:
        parsed = datetime.max.replace(tzinfo=UTC)
        invalid = 1
    artifacts_dir = agent.artifacts_dir or ""
    return (
        normalize_wait_priority(agent.wait_priority),
        invalid,
        parsed,
        agent.raw_suffix or "",
        artifacts_dir,
    )


__all__ = [
    "RunnerCapacitySnapshot",
    "refresh_runner_slot_context",
]

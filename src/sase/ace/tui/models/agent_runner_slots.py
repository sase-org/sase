"""In-memory runner-slot display context for Agents-tab rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .agent import Agent


@dataclass(frozen=True)
class RunnerCapacitySnapshot:
    """Immutable global user-agent runner capacity for one Agents load."""

    configured_limit: int = 0
    slots_in_use: int = 0
    global_cap_queue_count: int = 0


def refresh_runner_slot_context(
    agents: list[Agent],
    *,
    configured_limit: int | None = None,
) -> RunnerCapacitySnapshot:
    """Attach live count and eligible FIFO position from the loaded snapshot.

    The loader has already PID-filtered active rows. Deriving this context
    after the Tier-1/artifact-delta merge keeps the operation O(rows), pure,
    and consistent across full and selective refreshes. When the caller does
    not supply a configured limit, row context is still refreshed while the
    returned capacity snapshot remains the deterministic neutral fallback.
    """
    running_count = sum(1 for agent in agents if _holds_runner_slot(agent))
    waiters = sorted(
        (agent for agent in agents if _is_live_slot_waiter(agent)),
        key=_waiter_sort_key,
    )
    eligible_waiters = [
        agent
        for agent in waiters
        if agent.wait_runners is not None and running_count <= agent.wait_runners
    ]
    queue_positions = {
        id(agent): index for index, agent in enumerate(eligible_waiters, 1)
    }
    queue_size = len(eligible_waiters)

    for agent in agents:
        if agent.slot_requested_at:
            agent.runner_slots_in_use = running_count
            agent.runner_slot_queue_position = queue_positions.get(id(agent))
            agent.runner_slot_queue_size = queue_size
        else:
            agent.runner_slots_in_use = None
            agent.runner_slot_queue_position = None
            agent.runner_slot_queue_size = None

    if configured_limit is None:
        return RunnerCapacitySnapshot()
    return RunnerCapacitySnapshot(
        configured_limit=configured_limit,
        slots_in_use=running_count,
        global_cap_queue_count=sum(
            1 for agent in waiters if not agent.wait_runners_explicit
        ),
    )


def _is_ace_run_root(agent: Agent) -> bool:
    if agent.is_child_row:
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
        and agent.status == "WAITING"
    )


def _waiter_sort_key(agent: Agent) -> tuple[int, datetime, str, str]:
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
    return invalid, parsed, agent.raw_suffix or "", artifacts_dir


__all__ = ["RunnerCapacitySnapshot", "refresh_runner_slot_context"]

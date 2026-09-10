"""In-memory runner-slot display context for Agents-tab rows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.agent.status_buckets import (
    PRE_RUN_WAIT_STATUSES,
    agent_status_bucket,
    runner_slot_display_status,
)
from sase.core.runner_slots import (
    DEFAULT_QUEUE_WEIGHT,
    normalize_wait_priority,
    runner_capacity_snapshot_from_capacity_records,
    runner_slot_queue_display_key,
)

from .agent import Agent, AgentType
from .agent_status import DISMISSABLE_STATUSES


@dataclass(frozen=True, slots=True)
class RunnerQueueEntry:
    """Presentation facts for one waiter in capacity-aware queue order."""

    identity: tuple[AgentType, str, str | None]
    presented_name: str
    threshold: int | None
    wait_runners_explicit: bool
    priority: int
    slot_requested_at: str | None
    status: str
    requested_weight: float = DEFAULT_QUEUE_WEIGHT
    eligible: bool = False
    blockers: tuple[dict[str, Any], ...] = ()
    parked: bool = False


@dataclass(frozen=True)
class RunnerCapacitySnapshot:
    """Immutable global user-agent runner capacity for one Agents load."""

    effective_limit: float = 0.0
    slots_in_use: int = 0
    queued_count: int = 0
    queue: tuple[RunnerQueueEntry, ...] = ()
    occupied_capacity: float | None = None


def format_capacity_value(value: object, *, minimum_decimal: bool = True) -> str:
    """Format a capacity unit value without binary floating-point noise."""
    number = _finite_float(value)
    if number is None:
        return "—"
    absolute = abs(number)
    if number != 0.0 and (absolute >= 1.0e9 or absolute < 1.0e-6):
        text = f"{number:.6g}"
    else:
        text = f"{number:.12f}".rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        text = "0"
    if minimum_decimal and "e" not in text and "E" not in text and "." not in text:
        text += ".0"
    return text


def format_queue_weight_badge_value(value: object) -> str | None:
    """Return compact badge text for non-default valid queue weights."""
    weight = _finite_float(value)
    if weight is None or math.isclose(
        weight,
        DEFAULT_QUEUE_WEIGHT,
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        return None
    return format_capacity_value(weight, minimum_decimal=False)


def refresh_runner_slot_context(
    agents: list[Agent],
    *,
    effective_limit: float | None = None,
    capacity_agents: list[Agent] | None = None,
) -> RunnerCapacitySnapshot:
    """Attach global runner-capacity context from the loaded snapshot.

    The loader has already PID-filtered active rows. Deriving this context
    from the caller's source roster keeps the operation O(rows), pure, and
    consistent across full and selective refreshes even when the display list
    has already been hidden, searched, folded, or fleet-projected. When the
    caller does not supply an effective limit, row context is still refreshed
    while the returned capacity snapshot remains the deterministic neutral
    fallback.

    The weighted occupancy, queue order, eligibility, and blocker details come
    from the Rust admission projection used by the launcher. Integer lane
    counts remain available separately from weighted capacity units so existing
    readers do not need to reinterpret a count as a fractional quantity.
    """
    if effective_limit is None:
        return _refresh_runner_slot_context_fallback(agents)

    capacity_source = agents if capacity_agents is None else capacity_agents
    capacity_records = tuple(
        _capacity_record_from_agent(agent) for agent in capacity_source
    )
    raw_snapshot = runner_capacity_snapshot_from_capacity_records(
        capacity_records,
        effective_limit=float(effective_limit),
    )
    return _apply_runner_capacity_snapshot(
        agents,
        raw_snapshot,
        capacity_agents=capacity_source,
    )


def _refresh_runner_slot_context_fallback(
    agents: list[Agent],
) -> RunnerCapacitySnapshot:
    """Refresh queue status when no configured capacity limit is available."""
    from ._agent_clan import (
        aggregate_clan_status,
        clan_members,
        sase_agent_status_counts,
    )

    lane_candidates = _lane_candidates(agents)
    running_count = _display_running_lane_count(lane_candidates)
    waiters = sorted(
        (agent for agent in agents if _is_live_slot_waiter(agent)),
        key=lambda agent: _waiter_sort_key(agent, running_count=running_count),
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
        threshold = agent.wait_runners if agent.wait_runners is not None else 0
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
                parked=running_count > threshold,
            )
        )

    for agent in agents:
        if agent.slot_requested_at:
            agent.runner_slots_in_use = running_count
            agent.runner_occupied_capacity = None
            agent.runner_effective_limit = None
            agent.runner_slot_queue_position = queue_positions.get(id(agent))
            agent.runner_slot_queue_size = queue_size
            agent.runner_capacity_blockers = ()
        else:
            agent.runner_slots_in_use = None
            agent.runner_occupied_capacity = None
            agent.runner_effective_limit = None
            agent.runner_slot_queue_position = None
            agent.runner_slot_queue_size = None
            agent.runner_capacity_blockers = ()
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

    return RunnerCapacitySnapshot(
        slots_in_use=running_count,
        queue=tuple(queue_entries),
    )


def _apply_runner_capacity_snapshot(
    agents: list[Agent],
    raw_snapshot: dict[str, Any],
    *,
    capacity_agents: list[Agent] | None = None,
) -> RunnerCapacitySnapshot:
    """Apply a Rust runner-capacity snapshot to mutable TUI agent rows."""
    from ._agent_clan import aggregate_clan_status, clan_members

    running_count = _int_value(raw_snapshot.get("occupied_lanes")) or 0
    occupied_capacity = _finite_float(raw_snapshot.get("occupied_capacity"))
    effective_limit = _finite_float(raw_snapshot.get("effective_limit")) or 0.0
    display_agent_by_artifact_dir = {
        _capacity_artifact_dir(agent): agent for agent in agents
    }
    source_agent_by_artifact_dir = {
        _capacity_artifact_dir(agent): agent
        for agent in (agents if capacity_agents is None else capacity_agents)
    }
    queue_entries: list[RunnerQueueEntry] = []
    queue_positions: dict[int, int] = {}
    queue_blockers: dict[int, tuple[dict[str, Any], ...]] = {}
    waiters = _ordered_snapshot_waiters(raw_snapshot.get("waiters", ()))
    queue_size = len(waiters)

    for index, waiter in enumerate(waiters, 1):
        artifact_dir = _text_value(waiter.get("artifact_dir"))
        display_agent = (
            display_agent_by_artifact_dir.get(artifact_dir)
            if artifact_dir is not None
            else None
        )
        agent = display_agent or (
            source_agent_by_artifact_dir.get(artifact_dir)
            if artifact_dir is not None
            else None
        )
        if agent is None:
            continue
        blockers = _blocker_tuple(waiter.get("blockers"))
        queue_position = _positive_int(waiter.get("queue_position")) or index
        if display_agent is not None:
            queue_positions[id(display_agent)] = queue_position
            queue_blockers[id(display_agent)] = blockers
            display_agent.status = runner_slot_display_status(
                display_agent.status,
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
                threshold=_nonnegative_int(waiter.get("wait_runners")),
                wait_runners_explicit=agent.wait_runners_explicit,
                priority=normalize_wait_priority(waiter.get("priority")),
                slot_requested_at=_text_value(waiter.get("slot_requested_at")),
                status=(
                    display_agent.status if display_agent is not None else agent.status
                ),
                requested_weight=(
                    _finite_float(waiter.get("requested_weight"))
                    or DEFAULT_QUEUE_WEIGHT
                ),
                eligible=waiter.get("eligible") is True,
                blockers=blockers,
                parked=_snapshot_waiter_is_parked(waiter),
            )
        )

    for agent in agents:
        if agent.slot_requested_at:
            agent.runner_slots_in_use = running_count
            agent.runner_occupied_capacity = occupied_capacity
            agent.runner_effective_limit = effective_limit
            agent.runner_slot_queue_position = queue_positions.get(id(agent))
            agent.runner_slot_queue_size = queue_size
            agent.runner_capacity_blockers = queue_blockers.get(id(agent), ())
        else:
            agent.runner_slots_in_use = None
            agent.runner_occupied_capacity = None
            agent.runner_effective_limit = None
            agent.runner_slot_queue_position = None
            agent.runner_slot_queue_size = None
            agent.runner_capacity_blockers = ()
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
                slot_queued=id(agent) in queue_positions,
            )

    return RunnerCapacitySnapshot(
        effective_limit=effective_limit,
        slots_in_use=running_count,
        queued_count=queue_size,
        queue=tuple(queue_entries),
        occupied_capacity=occupied_capacity,
    )


def _lane_candidates(agents: list[Agent]) -> list[Agent]:
    return [
        agent
        for agent in agents
        if agent.is_clan_container or agent.is_child_row or _is_ace_run_root(agent)
    ]


def _display_running_lane_count(lane_candidates: list[Agent]) -> int:
    from ._agent_clan import sase_agent_status_counts

    running_count = sase_agent_status_counts(lane_candidates, ()).running
    running_count += sum(
        1
        for agent in lane_candidates
        if not agent.is_clan_container
        and not agent.is_child_row
        and not _agent_lane_bucket_counts_as_running(agent)
        and _container_is_genuinely_occupying(agent)
    )
    return running_count


def _capacity_record_from_agent(agent: Agent) -> dict[str, Any]:
    artifacts_dir = _capacity_artifact_dir(agent)
    return {
        "artifact_dir": artifacts_dir,
        "project_name": _project_name(agent),
        "workflow_dir_name": _workflow_dir_name(agent),
        "timestamp": _capacity_timestamp(agent),
        "has_agent_meta": not (agent.is_clan_container or agent.is_proc_shell),
        "has_done_marker": agent.stop_time is not None
        or agent.status in {"DONE", "FAILED", "FAILED (RETRIED)"},
        "appears_as_agent": _appears_as_agent(agent),
        "live": _capacity_record_is_live(agent),
        "pending_question": agent.runner_slot_yielded,
        "pid": agent.pid,
        "run_started_at": _capacity_run_started_at(agent),
        "parent_timestamp": agent.parent_timestamp,
        "agent_family": _capacity_agent_family(agent),
        "agent_family_role": agent.agent_family_role,
        "agent_family_parallel": agent.agent_family_parallel,
        "family_shell_kind": _family_shell_kind(agent),
        "family_shell_id": _family_shell_id(agent),
        "family_shell_state": _family_shell_state(agent),
        "queue_weight": None
        if agent.queue_weight_invalid
        else _finite_float(agent.queue_weight),
        "queue_weight_explicit": agent.queue_weight_explicit,
        "queue_weight_invalid": agent.queue_weight_invalid,
        "slot_requested_at": agent.slot_requested_at
        if _is_live_slot_waiter(agent)
        else None,
        "wait_runners": _nonnegative_int(agent.wait_runners),
        "wait_runners_explicit": agent.wait_runners_explicit,
        "wait_priority": _nonnegative_int(agent.wait_priority),
        "eligible_since": None,
    }


def _capacity_artifact_dir(agent: Agent) -> str:
    if agent.artifacts_dir:
        return agent.artifacts_dir
    agent_type, cl_name, raw_suffix = agent.identity
    suffix = raw_suffix or agent.raw_suffix or cl_name
    return f"memory://{agent_type.value}/{cl_name}/{suffix}"


def _project_name(agent: Agent) -> str:
    if agent.project_file:
        project_name = Path(agent.project_file).parent.name
        if project_name:
            return project_name
    artifacts_dir = agent.artifacts_dir
    if artifacts_dir:
        path = Path(artifacts_dir)
        try:
            return path.parents[2].name
        except IndexError:
            pass
    return ""


def _workflow_dir_name(agent: Agent) -> str:
    artifacts_dir = agent.artifacts_dir
    if artifacts_dir:
        workflow = Path(artifacts_dir).parent.name
        if workflow:
            return workflow
    if agent.workflow:
        return agent.workflow
    return "ace-run" if _is_ace_run_root(agent) or agent.is_child_row else ""


def _capacity_timestamp(agent: Agent) -> str:
    if agent.raw_suffix:
        return agent.raw_suffix
    if agent.artifacts_dir:
        return Path(agent.artifacts_dir).name
    return agent.cl_name


def _appears_as_agent(agent: Agent) -> bool:
    if agent.is_clan_container or agent.is_proc_shell:
        return False
    return agent.appears_as_agent or _is_ace_run_root(agent) or agent.is_child_row


def _capacity_record_is_live(agent: Agent) -> bool:
    return bool(agent.runner_is_live or agent.pid is not None)


def _capacity_run_started_at(agent: Agent) -> str | None:
    if agent.run_start_time is not None:
        return agent.run_start_time.isoformat()
    if agent.pid is not None and _agent_lane_bucket_counts_as_running(agent):
        started = agent.start_time
        return None if started is None else started.isoformat()
    return None


def _capacity_agent_family(agent: Agent) -> str | None:
    if agent.agent_family:
        return agent.agent_family
    if agent.parent_timestamp and not agent.agent_family_parallel:
        return agent.parent_timestamp
    return None


def _family_shell_kind(agent: Agent) -> str | None:
    if agent.is_gate:
        return "gate"
    if agent.is_monitor:
        return "monitor"
    return None


def _family_shell_id(agent: Agent) -> str | None:
    if agent.is_gate:
        return agent.gate_id
    if agent.is_monitor:
        return agent.monitor_id
    return None


def _family_shell_state(agent: Agent) -> str | None:
    if agent.is_gate:
        return agent.gate_state
    if agent.is_monitor:
        return agent.monitor_state
    return None


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _nonnegative_int(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


def _int_value(value: object) -> int | None:
    if type(value) is int:
        return value
    return None


def _positive_int(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    return None


def _text_value(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _blocker_tuple(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict(blocker) for blocker in value if isinstance(blocker, dict))


def _ordered_snapshot_waiters(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list | tuple):
        return ()
    indexed = [
        (index, dict(waiter))
        for index, waiter in enumerate(value)
        if isinstance(waiter, dict)
    ]
    indexed.sort(
        key=lambda item: (
            _positive_int(item[1].get("queue_position")) is None,
            _positive_int(item[1].get("queue_position")) or item[0] + 1,
            item[0],
        )
    )
    return tuple(waiter for _, waiter in indexed)


def _snapshot_waiter_is_parked(waiter: dict[str, Any]) -> bool:
    if waiter.get("eligible") is True:
        return False
    blockers = _blocker_tuple(waiter.get("blockers"))
    return any(blocker.get("code") != "queue-order" for blocker in blockers)


def _agent_lane_bucket_counts_as_running(agent: Agent) -> bool:
    """Return whether a top-level (non-clan) lane's own bucket reads running.

    Mirrors the "Running" branch of ``_status_counts_for_projections`` for a
    node that is not itself projected from a container (``projected_from_container``
    is always ``False`` for a plain top-level loop entry), so this must stay
    in lockstep with that function's Running-bucket condition.
    """
    return (
        agent_status_bucket(agent) == "Running"
        and agent.status not in DISMISSABLE_STATUSES
    )


def _container_is_genuinely_occupying(agent: Agent) -> bool:
    """Return whether *agent*'s own shell is live, ignoring its display status.

    A sequential family container's displayed status can be overwritten to
    mirror a terminal newest child while the container's own process is
    still running, so raw liveness -- not the mirrored status string -- is
    the fallback signal for that narrow gap. The three literal terminal
    statuses are still honored: a genuinely done or failed root has no slot
    left to hold regardless of stale pid bookkeeping.
    """
    return (
        agent.pid is not None
        and agent.run_start_time is not None
        and agent.stop_time is None
        and not agent.runner_slot_yielded
        and agent.status not in {"DONE", "FAILED", "FAILED (RETRIED)"}
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
    return _is_ace_run_root(agent) or agent.is_family_member_child


def _is_live_slot_waiter(agent: Agent) -> bool:
    return (
        _participates_in_runner_slots(agent)
        and agent.pid is not None
        and bool(agent.slot_requested_at)
        and agent.status in PRE_RUN_WAIT_STATUSES
    )


def _waiter_sort_key(
    agent: Agent,
    *,
    running_count: int,
) -> tuple[int, int, int, int, datetime, str, str]:
    # Snapshot-backed running rows use the source record timestamp as
    # ``raw_suffix``; claim-backed rows normalize the same artifact timestamp.
    return runner_slot_queue_display_key(
        running_count=running_count,
        threshold=agent.wait_runners,
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

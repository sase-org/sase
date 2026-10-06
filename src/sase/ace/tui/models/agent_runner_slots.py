"""In-memory runner-slot display context for Agents-tab rows."""

from __future__ import annotations

from collections.abc import Callable
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

from ._agent_runner_slot_capacity import (
    agent_lane_bucket_counts_as_running as _agent_lane_bucket_counts_as_running,
    blocker_tuple as _blocker_tuple,
    capacity_artifact_dir as _capacity_artifact_dir,
    capacity_record_from_agent as _capacity_record_from_agent,
    clan_container_lookup as _clan_container_lookup,
    container_is_genuinely_occupying as _container_is_genuinely_occupying,
    finite_float as _finite_float,
    int_value as _int_value,
    is_ace_run_root as _is_ace_run_root,
    is_live_slot_waiter as _is_live_slot_waiter,
    ordered_snapshot_waiters as _ordered_snapshot_waiters,
    positive_int as _positive_int,
    snapshot_waiter_is_parked as _snapshot_waiter_is_parked,
    text_value as _text_value,
    waiter_capacity_multiplier as _waiter_capacity_multiplier,
    waiter_sort_key as _waiter_sort_key,
    waiter_threshold as _waiter_threshold,
)
from ._agent_runner_slot_types import (
    RunnerCapacityHolder,
    RunnerCapacitySnapshot,
    RunnerQueueEntry,
    format_capacity_value,
    format_queue_weight_badge_value,
)
from .agent import Agent


def _memoized_pid_probe() -> Callable[[int], bool]:
    """Return a per-call memoized wrapper around the loader's PID probe."""
    from sase.ace.hooks.processes import is_process_running

    cache: dict[int, bool] = {}

    def _probe(pid: int) -> bool:
        live = cache.get(pid)
        if live is None:
            live = is_process_running(pid)
            cache[pid] = live
        return live

    return _probe


def refresh_runner_slot_context(
    agents: list[Agent],
    *,
    effective_limit: float | None = None,
    capacity_agents: list[Agent] | None = None,
    active_holds: tuple[dict[str, Any], ...] = (),
    is_pid_live: Callable[[int], bool] | None = None,
) -> RunnerCapacitySnapshot:
    """Attach global runner-capacity context from the loaded snapshot.

    The loader verifies the PIDs it filters on, and this adapter verifies
    the rest: rows the loader kept without probing (terminal loaded
    statuses and session-turn rows) re-probe here so a stale PID alone
    never becomes a ghost capacity claim. Deriving this context
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

    probe = is_pid_live if is_pid_live is not None else _memoized_pid_probe()
    capacity_source = agents if capacity_agents is None else capacity_agents
    parsed_artifact_paths: dict[str, Any] = {}
    clan_containers = _clan_container_lookup(capacity_source)
    capacity_records = tuple(
        _capacity_record_from_agent(
            agent,
            parsed_artifact_paths,
            clan_containers=clan_containers,
            is_pid_live=probe,
        )
        for agent in capacity_source
    )
    raw_snapshot = runner_capacity_snapshot_from_capacity_records(
        capacity_records,
        effective_limit=float(effective_limit),
        active_holds=active_holds,
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
    from ._agent_clan import apply_clan_container_status, clan_members

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
                wait_runners_explicit=(
                    agent.wait_runners_explicit or agent.queue_capacity_explicit
                ),
                capacity_multiplier=agent.queue_capacity_multiplier,
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
            agent.runner_admission_limit = None
            agent.runner_slot_queue_position = queue_positions.get(id(agent))
            agent.runner_slot_queue_size = queue_size
            agent.runner_capacity_blockers = ()
        else:
            agent.runner_slots_in_use = None
            agent.runner_occupied_capacity = None
            agent.runner_effective_limit = None
            agent.runner_admission_limit = None
            agent.runner_slot_queue_position = None
            agent.runner_slot_queue_size = None
            agent.runner_capacity_blockers = ()
        if agent.is_clan_container:
            apply_clan_container_status(
                agent,
                clan_members(agent),
                fallback=runner_slot_display_status(
                    agent.status,
                    slot_queued=False,
                ),
            )
        else:
            slot_queued = id(agent) in queue_positions
            if not slot_queued:
                source = agent.wait_display_source
                slot_queued = source is not None and id(source) in queue_positions
            agent.status = runner_slot_display_status(
                agent.status,
                slot_queued=slot_queued,
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
    from ._agent_clan import apply_clan_container_status, clan_members

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
    queue_admission_limits: dict[int, float | None] = {}
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
            queue_admission_limits[id(display_agent)] = _finite_float(
                waiter.get("admission_limit")
            )
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
                threshold=_waiter_threshold(waiter),
                wait_runners_explicit=(
                    agent.wait_runners_explicit or agent.queue_capacity_explicit
                ),
                capacity_multiplier=(
                    _waiter_capacity_multiplier(waiter)
                    or agent.queue_capacity_multiplier
                ),
                priority=normalize_wait_priority(waiter.get("priority")),
                slot_requested_at=_text_value(waiter.get("slot_requested_at")),
                status=(
                    display_agent.status if display_agent is not None else agent.status
                ),
                requested_weight=_requested_weight(waiter.get("requested_weight")),
                requested_weight_explicit=_requested_weight_explicit(
                    waiter.get("requested_weight"),
                    waiter.get("queue_weight_explicit"),
                ),
                occupied_capacity=occupied_capacity,
                admission_limit=_finite_float(waiter.get("admission_limit")),
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
            agent.runner_admission_limit = queue_admission_limits.get(id(agent))
            agent.runner_slot_queue_position = queue_positions.get(id(agent))
            agent.runner_slot_queue_size = queue_size
            agent.runner_capacity_blockers = queue_blockers.get(id(agent), ())
        else:
            agent.runner_slots_in_use = None
            agent.runner_occupied_capacity = occupied_capacity
            agent.runner_effective_limit = effective_limit
            agent.runner_admission_limit = None
            agent.runner_slot_queue_position = None
            agent.runner_slot_queue_size = None
            agent.runner_capacity_blockers = ()
        if agent.is_clan_container:
            apply_clan_container_status(
                agent,
                clan_members(agent),
                fallback=runner_slot_display_status(
                    agent.status,
                    slot_queued=False,
                ),
            )
        else:
            slot_queued = id(agent) in queue_positions
            if not slot_queued:
                source = agent.wait_display_source
                slot_queued = source is not None and id(source) in queue_positions
            agent.status = runner_slot_display_status(
                agent.status,
                slot_queued=slot_queued,
            )

    return RunnerCapacitySnapshot(
        effective_limit=effective_limit,
        slots_in_use=running_count,
        queued_count=queue_size,
        queue=tuple(queue_entries),
        occupied_capacity=occupied_capacity,
        holders=_capacity_holders(
            raw_snapshot.get("claims", ()), source_agent_by_artifact_dir
        ),
    )


def _capacity_holders(
    claims: object,
    source_agent_by_artifact_dir: dict[str, Agent],
) -> tuple[RunnerCapacityHolder, ...]:
    """Build ordered claim-holder entries for the load gauge tooltip."""
    if not isinstance(claims, list | tuple):
        return ()
    holders: list[RunnerCapacityHolder] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        occupiers = _claim_occupiers(claim, source_agent_by_artifact_dir)
        if not occupiers:
            continue
        first = occupiers[0]
        label = first.presented_agent_name or first.agent_name or first.cl_name or ""
        if not label:
            continue
        weight = _finite_float(claim.get("occupied_capacity"))
        kind: str | None = None
        if any(agent.is_monitor for agent in occupiers):
            kind = "monitor"
        elif any(agent.is_gate for agent in occupiers):
            kind = "gate"
        holders.append(
            RunnerCapacityHolder(
                label=label,
                weight=weight if weight is not None else 0.0,
                kind=kind,
            )
        )
    holders.sort(key=lambda holder: (-holder.weight, holder.label))
    return tuple(holders)


def _claim_occupiers(
    claim: dict[str, Any],
    source_agent_by_artifact_dir: dict[str, Agent],
) -> list[Agent]:
    """Resolve the agent rows backing one Rust capacity claim."""
    occupiers: list[Agent] = []
    seen: set[int] = set()
    candidates: list[str] = []
    owner_dir = _text_value(claim.get("owner_artifact_dir"))
    if owner_dir is not None:
        candidates.append(owner_dir)
    artifact_dirs = claim.get("artifact_dirs")
    if isinstance(artifact_dirs, list | tuple):
        for entry in artifact_dirs:
            if isinstance(entry, str) and entry not in candidates:
                candidates.append(entry)
    for artifact_dir in candidates:
        agent = source_agent_by_artifact_dir.get(artifact_dir)
        if agent is not None and id(agent) not in seen:
            seen.add(id(agent))
            occupiers.append(agent)
    return occupiers


def _requested_weight(value: object) -> float:
    weight = _finite_float(value)
    return DEFAULT_QUEUE_WEIGHT if weight is None else weight


def _requested_weight_explicit(value: object, explicit_flag: object) -> bool:
    weight = _finite_float(value)
    if weight is None:
        return False
    return explicit_flag is True or weight == 0.0


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


__all__ = [
    "RunnerCapacitySnapshot",
    "RunnerQueueEntry",
    "refresh_runner_slot_context",
]

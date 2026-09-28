"""Pure status/count aggregation for rootless agent clans."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.agent.status_buckets import (
    QUEUED_STATUS_BUCKET,
    aggregate_agent_group_effective_status,
    aggregate_agent_group_status,
    agent_is_asking,
    agent_status_bucket,
    clan_status_source_index,
    status_bucket_for_values,
)

if TYPE_CHECKING:
    from .agent import Agent
    from .agent_types import AgentType

from .agent_status import DISMISSABLE_STATUSES
from .agent_session_members import (
    ConcreteAgentStatus,
    agent_row_is_in_flight,
    concrete_agent_statuses,
    current_agent_session_turn_row,
    is_sequential_agent_session_container,
)
from .agent_nodes import is_agents_tab_agent_node
from .agent_time import wait_display_agent

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


_TURN_STATUS_PRESENTATION_FIELDS: tuple[str, ...] = (
    "monitor_start_status",
    "monitor_stop_status",
    "monitor_state",
    "gate_start_status",
    "gate_stop_status",
    "gate_state",
    "gate_accent",
    "gate_execution_active",
    "gate_finalize_proc_id",
)


def aggregate_clan_status(statuses: Iterable[str]) -> str | None:
    """Return the shared aggregate agent-group display status."""
    return aggregate_agent_group_status(statuses)


def _copy_turn_status_presentation(target: Agent, source: Agent | None) -> None:
    """Copy or clear the monitor/gate fields that style a clan status label."""
    for field_name in _TURN_STATUS_PRESENTATION_FIELDS:
        if source is None and field_name == "gate_execution_active":
            setattr(target, field_name, False)
            continue
        setattr(
            target,
            field_name,
            None if source is None else getattr(source, field_name),
        )


def status_display_agent(agent: Agent) -> Agent:
    """Return the row whose status word *agent* presents.

    A clan container with exactly one running member mirrors that member's
    render-time status overlays through ``status_display_source``; every
    other row presents its own status.
    """
    return agent.status_display_source or agent


def apply_clan_container_status(
    container: Agent,
    members: Iterable[Agent],
    *,
    fallback: str,
) -> None:
    """Project a clan container's status from its direct members.

    Members are deduplicated by ``identity``, keeping the first occurrence.
    Aggregation uses :func:`aggregate_agent_group_effective_status` so a
    row-level bucket override (for example ``TESTED`` with bucket ``Done``)
    participates in the existing precedence ladder.

    When a clan has exactly one running member (``STARTING`` included) and
    the precedence-ladder aggregate bucket is ``Running``, the clan shows
    that member's status exactly: the stored label, the effective bucket
    (``Running`` or ``Starting``), and the monitor/gate presentation fields.
    The render-time overlays of the status word (``FINALIZING`` and the
    ``RETRYING (Ns)`` countdown) resolve through ``status_display_source``.
    A member that needs the user (asking, awaiting plan review, or failed)
    still outranks the running member via the ladder aggregate.

    When the aggregate bucket is Queued and exactly one unique member is
    queued, the clan attaches that member through ``wait_display_source``
    (dereferencing a sequential-agent-session root to its queued turn) so list-row
    and CLAN ``Status:`` extras can show the member's admission rank. Any
    other aggregate, including two queued members, clears the pointer so
    repeated projections cannot leave a stale rank after a companion queues
    or the lone waiter starts.

    Any non-mirrored aggregate, including an empty member list (which
    falls back to *fallback*), clears ``status_bucket``,
    ``status_display_source``, and those presentation fields. Clearing on
    every call keeps repeated projections (tree projection and both
    runner-slot refresh paths in ``agent_runner_slots.py``) idempotent after
    the source member changes or a second active member appears.
    """
    unique_members: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for member in members:
        if member.identity in seen:
            continue
        seen.add(member.identity)
        unique_members.append(member)

    entries = tuple(
        (member.status, agent_status_bucket(member)) for member in unique_members
    )
    aggregate = aggregate_agent_group_effective_status(entries)
    aggregate_bucket = (
        None if aggregate is None else status_bucket_for_values(aggregate)
    )
    source_index = clan_status_source_index(entries)
    source = unique_members[source_index] if source_index is not None else None
    if source is not None:
        container.status = source.status
        container.status_bucket = agent_status_bucket(source)
        _copy_turn_status_presentation(container, source)
        container.status_display_source = source
    else:
        container.status = fallback if aggregate is None else aggregate
        container.status_bucket = None
        _copy_turn_status_presentation(container, None)
        container.status_display_source = None
    _set_clan_queued_wait_display_source(container, unique_members, aggregate_bucket)


def _set_clan_queued_wait_display_source(
    container: Agent,
    unique_members: list[Agent],
    aggregate_bucket: str | None,
) -> None:
    """Attach or clear the lone queued member's wait-display row."""
    queued_members = [
        member
        for member in unique_members
        if agent_status_bucket(member) == QUEUED_STATUS_BUCKET
    ]
    if aggregate_bucket == QUEUED_STATUS_BUCKET and len(queued_members) == 1:
        container.wait_display_source = wait_display_agent(queued_members[0])
        return
    container.wait_display_source = None


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
            and is_agents_tab_agent_node(child)
            and child.presented_clan_reference_name() == clan_reference
            and child.agent_clan_generation == agent.agent_clan_generation
        )
    # Legacy archives project parallel-agent-session metadata into a clan at the wire
    # boundary, but directly constructed compatibility fixtures may still carry
    # only the old marker.
    if not agent.agent_session_parallel:
        return ()
    return tuple(
        child
        for child in agent.runtime_children
        if child is not agent and child.agent_session_parallel
    )


def clan_running_lane_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return the clan's own in-flight member rows, one per running lane.

    Each row is a direct clan member, never a turn nested inside one of the
    clan's sequential agent sessions: a session lane is represented by the agent session
    row itself so it contributes the session total rather than the runtime of
    whichever turn is currently executing. A session lane counts as in
    flight while any of its turns is executing, which outlives the agent session
    root row's own status and ``stop_time``. Nested clan containers are not
    clan members (matching :func:`clan_members` and
    ``_lane_summary_projections``), so they are not walked.
    """
    if not agent.is_clan_container:
        return ()
    rows: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for member in clan_members(agent):
        if current_agent_session_turn_row(
            member
        ) is None and not agent_row_is_in_flight(member):
            continue
        if member.identity in seen:
            continue
        seen.add(member.identity)
        rows.append(member)
    return tuple(rows)


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
        bucket = agent_status_bucket(member)
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


def sase_agent_status_counts(
    agents: Iterable[Agent],
    unread_ids: Collection[tuple[AgentType, str, str | None]],
) -> _AgentSummaryStatusCounts:
    """Count deduplicated Agents-tab agent nodes by status."""
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
        if agent_is_asking(projected_agent.status) or bucket == "Stopped":
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
    if not is_agents_tab_agent_node(agent):
        return ()
    return (
        _ProjectedSummaryAgent(
            status=ConcreteAgentStatus(
                agent=agent,
                bucket=agent_status_bucket(agent),
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
        if agent.is_clan_container or agent.agent_session_parallel
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
            # Preserve the legacy parallel-agent-session projection: only the loaded
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
        projected_from_container = is_sequential_agent_session_container(agent) or any(
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
    "sase_agent_status_counts",
    "agent_status_projections",
    "agent_summary_status_counts",
    "aggregate_clan_status",
    "apply_clan_container_status",
    "clan_running_lane_rows",
    "clan_member_status_priority",
    "clan_member_counts",
    "clan_members",
    "status_display_agent",
]

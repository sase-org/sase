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
    status_bucket_for_values,
)

if TYPE_CHECKING:
    from .agent import Agent
    from .agent_types import AgentType

from .agent_status import DISMISSABLE_STATUSES
from .agent_family_members import (
    ConcreteAgentStatus,
    agent_row_is_in_flight,
    concrete_agent_statuses,
    current_family_shell_row,
    is_sequential_family_container,
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


_SHELL_STATUS_PRESENTATION_FIELDS: tuple[str, ...] = (
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

_CLAN_INHERITABLE_STATUS_BUCKETS: frozenset[str] = frozenset(
    {"Failed", "Running", "Stopped"}
)
_CLAN_IGNORED_MEMBER_STATUS_BUCKETS: frozenset[str] = frozenset(
    {QUEUED_STATUS_BUCKET, "Waiting", "Done"}
)


def aggregate_clan_status(statuses: Iterable[str]) -> str | None:
    """Return the shared aggregate agent-group display status."""
    return aggregate_agent_group_status(statuses)


def _copy_shell_status_presentation(target: Agent, source: Agent | None) -> None:
    """Copy or clear the monitor/gate fields that style a clan status label."""
    for field_name in _SHELL_STATUS_PRESENTATION_FIELDS:
        if source is None and field_name == "gate_execution_active":
            setattr(target, field_name, False)
            continue
        setattr(
            target,
            field_name,
            None if source is None else getattr(source, field_name),
        )


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

    When exactly one member is outside the queued/waiting/done buckets and
    its effective bucket is the canonical aggregate bucket, the clan can
    inherit that member's refined display label, effective bucket, and the
    monitor/gate presentation fields. This preserves authored shell labels
    such as ``TESTING``/``TESTED`` and gate labels while keeping the
    aggregate's outcome bucket, ``BY_STATUS`` grouping, member ordering,
    count chips, and summary counts unchanged. ``Starting`` is a competing
    member, not an inheritable source, so a lone ``STARTING`` member still
    leaves the clan at ``RUNNING``. Queued members remain ignored for that
    Failed/Running/Stopped label mirror.

    When the aggregate bucket is Queued and exactly one unique member is
    queued, the clan attaches that member through ``wait_display_source``
    (dereferencing a sequential-family root to its queued shell) so list-row
    and CLAN ``Status:`` extras can show the member's admission rank. Any
    other aggregate, including two queued members, clears the pointer so
    repeated projections cannot leave a stale rank after a companion queues
    or the lone waiter starts.

    Any non-inheritable aggregate, including an empty member list (which
    falls back to *fallback*), clears ``status_bucket`` and those presentation
    fields so repeated projections stay idempotent after the source member
    changes or a second active member appears.
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
    relevant_members = [
        member
        for member in unique_members
        if agent_status_bucket(member) not in _CLAN_IGNORED_MEMBER_STATUS_BUCKETS
    ]
    source = relevant_members[0] if len(relevant_members) == 1 else None
    source_bucket = None if source is None else agent_status_bucket(source)
    if (
        source is not None
        and source_bucket in _CLAN_INHERITABLE_STATUS_BUCKETS
        and source_bucket == aggregate_bucket
    ):
        container.status = source.status
        container.status_bucket = source_bucket
        _copy_shell_status_presentation(container, source)
    else:
        container.status = fallback if aggregate is None else aggregate
        container.status_bucket = None
        _copy_shell_status_presentation(container, None)
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
    # Legacy archives project parallel-family metadata into a clan at the wire
    # boundary, but directly constructed compatibility fixtures may still carry
    # only the old marker.
    if not agent.agent_family_parallel:
        return ()
    return tuple(
        child
        for child in agent.runtime_children
        if child is not agent and child.agent_family_parallel
    )


def clan_running_lane_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return the clan's own in-flight member rows, one per running lane.

    Each row is a direct clan member, never a shell nested inside one of the
    clan's sequential families: a family lane is represented by the family
    row itself so it contributes the family total rather than the runtime of
    whichever shell is currently executing. A family lane counts as in
    flight while any of its shells is executing, which outlives the family
    root row's own status and ``stop_time``. Nested clan containers are not
    clan members (matching :func:`clan_members` and
    ``_lane_summary_projections``), so they are not walked.
    """
    if not agent.is_clan_container:
        return ()
    rows: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for member in clan_members(agent):
        if current_family_shell_row(member) is None and not agent_row_is_in_flight(
            member
        ):
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
    "sase_agent_status_counts",
    "agent_status_projections",
    "agent_summary_status_counts",
    "aggregate_clan_status",
    "apply_clan_container_status",
    "clan_running_lane_rows",
    "clan_member_status_priority",
    "clan_member_counts",
    "clan_members",
]

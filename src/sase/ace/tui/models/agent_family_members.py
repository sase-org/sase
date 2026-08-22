"""Pure in-memory projection of concrete agents and sequential families."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sase.agent.status_buckets import (
    agent_is_active,
    agent_status_bucket,
)
from sase.monitor_state import monitor_state_is_terminal
from .agent import Agent, AgentType


#: Buckets that claim an agent process is still executing.
_IN_FLIGHT_BUCKETS: frozenset[str] = frozenset({"Running", "Starting"})


@dataclass(frozen=True, slots=True)
class ConcreteAgentStatus:
    """One concrete agent row and its presentation-side status bucket."""

    agent: Agent
    bucket: str


def agent_row_is_in_flight(agent: Agent) -> bool:
    """Return whether one row represents work that is still executing."""
    if agent.is_monitor:
        return agent.monitor_state == "running" and agent.stop_time is None
    return agent_is_active(agent.status) and agent.stop_time is None


def monitor_row_is_settled(row: Agent) -> bool:
    """Return whether one monitor row belongs in the settled (grey) lane.

    A ``stop_time`` alone settles a row even when its ``monitor_state`` was
    never reconciled to a terminal value: the family member row is over
    either way, and the badge partition would otherwise strand the row in
    neither lane. Unknown/missing ``monitor_state`` with no ``stop_time``
    is not settled, matching :func:`monitor_state_is_terminal`'s doctrine
    that a monitor which has not (yet) reported never reads as finished.

    Shared by the ``⚙N`` lane counts and the per-row gear style so a grey
    gear on a row and the grey count it feeds can never drift apart.
    """
    return monitor_state_is_terminal(row.monitor_state) or row.stop_time is not None


@dataclass(frozen=True, slots=True)
class MonitorLaneCounts:
    """Running vs. settled monitor counts for one container row's subtree."""

    running: int = 0
    settled: int = 0


NO_MONITOR_LANES = MonitorLaneCounts()


class _MonitorLaneTally:
    """Shared traversal state for partitioning monitor rows into two lanes.

    ``Agent`` is mutable and unhashable, and ``runtime_children`` /
    ``followup_agents`` overlap, so traversal cycle-guards on ``id(row)``
    while the count itself dedupes by ``row.identity``. Every distinct
    monitor row increments exactly one lane, never both, never neither.
    """

    def __init__(self) -> None:
        self._visited_ids: set[int] = set()
        self._seen_identities: set[tuple[AgentType, str, str | None]] = set()
        self.running = 0
        self.settled = 0

    def visit(self, row: Agent) -> None:
        if id(row) in self._visited_ids:
            return
        self._visited_ids.add(id(row))
        if row.identity not in self._seen_identities:
            self._seen_identities.add(row.identity)
            if row.is_monitor:
                if monitor_row_is_settled(row):
                    self.settled += 1
                else:
                    self.running += 1
        for child in (*row.runtime_children, *row.followup_agents):
            self.visit(child)

    def counts(self) -> MonitorLaneCounts:
        return MonitorLaneCounts(running=self.running, settled=self.settled)


def monitor_lane_counts(agent: Agent) -> MonitorLaneCounts:
    """Partition monitor shells beneath one container row into two lanes.

    The container row itself is excluded: only its ``runtime_children`` and
    ``followup_agents`` are visited.
    """
    tally = _MonitorLaneTally()
    for child in (*agent.runtime_children, *agent.followup_agents):
        tally.visit(child)
    return tally.counts()


def panel_monitor_lane_counts(rows: Iterable[Agent]) -> MonitorLaneCounts:
    """Partition monitor rows reachable from a whole panel's top-level rows.

    Differs from :func:`monitor_lane_counts` in two ways, both required to
    make a panel-level total rather than a per-container one: each row in
    ``rows`` is itself visited rather than excluded, so a top-level row that
    is itself a monitor is counted (a monitor nests under its starter today,
    so this should never fire, but it keeps the partition total honest
    instead of silently dropping a row if that projection ever changes); and
    dedupe spans all roots in one shared tally rather than one tally per
    root, so a monitor reachable from two different top-level rows (a clan
    container and a member family can both reach the same monitor) is
    counted exactly once.
    """
    tally = _MonitorLaneTally()
    for row in rows:
        tally.visit(row)
    return tally.counts()


def is_sequential_family_container(agent: Agent) -> bool:
    """Return whether ``agent`` represents a loaded sequential family.

    The second branch preserves compatibility with clan projections whose
    direct family root may predate the explicit ``agent_family_role`` marker
    but still owns loaded, serial family-member children. A monitor child
    alone does not promote its starter to a container.
    """
    if agent.agent_family_parallel:
        return False
    if agent.is_family_container_row:
        return True
    return bool(
        agent.agent_family
        and any(
            child.is_family_member_child
            and not child.agent_family_parallel
            and not child.is_monitor
            for child in (*agent.runtime_children, *agent.followup_agents)
        )
    )


def _is_workflow_aggregate_row(agent: Agent) -> bool:
    """Return whether ``agent`` owns workflow-step presentation rows."""
    if agent.is_workflow_child:
        return False
    return agent.agent_type == AgentType.WORKFLOW or any(
        child.is_workflow_step_child
        for child in (*agent.runtime_children, *agent.followup_agents)
    )


def _shell_links(row: Agent) -> tuple[Agent, ...]:
    """Return both loaded child collections in their already-normalized order."""
    return (*row.runtime_children, *row.followup_agents)


def _is_excluded_family_shell(row: Agent) -> bool:
    """Return whether *row* is scaffolding rather than a concrete family shell."""
    return row.is_synthetic_planner or row.agent_family_parallel


def _concrete_agent_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return concrete agents represented by one non-container row.

    A loaded workflow aggregate is represented by its real agent-type steps.
    Python/bash steps never count as agents.  When no agent step is loaded,
    the aggregate row remains the compatibility fallback and counts once.
    """
    if agent.is_workflow_step_child:
        if (
            agent.step_type == "agent"
            and not agent.is_synthetic_planner
            and not agent.agent_family_parallel
            and not agent.is_monitor
        ):
            return (agent,)
        return ()
    if agent.is_monitor:
        return ()

    if _is_workflow_aggregate_row(agent):
        agent_steps = _dedupe_rows(
            tuple(
                child
                for child in (*agent.runtime_children, *agent.followup_agents)
                if child.is_workflow_step_child
                and child.step_type == "agent"
                and not child.is_synthetic_planner
                and not child.agent_family_parallel
                and not child.is_monitor
            )
        )
        if agent_steps:
            return agent_steps
    return (agent,)


def _family_shell_anchors(agent: Agent) -> tuple[Agent, ...]:
    """Return the ordered agent-shell chain before nested monitors are inserted."""
    planner = _concrete_planner_child(agent)
    candidates: list[Agent] = []
    if planner is not None:
        candidates.append(planner)
    elif _root_represents_member(agent):
        candidates.append(agent)

    candidates.extend(_concrete_continuations(agent.runtime_children, planner))
    candidates.extend(_concrete_continuations(agent.followup_agents, planner))
    return _dedupe_by_identity(candidates)


def _expand_nested_monitor_shells(
    container: Agent,
    anchors: Sequence[Agent],
) -> tuple[Agent, ...]:
    """Insert nested monitor shells immediately after their causal starter.

    Traverses both ``runtime_children`` and ``followup_agents`` because loaded
    shapes expose overlapping but not always identical links. Dedupes by
    durable row identity, cycle-guards by object identity, and keeps each
    collection's already-normalized order rather than sorting by timestamp.
    Later agent-shell continuations stay in the anchor sequence; their
    monitors are not stolen while walking an earlier starter.
    """
    result: list[Agent] = []
    walked_ids: set[int] = set()
    emitted: set[tuple[AgentType, str, str | None]] = set()
    anchor_identities = {row.identity for row in anchors}

    def emit(row: Agent) -> None:
        if id(row) in walked_ids:
            return
        walked_ids.add(id(row))
        if row.identity in emitted or _is_excluded_family_shell(row):
            return
        emitted.add(row.identity)
        result.append(row)
        walk_monitors(row)

    def walk_monitors(row: Agent) -> None:
        for child in _shell_links(row):
            child_id = id(child)
            if child_id in walked_ids:
                continue
            if child.identity in emitted:
                walked_ids.add(child_id)
                continue
            if _is_excluded_family_shell(child):
                walked_ids.add(child_id)
                continue
            if child.is_monitor:
                emit(child)
                continue
            if child.identity in anchor_identities:
                continue
            walked_ids.add(child_id)
            walk_monitors(child)

    if container.identity not in anchor_identities:
        walk_monitors(container)
    for anchor in anchors:
        emit(anchor)
    return tuple(result)


def concrete_family_shell_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return ordered concrete family shells: agent shells and nested monitors.

    Plan workflow roots are aggregate rows. When their concrete main agent
    step is loaded, that step owns the planner phase; otherwise the root stays
    as the compatibility fallback. Rename-on-attach roots remain the first
    real shell for families that do not have a concrete planner step.

    A monitor nested under any family shell is included immediately after its
    causal starter. Synthetic planners, non-agent workflow steps, and
    parallel-family rows stay excluded. The walk is a pure in-memory
    projection: linear in the loaded family subtree, cycle-safe, and
    identity-deduped.
    """
    return _expand_nested_monitor_shells(agent, _family_shell_anchors(agent))


def concrete_family_member_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return ordered concrete agent shells represented by a family container.

    Monitor proc shells are omitted so agent, runner, status, and completion
    counts stay agent-only. See :func:`concrete_family_shell_rows` for the
    roster sequence that includes them.
    """
    return tuple(row for row in concrete_family_shell_rows(agent) if not row.is_monitor)


def family_roster_container(agent: Agent) -> Agent | None:
    """Return the container row whose FAMILY SHELLS roster lists ``agent``.

    Container rows render their own roster and are never members of another
    row's roster, so they resolve to ``None``.
    """
    if agent.is_family_container_row:
        return None
    container = agent.family_container
    if container is None or container is agent:
        return None
    return container


def _settled_member_bucket(member: Agent) -> str:
    """Return the effective bucket for one non-final sequential-family member."""
    bucket = agent_status_bucket(member)
    if bucket not in _IN_FLIGHT_BUCKETS or agent_row_is_in_flight(member):
        return bucket
    return "Done"


def family_member_status_buckets(members: Sequence[Agent]) -> tuple[str, ...]:
    """Return effective buckets for an ordered sequential family.

    A family advances one member at a time: a successor is attached only once
    its predecessor has finished, so a non-final member that is no longer
    executing has handed the work off and is settled.  Sticky handoff labels
    (``TALE APPROVED``), transient post-answer labels (``ANSWERED``), and every
    status that falls through ``status_bucket_for_values``'s ``Running``
    default would otherwise keep a finished predecessor counted as running.  A
    non-final member that *is* still executing keeps its bucket: a member
    attached to a running parent is created as ``WAITING``, so the running
    predecessor is the real state of the lane.  The final member always keeps
    the global bucket.
    """
    final_index = len(members) - 1
    return tuple(
        _settled_member_bucket(member)
        if index < final_index
        else agent_status_bucket(member)
        for index, member in enumerate(members)
    )


def concrete_agent_statuses(agent: Agent) -> tuple[ConcreteAgentStatus, ...]:
    """Project one non-clan unit into concrete rows and effective buckets."""
    if is_sequential_family_container(agent):
        rows = concrete_family_member_rows(agent)
        buckets = family_member_status_buckets(rows)
    else:
        rows = _concrete_agent_rows(agent)
        buckets = tuple(agent_status_bucket(row) for row in rows)
    pairs = tuple(
        (row, bucket)
        for row, bucket in zip(rows, buckets, strict=True)
        if not row.is_monitor
    )
    return tuple(ConcreteAgentStatus(agent=row, bucket=bucket) for row, bucket in pairs)


def _concrete_planner_child(agent: Agent) -> Agent | None:
    if not agent.is_plan_family_root_entry:
        return None
    return next(
        (
            child
            for child in agent.runtime_children
            if child.is_workflow_step_child
            and child.step_type == "agent"
            and child.parent_step_index is None
            and not child.is_synthetic_planner
            and not child.agent_family_parallel
        ),
        None,
    )


def _root_represents_member(agent: Agent) -> bool:
    if agent.is_plan_family_root_entry:
        return True
    family_name = agent.agent_family or agent.family_reference_name()
    return not bool(
        agent.agent_name and family_name and agent.agent_name == family_name
    )


def _concrete_continuations(
    rows: Sequence[Agent],
    planner: Agent | None,
) -> tuple[Agent, ...]:
    return tuple(
        row
        for row in rows
        if row is not planner
        and not row.is_workflow_step_child
        and not row.is_synthetic_planner
        and not row.agent_family_parallel
        and not row.is_monitor
    )


def _dedupe_rows(rows: Sequence[Agent]) -> tuple[Agent, ...]:
    ordered: list[Agent] = []
    seen: set[int] = set()
    for row in rows:
        object_identity = id(row)
        if object_identity in seen:
            continue
        seen.add(object_identity)
        ordered.append(row)
    return tuple(ordered)


def _dedupe_by_identity(rows: Sequence[Agent]) -> tuple[Agent, ...]:
    ordered: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for row in rows:
        if row.identity in seen:
            continue
        seen.add(row.identity)
        ordered.append(row)
    return tuple(ordered)


__all__ = [
    "ConcreteAgentStatus",
    "MonitorLaneCounts",
    "NO_MONITOR_LANES",
    "agent_row_is_in_flight",
    "concrete_agent_statuses",
    "concrete_family_member_rows",
    "concrete_family_shell_rows",
    "family_member_status_buckets",
    "family_roster_container",
    "is_sequential_family_container",
    "monitor_lane_counts",
    "monitor_row_is_settled",
    "panel_monitor_lane_counts",
]

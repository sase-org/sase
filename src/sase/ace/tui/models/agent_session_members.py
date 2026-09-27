"""Pure in-memory projection of concrete agents and sequential agent sessions."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sase.agent.status_buckets import (
    agent_is_active,
    agent_status_bucket,
)
from sase.gate_turn.state import gate_state_is_terminal
from sase.monitor_state import monitor_lane_status_bucket, monitor_state_is_terminal
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
    if agent.is_gate:
        return (
            agent.gate_state == "settling" or agent.gate_execution_active
        ) and agent.stop_time is None
    if agent.is_monitor:
        return agent.monitor_state == "running" and agent.stop_time is None
    return agent_is_active(agent.status) and agent.stop_time is None


def monitor_row_is_settled(row: Agent) -> bool:
    """Return whether one monitor row belongs in the settled (grey) lane.

    A ``stop_time`` alone settles a row even when its ``monitor_state`` was
    never reconciled to a terminal value: the session member row is over
    either way, and the badge partition would otherwise strand the row in
    neither lane. Unknown/missing ``monitor_state`` with no ``stop_time``
    is not settled, matching :func:`monitor_state_is_terminal`'s doctrine
    that a monitor which has not (yet) reported never reads as finished.

    Shared by the ``⚙N`` lane counts and the per-row gear style so a grey
    gear on a row and the grey count it feeds can never drift apart.
    """
    return monitor_state_is_terminal(row.monitor_state) or row.stop_time is not None


def gate_row_is_settled(row: Agent) -> bool:
    """Return whether one gate row belongs in the settled (grey) lane."""
    return gate_state_is_terminal(row.gate_state) or row.stop_time is not None


@dataclass(frozen=True, slots=True)
class _MonitorLaneCounts:
    """Running vs. settled monitor counts for one container row's subtree."""

    running: int = 0
    settled: int = 0


NO_MONITOR_LANES = _MonitorLaneCounts()


@dataclass(frozen=True, slots=True)
class _GateLaneCounts:
    """Pending/running vs. settled gate counts for one container row's subtree."""

    running: int = 0
    settled: int = 0
    failed: int = 0


NO_GATE_LANES = _GateLaneCounts()


@dataclass(frozen=True, slots=True)
class TurnLaneCounts:
    """Per-kind turn lane counts for one container row's subtree."""

    monitor: _MonitorLaneCounts = NO_MONITOR_LANES
    gate: _GateLaneCounts = NO_GATE_LANES


NO_TURN_LANES = TurnLaneCounts()


def row_is_agent_session_turn(row: Agent) -> bool:
    """Return whether *row* is a non-agent session turn."""
    return row.is_monitor or row.is_gate


class _TurnLaneTally:
    """Shared traversal state for partitioning turn rows into two lanes.

    ``Agent`` is mutable and unhashable, and ``runtime_children`` /
    ``followup_agents`` overlap, so traversal cycle-guards on ``id(row)``
    while the count itself dedupes by ``row.identity``. Every distinct
    turn row increments exactly one lane, never both, never neither.
    """

    def __init__(self) -> None:
        self._visited_ids: set[int] = set()
        self._seen_identities: set[tuple[AgentType, str, str | None]] = set()
        self.monitor_running = 0
        self.monitor_settled = 0
        self.gate_running = 0
        self.gate_settled = 0
        self.gate_failed = 0

    def visit(self, row: Agent) -> None:
        if id(row) in self._visited_ids:
            return
        self._visited_ids.add(id(row))
        if row.identity not in self._seen_identities:
            self._seen_identities.add(row.identity)
            if row.is_monitor:
                if monitor_row_is_settled(row):
                    self.monitor_settled += 1
                else:
                    self.monitor_running += 1
            elif row.is_gate:
                if row.gate_state in {"failed", "timeout", "lost"}:
                    self.gate_failed += 1
                elif gate_row_is_settled(row):
                    self.gate_settled += 1
                else:
                    self.gate_running += 1
        for child in (*row.runtime_children, *row.followup_agents):
            self.visit(child)

    def turn_counts(self) -> TurnLaneCounts:
        return TurnLaneCounts(
            monitor=_MonitorLaneCounts(
                running=self.monitor_running,
                settled=self.monitor_settled,
            ),
            gate=_GateLaneCounts(
                running=self.gate_running,
                settled=self.gate_settled,
                failed=self.gate_failed,
            ),
        )

    def counts(self) -> _MonitorLaneCounts:
        return self.turn_counts().monitor


def turn_lane_counts(agent: Agent) -> TurnLaneCounts:
    """Partition monitor and gate turns beneath one container row."""
    tally = _TurnLaneTally()
    for child in (*agent.runtime_children, *agent.followup_agents):
        tally.visit(child)
    return tally.turn_counts()


def panel_turn_lane_counts(rows: Iterable[Agent]) -> TurnLaneCounts:
    """Partition turn rows reachable from a whole panel's top-level rows.

    Differs from :func:`turn_lane_counts` in two ways, both required to
    make a panel-level total rather than a per-container one: each row in
    ``rows`` is itself visited rather than excluded, so a top-level row that
    is itself a turn is counted (a turn nests under its starter today,
    so this should never fire, but it keeps the partition total honest
    instead of silently dropping a row if that projection ever changes); and
    dedupe spans all roots in one shared tally rather than one tally per
    root, so a turn reachable from two different top-level rows (a clan
    container and a member agent session can both reach the same turn) is
    counted exactly once.
    """
    tally = _TurnLaneTally()
    for row in rows:
        tally.visit(row)
    return tally.turn_counts()


def is_sequential_agent_session_container(agent: Agent) -> bool:
    """Return whether ``agent`` represents a loaded sequential agent session.

    The second branch preserves compatibility with clan projections whose
    direct session root may predate the explicit ``agent_session_role`` marker
    but still owns loaded, serial session-member children. A monitor child
    alone does not promote its starter to a container.
    """
    if agent.agent_session_parallel:
        return False
    if agent.is_agent_session_container_row:
        return True
    return bool(
        agent.agent_session
        and any(
            child.is_agent_session_member_child
            and not child.agent_session_parallel
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


def _turn_links(row: Agent) -> tuple[Agent, ...]:
    """Return both loaded child collections in their already-normalized order."""
    return (*row.runtime_children, *row.followup_agents)


def _is_excluded_agent_session_turn(row: Agent) -> bool:
    """Return whether *row* is scaffolding rather than a concrete session turn."""
    return row.agent_session_parallel


def _concrete_agent_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return concrete agents represented by one non-container row.

    A loaded workflow aggregate is represented by its real agent-type steps.
    Python/bash steps never count as agents.  When no agent step is loaded,
    the aggregate row remains the compatibility fallback and counts once.
    """
    if agent.is_workflow_step_child:
        if (
            agent.step_type == "agent"
            and not agent.agent_session_parallel
            and not row_is_agent_session_turn(agent)
        ):
            return (agent,)
        return ()
    if row_is_agent_session_turn(agent):
        return ()
    if agent.is_named_proc:
        return ()

    if _is_workflow_aggregate_row(agent):
        agent_steps = _dedupe_rows(
            tuple(
                child
                for child in (*agent.runtime_children, *agent.followup_agents)
                if child.is_workflow_step_child
                and child.step_type == "agent"
                and not child.agent_session_parallel
                and not row_is_agent_session_turn(child)
            )
        )
        if agent_steps:
            return agent_steps
    return (agent,)


@dataclass(frozen=True, slots=True)
class _AgentSessionTurnAnchors:
    """Ordered agent-turn anchors plus the anchor standing in for the root.

    ``container_proxy`` is the turn that represents the container row's own
    agent process: the concrete planner step when one is loaded (same
    ``raw_suffix`` and artifacts dir as the container, different
    ``identity``), the container itself when it represents a member, and
    ``None`` when nothing in the sequence represents it.
    """

    anchors: tuple[Agent, ...]
    container_proxy: Agent | None


def _agent_session_turn_anchors(agent: Agent) -> _AgentSessionTurnAnchors:
    """Return the ordered agent-turn chain before nested monitors are inserted."""
    planner = _concrete_planner_child(agent)
    candidates: list[Agent] = []
    container_proxy: Agent | None = None
    if planner is not None:
        candidates.append(planner)
        container_proxy = planner
    elif root_represents_member(agent):
        candidates.append(agent)
        container_proxy = agent

    candidates.extend(_concrete_continuations(agent.runtime_children, planner))
    candidates.extend(_concrete_continuations(agent.followup_agents, planner))
    return _AgentSessionTurnAnchors(
        anchors=_dedupe_by_identity(candidates),
        container_proxy=container_proxy,
    )


def _expand_nested_agent_session_turns(
    container: Agent,
    anchors: Sequence[Agent],
    container_proxy: Agent | None,
) -> tuple[Agent, ...]:
    """Insert nested non-agent turns immediately after their causal starter.

    A turn attached to the container row is emitted after the anchor that
    represents that container (its planner step when one is loaded). Traverses
    both ``runtime_children`` and ``followup_agents`` because loaded shapes
    expose overlapping but not always identical links. Dedupes by durable row
    identity, cycle-guards by object identity, and keeps each collection's
    already-normalized order rather than sorting by timestamp. Later
    agent-turn continuations stay in the anchor sequence; their turns are
    not stolen while walking an earlier starter.
    """
    result: list[Agent] = []
    walked_ids: set[int] = set()
    emitted: set[tuple[AgentType, str, str | None]] = set()
    anchor_identities = {row.identity for row in anchors}

    def emit(row: Agent) -> None:
        if id(row) in walked_ids:
            return
        walked_ids.add(id(row))
        if row.identity in emitted or _is_excluded_agent_session_turn(row):
            return
        emitted.add(row.identity)
        result.append(row)
        walk_turns(row)

    def walk_turns(row: Agent) -> None:
        for child in _turn_links(row):
            child_id = id(child)
            if child_id in walked_ids:
                continue
            if child.identity in emitted:
                walked_ids.add(child_id)
                continue
            if _is_excluded_agent_session_turn(child):
                walked_ids.add(child_id)
                continue
            if row_is_agent_session_turn(child):
                emit(child)
                continue
            if child.identity in anchor_identities:
                continue
            walked_ids.add(child_id)
            walk_turns(child)

    proxy = container_proxy
    if proxy is not None and proxy.identity == container.identity:
        proxy = None  # emit(container) already walks the container's turns
    pending_container_walk = proxy is not None
    if proxy is None and container.identity not in anchor_identities:
        walk_turns(container)  # nothing represents the container
    for anchor in anchors:
        emit(anchor)
        if (
            pending_container_walk
            and proxy is not None
            and anchor.identity == proxy.identity
        ):
            walk_turns(container)
            pending_container_walk = False
    if pending_container_walk:
        walk_turns(container)  # proxy absent from anchors: never drop a row
    return tuple(result)


def concrete_agent_session_turn_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return ordered concrete session turns: agent turns and nested non-agent turns.

    Plan workflow roots are aggregate rows. When their concrete main agent
    step is loaded, that step owns the planner phase; otherwise the root stays
    as the compatibility fallback. Rename-on-attach roots remain the first
    real turn for agent sessions that do not have a concrete planner step.

    A non-agent turn is emitted immediately after the turn that started it. A
    turn attached to the container row is emitted after the anchor that
    represents that container (its planner step when one is loaded). Synthetic
    planners, non-agent workflow steps, and parallel-agent-session rows stay
    excluded. The walk is a pure in-memory projection: linear in the loaded
    agent session subtree, cycle-safe, identity-deduped, and ordered by causal
    placement rather than timestamp.
    """
    projection = _agent_session_turn_anchors(agent)
    return _expand_nested_agent_session_turns(
        agent,
        projection.anchors,
        projection.container_proxy,
    )


def current_agent_session_turn_row(agent: Agent) -> Agent | None:
    """Return the current in-flight concrete turn for a sequential agent session."""
    if agent.is_clan_container or not is_sequential_agent_session_container(agent):
        return None
    for row in reversed(concrete_agent_session_turn_rows(agent)):
        if agent_row_is_in_flight(row):
            return row
    return None


def concrete_agent_session_member_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return ordered concrete agent turns represented by a session container.

    Monitor named procs are omitted so agent, runner, status, and completion
    counts stay agent-only. See :func:`concrete_agent_session_turn_rows` for the
    roster sequence that includes them.
    """
    return tuple(
        row
        for row in concrete_agent_session_turn_rows(agent)
        if not row_is_agent_session_turn(row)
    )


def agent_session_roster_container(agent: Agent) -> Agent | None:
    """Return the container row whose SESSION TURNS roster lists ``agent``.

    Container rows render their own roster and are never members of another
    row's roster, so they resolve to ``None``.
    """
    if agent.is_agent_session_container_row:
        return None
    container = agent.agent_session_container
    if container is None or container is agent:
        return None
    return container


def _settled_member_bucket(member: Agent) -> str:
    """Return the effective bucket for one non-final sequential-agent-session member."""
    bucket = agent_status_bucket(member)
    if bucket not in _IN_FLIGHT_BUCKETS or agent_row_is_in_flight(member):
        return bucket
    return "Done"


def monitor_row_lane_bucket(row: Agent) -> str:
    """Return the agent-level lane bucket for one monitor row.

    The row keeps its own bucket for its own display; aggregates read a
    settled monitor only as the current state of its lane via
    :func:`monitor_lane_status_bucket`.
    """
    own = agent_status_bucket(row)
    if not (row.is_monitor and monitor_row_is_settled(row)):
        return own
    return monitor_lane_status_bucket(
        row.monitor_state,
        own,
        followup_outcome=row.monitor_followup_outcome,
        followup_error=row.monitor_followup_error,
        next_action=row.monitor_next_action,
        host_completion_status=row.monitor_host_completion_status,
    )


def agent_session_lane_status_entries(
    rows: Sequence[Agent],
) -> tuple[tuple[str, str], ...]:
    """Return ``(status, bucket)`` entries for a session lane, handoff-aware.

    Starts from :func:`agent_session_member_status_buckets`. A settled monitor
    that is not the final row already handed its result to a later row, so it
    is skipped. A final settled monitor contributes its lane bucket from
    :func:`monitor_row_lane_bucket`. Every other row keeps its bucket.
    """
    buckets = agent_session_member_status_buckets(rows)
    entries: list[tuple[str, str]] = []
    final_index = len(rows) - 1
    for index, (row, bucket) in enumerate(zip(rows, buckets, strict=True)):
        if row.is_monitor and monitor_row_is_settled(row):
            if index != final_index:
                continue
            entries.append((row.status, monitor_row_lane_bucket(row)))
        else:
            entries.append((row.status, bucket))
    return tuple(entries)


def agent_session_member_status_buckets(members: Sequence[Agent]) -> tuple[str, ...]:
    """Return effective buckets for an ordered sequential agent session.

    A session advances one member at a time: a successor is attached only once
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
    if is_sequential_agent_session_container(agent):
        rows = concrete_agent_session_member_rows(agent)
        buckets = agent_session_member_status_buckets(rows)
    else:
        rows = _concrete_agent_rows(agent)
        buckets = tuple(agent_status_bucket(row) for row in rows)
    pairs = tuple(
        (row, bucket)
        for row, bucket in zip(rows, buckets, strict=True)
        if not row_is_agent_session_turn(row)
    )
    return tuple(ConcreteAgentStatus(agent=row, bucket=bucket) for row, bucket in pairs)


def _concrete_planner_child(agent: Agent) -> Agent | None:
    if not agent.is_plan_agent_session_root_entry:
        return None
    return next(
        (
            child
            for child in agent.runtime_children
            if child.is_workflow_step_child
            and child.step_type == "agent"
            and child.parent_step_index is None
            and not child.agent_session_parallel
        ),
        None,
    )


def root_represents_member(agent: Agent) -> bool:
    if agent.is_imported_agent_session_container:
        return False
    if agent.is_plan_agent_session_root_entry:
        return True
    agent_session_name = agent.agent_session or agent.agent_session_reference_name()
    return not bool(
        agent.agent_name
        and agent_session_name
        and agent.agent_name == agent_session_name
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
        and not _is_excluded_agent_session_turn(row)
        and not row_is_agent_session_turn(row)
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
    "NO_GATE_LANES",
    "NO_MONITOR_LANES",
    "NO_TURN_LANES",
    "TurnLaneCounts",
    "agent_row_is_in_flight",
    "agent_session_lane_status_entries",
    "concrete_agent_statuses",
    "concrete_agent_session_member_rows",
    "concrete_agent_session_turn_rows",
    "current_agent_session_turn_row",
    "agent_session_member_status_buckets",
    "agent_session_roster_container",
    "gate_row_is_settled",
    "is_sequential_agent_session_container",
    "monitor_row_is_settled",
    "monitor_row_lane_bucket",
    "panel_turn_lane_counts",
    "root_represents_member",
    "row_is_agent_session_turn",
    "turn_lane_counts",
]

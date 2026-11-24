"""Lane status and turn counts for ACE agent session projections."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sase.agent.status_buckets import agent_is_active, agent_status_bucket
from sase.gate_turn.state import gate_state_is_terminal
from sase.monitor_state import (
    MONITOR_HELD_STATE,
    monitor_lane_status_bucket,
    monitor_state_is_terminal,
)
from .agent import Agent, AgentType

#: Buckets that claim an agent process is still executing.
_IN_FLIGHT_BUCKETS: frozenset[str] = frozenset({"Running", "Starting"})


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

    A held staged monitor is Failed but nonterminal: it never ran, so it
    belongs in the settled (grey) lane rather than the in-flight orange one.
    """
    if row.monitor_state == MONITOR_HELD_STATE:
        return True
    return monitor_state_is_terminal(row.monitor_state) or row.stop_time is not None


def monitor_row_is_settle_candidate(row: Agent) -> bool:
    """Return whether a monitor row may still be settling its continuation.

    The supervisor persists a terminal ``monitor_state`` as soon as the
    command exits, then resolves outcome policy and launches any follow-up,
    and only then stamps ``stopped_at``. A terminal row with no stop time and
    a recorded supervisor pid is therefore a candidate; the loader decides
    whether it is actually settling with a bounded liveness probe and stamps
    :attr:`Agent.monitor_settling`. Pure: performs no I/O.
    """
    return (
        row.is_monitor
        and monitor_state_is_terminal(row.monitor_state)
        and row.stop_time is None
        and row.pid is not None
    )


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


def row_is_not_adopted_handoff(row: Agent) -> bool:
    """Return whether *row* is a held monitor proposal, not started work."""
    return row.is_monitor and row.monitor_state == MONITOR_HELD_STATE


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
    :func:`monitor_lane_status_bucket`. A row the loader stamped as
    :attr:`Agent.monitor_settling` (terminal command, live supervisor still
    deciding the continuation) reads as an in-progress lane rather than as
    its command's failure.
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
        settling=row.monitor_settling,
    )


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

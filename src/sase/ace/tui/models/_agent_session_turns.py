"""Ordered concrete turn projections for sequential agent sessions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sase.agent.status_buckets import agent_status_bucket
from ._agent_session_lanes import (
    agent_row_is_in_flight,
    is_sequential_agent_session_container,
    monitor_row_lane_bucket,
    row_is_agent_session_turn,
    row_is_not_adopted_handoff,
)
from .agent import Agent, AgentType


def _is_excluded_agent_session_turn(row: Agent) -> bool:
    """Return whether *row* is scaffolding rather than a concrete session turn."""
    return row.agent_session_parallel


def _turn_links(row: Agent) -> tuple[Agent, ...]:
    """Return both loaded child collections in their already-normalized order."""
    return (*row.runtime_children, *row.followup_agents)


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


class _TurnExpansion:
    """Acyclic traversal state for :func:`_expand_nested_agent_session_turns`.

    The walk used to be a pair of mutually recursive local functions. Their
    closure cells formed a reference cycle that pinned every visited row (and
    the result list) until the cyclic collector ran, once per concrete-turn
    projection. This holder keeps the same state on a plain object and
    descends with an explicit stack, so dropping the result frees the rows by
    refcount and a pathological graph cannot hit the recursion limit.
    """

    __slots__ = ("anchor_identities", "emitted", "result", "walked_ids")

    def __init__(self, anchors: Sequence[Agent]) -> None:
        self.result: list[Agent] = []
        self.walked_ids: set[int] = set()
        self.emitted: set[tuple[AgentType, str, str | None]] = set()
        self.anchor_identities = {row.identity for row in anchors}

    def _admit(self, row: Agent) -> bool:
        """Record *row* as a session turn; return whether its links are walked."""
        if id(row) in self.walked_ids:
            return False
        self.walked_ids.add(id(row))
        if row.identity in self.emitted or _is_excluded_agent_session_turn(row):
            return False
        self.emitted.add(row.identity)
        self.result.append(row)
        return True

    def emit(self, row: Agent) -> None:
        """Emit *row*, then its causal turns, in depth-first link order."""
        if self._admit(row):
            self.walk_turns(row)

    def walk_turns(self, row: Agent) -> None:
        """Emit the turns reachable from *row*'s links, depth-first."""
        pending = [iter(_turn_links(row))]
        while pending:
            for child in pending[-1]:
                child_id = id(child)
                if child_id in self.walked_ids:
                    continue
                if child.identity in self.emitted:
                    self.walked_ids.add(child_id)
                    continue
                if _is_excluded_agent_session_turn(child):
                    self.walked_ids.add(child_id)
                    continue
                if row_is_agent_session_turn(child):
                    if self._admit(child):
                        pending.append(iter(_turn_links(child)))
                        break
                    continue
                if child.identity in self.anchor_identities:
                    continue
                self.walked_ids.add(child_id)
                pending.append(iter(_turn_links(child)))
                break
            else:
                pending.pop()


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
    walk = _TurnExpansion(anchors)
    proxy = container_proxy
    if proxy is not None and proxy.identity == container.identity:
        proxy = None  # emit(container) already walks the container's turns
    pending_container_walk = proxy is not None
    if proxy is None and container.identity not in walk.anchor_identities:
        walk.walk_turns(container)  # nothing represents the container
    for anchor in anchors:
        walk.emit(anchor)
        if (
            pending_container_walk
            and proxy is not None
            and anchor.identity == proxy.identity
        ):
            walk.walk_turns(container)
            pending_container_walk = False
    if pending_container_walk:
        walk.walk_turns(container)  # proxy absent from anchors: never drop a row
    return tuple(walk.result)


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


def agent_session_running_monitor_row(agent: Agent) -> Agent | None:
    """Return the session's current turn when it is a running monitor turn.

    A monitor nests under the agent turn that started it, so aggregates built
    from a session's agent turns settle a lane whose only live work is that
    monitor. Callers add this row to their lane entries to keep it in flight.
    """
    current = current_agent_session_turn_row(agent)
    if current is not None and current.is_monitor:
        return current
    return None


def agent_session_lone_running_monitor_row(agent: Agent) -> Agent | None:
    """Return the session's only in-flight turn when that turn is a monitor.

    A held (not-adopted) monitor is not in flight, so it never qualifies.
    Bounded to the loaded session subtree: no projection-wide scan.
    """
    if agent.is_clan_container or not is_sequential_agent_session_container(agent):
        return None
    in_flight: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for row in concrete_agent_session_turn_rows(agent):
        if row.identity in seen:
            continue
        seen.add(row.identity)
        if not agent_row_is_in_flight(row):
            continue
        in_flight.append(row)
        if len(in_flight) > 1:
            return None
    if len(in_flight) != 1:
        return None
    lone = in_flight[0]
    return lone if lone.is_monitor else None


def agent_session_failed_turn_row(agent: Agent) -> Agent | None:
    """Return the session's failure-frontier turn when nothing is running.

    Applies to a sequential-session row whose own bucket is ``Failed`` and
    that has no in-flight turn. The candidates mirror the exclusions
    ``failure_focus_for_agent`` uses: rows that are not the container
    itself, whose lane bucket is ``Failed`` (a failed check whose
    continuation launched reads as ``Running`` and does not count), that
    were never retried, and that are not held (not-adopted) handoffs.
    Returns the last candidate in the walk's causal order, or ``None``.
    """
    if agent.is_clan_container or not is_sequential_agent_session_container(agent):
        return None
    if agent_status_bucket(agent) != "Failed":
        return None
    candidate: Agent | None = None
    rows = concrete_agent_session_turn_rows(agent)
    seen: set[tuple[AgentType, str, str | None]] = set()
    for row in rows:
        if row.identity in seen:
            continue
        seen.add(row.identity)
        if agent_row_is_in_flight(row):
            return None
    seen.clear()
    for row in rows:
        if row.identity in seen:
            continue
        seen.add(row.identity)
        if row.identity == agent.identity:
            continue
        if monitor_row_lane_bucket(row) != "Failed":
            continue
        if row.retried_as_timestamp is not None:
            continue
        if row_is_not_adopted_handoff(row):
            continue
        candidate = row
    return candidate


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


def _dedupe_by_identity(rows: Sequence[Agent]) -> tuple[Agent, ...]:
    ordered: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for row in rows:
        if row.identity in seen:
            continue
        seen.add(row.identity)
        ordered.append(row)
    return tuple(ordered)

"""Cycle-safe copies of the Agents-tab row graph.

``Agent`` rows are mutable presentation objects. A frozen snapshot dataclass
that stores lists of those rows does not isolate them: worker-side
relationship rebuilds (``followup_agents``, ``runtime_children``,
``agent_session_container``, ``wait_display_source``,
``status_display_source``, retry links) mutate the same
objects the UI is rendering unless this copy runs first.

Each reachable ``Agent`` is copied once through a shared memo so overlapping
collections (visible roster, capacity roster, session back-pointers) keep
intentional aliases inside the new graph and do not alias back to live rows.

Use :func:`copy_agent_graph` when the worker rebuilds relationships or walks
the full reachable graph (load-time detach). Use
:func:`copy_agent_rows_relinked` when the consumer only reassigns row
attributes on the copied roster itself — as the runner-slot pass does — and
never mutates nested leaf containers in place. The relinked copy is about as
cheap as a plain shallow copy (~7 ms per 600 rows versus ~160 ms for the full
graph copy); the roster refresh runs twice per capacity-report install (at
least every 10 s even when idle), so that cost matters under the TUI perf
rules ("periodic ticks revalidate; recomputes get a longer cadence").

``agent_session_container`` is a weak backreference behind its ordinary
``Agent | None`` interface. Copy paths read and reassign that interface so a
copied member points to its copied container, not the original.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import copy
from dataclasses import dataclass, fields
from typing import Any

from .agent import Agent

__all__ = [
    "AGENT_RELINK_FIELDS",
    "DELTA_ISOLATED_FIELDS",
    "AffectedClosure",
    "adopt_agents",
    "compute_affected_closure",
    "copy_agent_graph",
    "copy_agent_rows_delta_isolated",
    "copy_agent_rows_relinked",
    "own_affected_delta_rows",
]

#: ``Agent``-reference fields relinked by :func:`copy_agent_rows_relinked`.
#: Single-``Agent`` values map through the in-batch memo; lists map
#: element-wise into a new list so the copy never shares a list object with
#: the live row. Assigning the weak session-container backreference again
#: installs a weak reference to the mapped row. A reference to a row outside
#: the batch is kept as-is (consumers only read those rows).
AGENT_RELINK_FIELDS: tuple[str, ...] = (
    "followup_agents",
    "runtime_children",
    "wait_display_source",
    "status_display_source",
    "agent_session_container",
    "retry_chain_siblings",
)

#: Mutable leaf containers the delta fast path isolates on every shallow row
#: copy. The merge/slot/tree passes mutate these in place (timestamp appends,
#: feedback-path inserts, ``step_output`` updates); sharing the live objects
#: would let a worker thread mutate the displayed graph before apply.
DELTA_ISOLATED_FIELDS: tuple[str, ...] = (
    "retry_chain_siblings",
    "plan_times",
    "feedback_times",
    "questions_times",
    "feedback_plan_paths",
    "step_output",
)


def copy_agent_graph(
    agents: Sequence[Agent],
    memo: dict[int, Agent] | None = None,
) -> list[Agent]:
    """Return a detached copy of *agents*, sharing *memo* across collections."""
    owned = {} if memo is None else memo
    return [_copy_agent(agent, owned) for agent in agents]


def _copy_agent(agent: Agent, memo: dict[int, Agent] | None = None) -> Agent:
    """Return the memoized detached copy of *agent*."""
    from ._projected_record import projected_agent_compact_copy_value

    owned = {} if memo is None else memo
    existing = owned.get(id(agent))
    if existing is not None:
        return existing

    init_kwargs: dict[str, Any] = {}
    deferred: list[tuple[str, Any]] = []
    for field in fields(agent):
        present, value = projected_agent_compact_copy_value(agent, field.name)
        if not present and field.name == "agent_session_container":
            # This public field is stored behind a descriptor, so it is not
            # present under its field name in ``vars(agent)``. Still copy its
            # resolved Agent value and let the graph memo relink it.
            present, value = True, agent.agent_session_container
        if not present:
            continue
        if _value_contains_agent(value):
            if field.init:
                init_kwargs[field.name] = _empty_placeholder(value)
            deferred.append((field.name, value))
            continue
        copied = _copy_leaf(value)
        if field.init:
            init_kwargs[field.name] = copied
        else:
            deferred.append((field.name, copied))

    clone = Agent(**init_kwargs)
    owned[id(agent)] = clone
    for name, value in deferred:
        if _value_contains_agent(value):
            setattr(clone, name, _copy_graph_value(value, owned))
        else:
            setattr(clone, name, value)
    return clone


def copy_agent_rows_relinked(agents: Sequence[Agent]) -> list[Agent]:
    """Return shallow row copies with in-batch ``Agent`` references relinked.

    Each distinct input row is copied once with :func:`copy.copy` (memoized
    by :func:`id`, so a row appearing twice stays a single copy) and the
    result preserves input order, including duplicate positions.

    Each copy's :data:`AGENT_RELINK_FIELDS` are then rewritten to point at
    the in-batch copies: single-``Agent`` values map through the memo and
    lists map element-wise into a new list, so no copy shares a list object
    with a live row. A reference to a row outside the batch is kept as-is;
    consumers only read those rows.

    The caller must only reassign row attributes on the returned copies (as
    the runner-slot pass does) and never mutate nested leaf containers in
    place.
    """
    memo: dict[int, Agent] = {}
    originals: dict[int, Agent] = {}
    for agent in agents:
        key = id(agent)
        if key not in memo:
            memo[key] = copy(agent)
            from ._projected_record import prepare_projected_agent_copy

            prepare_projected_agent_copy(agent, memo[key])
            originals[key] = agent
    for key, original in originals.items():
        clone = memo[key]
        for field_name in AGENT_RELINK_FIELDS:
            value = getattr(original, field_name)
            if isinstance(value, Agent):
                setattr(clone, field_name, memo.get(id(value), value))
            elif isinstance(value, list):
                setattr(
                    clone,
                    field_name,
                    [
                        memo.get(id(item), item) if isinstance(item, Agent) else item
                        for item in value
                    ],
                )
            elif value is None:
                setattr(clone, field_name, None)
            else:
                setattr(clone, field_name, value)
    return [memo[id(agent)] for agent in agents]


def copy_agent_rows_delta_isolated(
    agents: Sequence[Agent],
    memo: dict[int, Agent] | None = None,
) -> list[Agent]:
    """Return shallow row copies isolated for the exact-delta fast path.

    Like :func:`copy_agent_rows_relinked` each distinct row is copied once
    with :func:`copy.copy` (memoized by :func:`id`) and in-batch ``Agent``
    references are relinked through the shared *memo* so visible, capacity,
    and fleet rosters keep intentional aliases without aliasing live rows.

    Every mutable list/dict/set container is additionally detached into a
    new container sharing only leaf values (``Agent`` elements relink
    through *memo*). The merge/slot/tree passes mutate several of these in
    place (:data:`DELTA_ISOLATED_FIELDS` names the known ones: timestamp
    appends, feedback-path inserts, ``step_output`` updates,
    ``retry_chain_siblings`` rebuilds); detaching all of them keeps a worker
    thread from mutating the displayed graph before apply even when a later
    pass gains a new in-place write. Immutable leaves, tuples, and nested
    dataclass wires (clan context, retention, fleet payloads) stay shared
    read-only: preparation only ever reassigns or replaces those, never
    mutates them in place.
    """

    owned = {} if memo is None else memo
    originals: dict[int, Agent] = {}
    for agent in agents:
        key = id(agent)
        if key not in owned:
            clone = copy(agent)
            from ._projected_record import prepare_projected_agent_copy

            prepare_projected_agent_copy(agent, clone)
            owned[key] = clone
            originals[key] = agent
    all_fields = fields(Agent)
    for key, original in originals.items():
        clone = owned[key]
        for field in all_fields:
            field_name = field.name
            if field_name in AGENT_RELINK_FIELDS:
                value = getattr(original, field_name)
                if isinstance(value, Agent):
                    setattr(clone, field_name, owned.get(id(value), value))
                elif isinstance(value, list):
                    setattr(
                        clone,
                        field_name,
                        [
                            owned.get(id(item), item)
                            if isinstance(item, Agent)
                            else item
                            for item in value
                        ],
                    )
                elif value is None:
                    setattr(clone, field_name, None)
                else:
                    setattr(clone, field_name, value)
                continue
            value = getattr(original, field_name, None)
            if isinstance(value, list):
                if "__copy__" in type(value).__dict__:
                    setattr(clone, field_name, copy(value))
                else:
                    setattr(
                        clone,
                        field_name,
                        [
                            owned.get(id(item), item)
                            if isinstance(item, Agent)
                            else item
                            for item in value
                        ],
                    )
            elif isinstance(value, dict):
                setattr(
                    clone,
                    field_name,
                    {
                        map_key: owned.get(id(item), item)
                        if isinstance(item, Agent)
                        else item
                        for map_key, item in value.items()
                    },
                )
            elif isinstance(value, set):
                setattr(
                    clone,
                    field_name,
                    {
                        owned.get(id(item), item) if isinstance(item, Agent) else item
                        for item in value
                    },
                )
    return [owned[id(agent)] for agent in agents]


def adopt_agents(
    agents: Sequence[Agent],
    memo: Mapping[int, Agent],
) -> list[Agent]:
    """Replace live cached rows with their detached copies; keep worker-owned rows."""
    return [memo.get(id(agent), agent) for agent in agents]


def _value_contains_agent(value: Any) -> bool:
    if isinstance(value, Agent):
        return True
    if isinstance(value, (list, tuple, set)):
        if isinstance(value, list) and "__copy__" in type(value).__dict__:
            # Lazy list subclasses may load while iterating. Their custom copy
            # hook preserves their cache without materializing the payload.
            return False
        return any(_value_contains_agent(item) for item in value)
    if isinstance(value, dict):
        return any(_value_contains_agent(item) for item in value.values())
    return False


def _empty_placeholder(value: Any) -> Any:
    if isinstance(value, Agent):
        return None
    if isinstance(value, list):
        return []
    if isinstance(value, tuple):
        return ()
    if isinstance(value, dict):
        return {}
    if isinstance(value, set):
        return set()
    return None


def _copy_graph_value(value: Any, memo: dict[int, Agent]) -> Any:
    if isinstance(value, Agent):
        return _copy_agent(value, memo)
    if isinstance(value, list):
        return [_copy_graph_value(item, memo) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_graph_value(item, memo) for item in value)
    if isinstance(value, dict):
        return {key: _copy_graph_value(item, memo) for key, item in value.items()}
    if isinstance(value, set):
        return {_copy_graph_value(item, memo) for item in value}
    return _copy_leaf(value)


def _copy_leaf(value: Any) -> Any:
    """Copy mutable containers; share immutables and frozen values."""
    if isinstance(value, list):
        if "__copy__" in type(value).__dict__:
            # Lazy list subclasses can provide a non-materializing copy.
            return copy(value)
        return [_copy_leaf(item) for item in value]
    if isinstance(value, dict):
        return {key: _copy_leaf(item) for key, item in value.items()}
    if isinstance(value, set):
        return {_copy_leaf(item) for item in value}
    if isinstance(value, tuple):
        return tuple(_copy_leaf(item) for item in value)
    return value


#: Relationship keys separating scalar exact-delta replacements from
#: structural ones. Must stay equal to ``EXACT_DELTA_RELATIONSHIP_KEYS`` in
#: ``actions/agents/_loading_compute_merge.py`` (asserted by
#: ``tests/test_agent_affected_closure_ownership.py``); the merge/normalizer
#: may rewrite relationships only through these keys, so a scalar delta keeps
#: every one of them equal between the incoming row and its cached
#: counterpart. Membership, ordering, dedup, capacity-alias, and query
#: changes differ in at least one key and fall back to the full safe path.
_AFFECTED_RELATIONSHIP_KEYS: tuple[str, ...] = (
    "parent_timestamp",
    "parent_workflow",
    "agent_session",
    "agent_session_role",
    "agent_clan",
    "agent_clan_generation",
    "pid",
    "raw_suffix",
    "project_file",
    "agent_type",
    "workflow",
    "parent_step_index",
    "step_index",
    "step_type",
    "step_name",
    "role_suffix",
    "is_workflow_child",
    "is_agent_session_member_child",
    "fleet_origin_alias",
    "start_time",
)


@dataclass(frozen=True)
class AffectedClosure:
    """Bounded write-set prediction for one exact scalar delta.

    ``affected_identities`` holds the cached identities a downstream prep
    pass may rewrite for the delta: the changed rows plus every row reachable
    through a relationship the merge, slot, tree, or display-source passes
    mutate in place (parent/child/sibling links, session and clan
    membership, workflow step groups, and capacity-alias re-homing).

    ``eligible`` is True only for the bounded scalar case (``reason`` is then
    ``"bounded"``). Any other reason (``"empty-cache"``,
    ``"unanchored-new-row"``, ``"relationship-change"``,
    ``"oversized-closure"``) is an explicit fallback contract: the caller
    must use the existing full safe path instead. No production caller
    consumes this yet; the delta-integration phase will wire the eligible
    case into the expanded fast path.
    """

    affected_identities: frozenset[tuple[Any, str, str | None]]
    eligible: bool
    reason: str
    seeds: int
    closure_size: int
    cached_size: int
    max_closure_size: int


def _closure_failure(
    reason: str,
    *,
    seeds: int,
    cached_size: int,
    max_closure_size: int,
    affected: frozenset[tuple[Any, str, str | None]] = frozenset(),
) -> AffectedClosure:
    return AffectedClosure(
        affected_identities=affected,
        eligible=False,
        reason=reason,
        seeds=seeds,
        closure_size=len(affected),
        cached_size=cached_size,
        max_closure_size=max_closure_size,
    )


def compute_affected_closure(
    cached: Sequence[Agent],
    incoming: Sequence[Agent],
    *,
    max_closure_size: int = 96,
) -> AffectedClosure:
    """Derive the bounded affected closure for an exact scalar delta.

    The expansion covers every relationship a downstream prep pass can
    mutate: direct graph neighbors (``followup_agents``,
    ``runtime_children``, ``retry_chain_siblings``, session container, and
    wait/status display sources, in both directions), session mates, clan
    mates (all generations plus the clan container), parent/child/step
    groups, rows waiting on a changed row (``waiting_for`` names the
    changed row's ``cl_name``), and capacity-alias mates when the delta
    re-homes an alias. The runner-slot pass still annotates the full roster
    through its own existing read-only index passes; this closure bounds
    the relationship-merge write set, not the slot read set.

    Out-of-closure ``Agent`` references from an owned copy keep aliasing the
    live rows read-only (see :func:`own_affected_delta_rows`); the merge
    write set predicted here never includes them.
    """
    cached_list = list(cached)
    incoming_list = list(incoming)
    cached_size = len(cached_list)
    if not cached_list:
        return _closure_failure(
            "empty-cache",
            seeds=0,
            cached_size=0,
            max_closure_size=max_closure_size,
        )
    by_identity: dict[tuple[Any, str, str | None], Agent] = {}
    for agent in cached_list:
        by_identity.setdefault(agent.identity, agent)

    waiter_groups: dict[str, set[tuple[Any, str, str | None]]] = {}
    session_groups: dict[str, set[tuple[Any, str, str | None]]] = {}
    clan_groups: dict[str, set[tuple[Any, str, str | None]]] = {}
    alias_groups: dict[str, set[tuple[Any, str, str | None]]] = {}
    child_groups: dict[str, set[tuple[Any, str, str | None]]] = {}
    step_groups: dict[
        tuple[str | None, str | None], set[tuple[Any, str, str | None]]
    ] = {}
    parent_by_suffix: dict[str, Agent] = {}
    reverse_refs: dict[
        tuple[Any, str, str | None], set[tuple[Any, str, str | None]]
    ] = {}
    for agent in cached_list:
        ident = agent.identity
        waiting_for = getattr(agent, "waiting_for", None)
        if isinstance(waiting_for, list):
            for name in waiting_for:
                if isinstance(name, str):
                    waiter_groups.setdefault(name, set()).add(ident)
        if agent.agent_session:
            session_groups.setdefault(agent.agent_session, set()).add(ident)
        if agent.agent_clan:
            clan_groups.setdefault(agent.agent_clan, set()).add(ident)
        if agent.fleet_origin_alias:
            alias_groups.setdefault(agent.fleet_origin_alias, set()).add(ident)
        if agent.parent_timestamp and not agent.parent_workflow:
            child_groups.setdefault(agent.parent_timestamp, set()).add(ident)
        if agent.parent_workflow or agent.parent_timestamp:
            step_groups.setdefault(
                (agent.parent_workflow, agent.parent_timestamp), set()
            ).add(ident)
        if agent.raw_suffix is not None and not agent.is_workflow_child:
            parent_by_suffix.setdefault(agent.raw_suffix, agent)
        targets: list[Agent] = []
        for name in (
            "followup_agents",
            "runtime_children",
            "retry_chain_siblings",
        ):
            value = getattr(agent, name, None)
            if isinstance(value, list):
                targets.extend(item for item in value if isinstance(item, Agent))
        for name in (
            "agent_session_container",
            "wait_display_source",
            "status_display_source",
        ):
            value = getattr(agent, name, None)
            if isinstance(value, Agent):
                targets.append(value)
        for target in targets:
            reverse_refs.setdefault(target.identity, set()).add(ident)

    seeds: set[tuple[Any, str, str | None]] = set()
    for row in incoming_list:
        counterpart = by_identity.get(row.identity)
        if counterpart is None:
            anchors: set[tuple[Any, str, str | None]] = set()
            if row.agent_session and row.agent_session in session_groups:
                anchors |= session_groups[row.agent_session]
            if row.agent_clan and row.agent_clan in clan_groups:
                anchors |= clan_groups[row.agent_clan]
            if row.parent_timestamp:
                anchors |= child_groups.get(row.parent_timestamp, set())
                parent = parent_by_suffix.get(row.parent_timestamp)
                if parent is not None:
                    anchors.add(parent.identity)
            if row.fleet_origin_alias and row.fleet_origin_alias in alias_groups:
                anchors |= alias_groups[row.fleet_origin_alias]
            if not anchors:
                return _closure_failure(
                    "unanchored-new-row",
                    seeds=len(seeds),
                    cached_size=cached_size,
                    max_closure_size=max_closure_size,
                    affected=frozenset(seeds),
                )
            seeds |= anchors
            continue
        for key in _AFFECTED_RELATIONSHIP_KEYS:
            if getattr(row, key, None) != getattr(counterpart, key, None):
                return _closure_failure(
                    "relationship-change",
                    seeds=len(seeds),
                    cached_size=cached_size,
                    max_closure_size=max_closure_size,
                    affected=frozenset(seeds),
                )
        seeds.add(counterpart.identity)

    closure = set(seeds)
    for seed in seeds:
        seeded = by_identity.get(seed)
        if seeded is None:
            continue
        direct: list[Agent] = []
        for name in (
            "followup_agents",
            "runtime_children",
            "retry_chain_siblings",
        ):
            value = getattr(seeded, name, None)
            if isinstance(value, list):
                direct.extend(item for item in value if isinstance(item, Agent))
        for name in (
            "agent_session_container",
            "wait_display_source",
            "status_display_source",
        ):
            value = getattr(seeded, name, None)
            if isinstance(value, Agent):
                direct.append(value)
        for target in direct:
            if target.identity in by_identity:
                closure.add(target.identity)
        closure |= reverse_refs.get(seed, set())
        if seeded.agent_session and seeded.agent_session in session_groups:
            closure |= session_groups[seeded.agent_session]
        closure |= waiter_groups.get(seeded.cl_name, set())
        if seeded.agent_clan and seeded.agent_clan in clan_groups:
            closure |= clan_groups[seeded.agent_clan]
        if seeded.raw_suffix is not None:
            closure |= child_groups.get(seeded.raw_suffix, set())
            for child_ident in child_groups.get(seeded.raw_suffix, set()):
                closure |= reverse_refs.get(child_ident, set())
        if seeded.parent_timestamp is not None:
            parent = parent_by_suffix.get(seeded.parent_timestamp)
            if parent is not None:
                closure.add(parent.identity)
            closure |= child_groups.get(seeded.parent_timestamp, set())
            closure |= step_groups.get(
                (seeded.parent_workflow, seeded.parent_timestamp), set()
            )
        for row in incoming_list:
            counterpart = by_identity.get(row.identity)
            if counterpart is not None and counterpart.identity == seed:
                if (row.fleet_origin_alias or None) != (
                    counterpart.fleet_origin_alias or None
                ):
                    if row.fleet_origin_alias:
                        closure |= alias_groups.get(row.fleet_origin_alias, set())
                    if counterpart.fleet_origin_alias:
                        closure |= alias_groups.get(
                            counterpart.fleet_origin_alias, set()
                        )
                break

    if len(closure) > max_closure_size:
        return _closure_failure(
            "oversized-closure",
            seeds=len(seeds),
            cached_size=cached_size,
            max_closure_size=max_closure_size,
            affected=frozenset(closure),
        )
    return AffectedClosure(
        affected_identities=frozenset(closure),
        eligible=True,
        reason="bounded",
        seeds=len(seeds),
        closure_size=len(closure),
        cached_size=cached_size,
        max_closure_size=max_closure_size,
    )


def own_affected_delta_rows(
    cached: Sequence[Agent],
    closure: AffectedClosure,
    memo: dict[int, Agent] | None = None,
) -> tuple[list[Agent], dict[int, Agent]]:
    """Isolate exactly the affected closure; share every other live row.

    Rows in the closure are detached with
    :func:`copy_agent_rows_delta_isolated` through the shared *memo* so
    overlapping collections keep one detached clone. Rows outside the
    closure are returned as the same live objects under a read-only
    contract: in-closure relink references that point outside the closure
    keep aliasing those live rows (their list containers are still
    detached, so rebuilding a copy's link list cannot mutate the live
    list), and no downstream pass may write through them.

    Raises :exc:`ValueError` when the closure is not eligible, so an
    unbounded, structural, or unanchored delta fails closed to the existing
    full safe path instead of silently widening aliasing. No production
    caller uses this yet; the delta-integration phase owns that wiring.
    """
    if not closure.eligible:
        raise ValueError(
            "affected closure is not bounded "
            f"(reason={closure.reason}, "
            f"closure_size={closure.closure_size}, "
            f"cached_size={closure.cached_size}, "
            f"max_closure_size={closure.max_closure_size}); "
            "use the full safe path"
        )
    owned = {} if memo is None else memo
    affected = [
        agent for agent in cached if agent.identity in closure.affected_identities
    ]
    copies = copy_agent_rows_delta_isolated(affected, owned)
    table = {
        id(original): clone for original, clone in zip(affected, copies, strict=True)
    }
    return [table.get(id(agent), agent) for agent in cached], owned

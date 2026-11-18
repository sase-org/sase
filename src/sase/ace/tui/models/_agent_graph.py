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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import copy
from dataclasses import fields
from typing import Any

from .agent import Agent

__all__ = [
    "AGENT_RELINK_FIELDS",
    "DELTA_ISOLATED_FIELDS",
    "adopt_agents",
    "agent_share_fingerprint",
    "copy_agent_graph",
    "copy_agent_rows_delta_isolated",
    "copy_agent_rows_relinked",
]

#: ``Agent``-reference fields relinked by :func:`copy_agent_rows_relinked`.
#: Single-``Agent`` values map through the in-batch memo; lists map
#: element-wise into a new list so the copy never shares a list object with
#: the live row. A reference to a row outside the batch is kept as-is
#: (consumers only read those rows).
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
                setattr(
                    clone,
                    field_name,
                    [
                        owned.get(id(item), item) if isinstance(item, Agent) else item
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


def _fingerprint_value(value: Any) -> Any:
    """Convert *value* to a cycle-safe comparable fingerprint element.

    ``Agent`` references become identity tuples so working copies (which
    point at other working copies) compare equal to live rows (which point
    at live rows) when they describe the same roster. All other containers
    recurse structurally; leaf values compare by ``==``.
    """
    if isinstance(value, Agent):
        return ("agent", value.identity)
    if isinstance(value, list):
        return ("list", tuple(_fingerprint_value(item) for item in value))
    if isinstance(value, tuple):
        return ("tuple", tuple(_fingerprint_value(item) for item in value))
    if isinstance(value, set):
        try:
            return ("set", tuple(sorted(_fingerprint_value(item) for item in value)))
        except TypeError:
            return ("set", tuple(_fingerprint_value(item) for item in value))
    if isinstance(value, dict):
        try:
            items = sorted(value.items(), key=lambda kv: repr(kv[0]))
        except TypeError:
            items = list(value.items())
        return (
            "dict",
            tuple((key, _fingerprint_value(item)) for key, item in items),
        )
    try:
        hash(value)
        return value
    except TypeError:
        try:
            return ("repr", repr(value))
        except Exception:
            return ("type", type(value).__name__)


def agent_share_fingerprint(agent: Agent) -> tuple[Any, ...]:
    """Return a cycle-safe presentation fingerprint for share-back decisions.

    Covers every dataclass field so an untouched row's working copy compares
    equal to its live row even though relationship pointers address different
    (but identity-equivalent) objects. Only rows whose fingerprint matches
    the live row may be shared in the published roster.
    """
    return tuple(
        _fingerprint_value(getattr(agent, field.name)) for field in fields(agent)
    )


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
        return [_copy_leaf(item) for item in value]
    if isinstance(value, dict):
        return {key: _copy_leaf(item) for key, item in value.items()}
    if isinstance(value, set):
        return {_copy_leaf(item) for item in value}
    if isinstance(value, tuple):
        return tuple(_copy_leaf(item) for item in value)
    return value

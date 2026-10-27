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
    "adopt_agents",
    "copy_agent_graph",
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


def copy_agent_graph(
    agents: Sequence[Agent],
    memo: dict[int, Agent] | None = None,
) -> list[Agent]:
    """Return a detached copy of *agents*, sharing *memo* across collections."""
    owned = {} if memo is None else memo
    return [_copy_agent(agent, owned) for agent in agents]


def _copy_agent(agent: Agent, memo: dict[int, Agent] | None = None) -> Agent:
    """Return the memoized detached copy of *agent*."""
    owned = {} if memo is None else memo
    existing = owned.get(id(agent))
    if existing is not None:
        return existing

    init_kwargs: dict[str, Any] = {}
    deferred: list[tuple[str, Any]] = []
    for field in fields(agent):
        value = getattr(agent, field.name)
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

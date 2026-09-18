"""Cycle-safe copies of the Agents-tab row graph.

``Agent`` rows are mutable presentation objects. A frozen snapshot dataclass
that stores lists of those rows does not isolate them: worker-side
relationship rebuilds (``followup_agents``, ``runtime_children``,
``family_container``, ``wait_display_source``, retry links) mutate the same
objects the UI is rendering unless this copy runs first.

Each reachable ``Agent`` is copied once through a shared memo so overlapping
collections (visible roster, capacity roster, family back-pointers) keep
intentional aliases inside the new graph and do not alias back to live rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields
from typing import Any

from .agent import Agent

__all__ = [
    "adopt_agents",
    "copy_agent_graph",
]


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

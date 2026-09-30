"""App-wide Agents roster generation and cached projection index.

Phase ``roster-generation`` (epic ``sase-1d7``): one generation counter bumped
on every ``_agents`` / ``_agents_with_children`` assignment and every in-place
agent status mutation, plus a cached ``agent_node_projection_index`` keyed by
``(generation, roster fingerprint)`` for UI-thread callers. The
notification-poll worker keeps building its own uncached index (see
``_notification_completion_arrival``) so worker hops never share UI-thread
cache entries.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_CACHE_MAX_ENTRIES = 8

_UNSET: Any = object()


def get_roster_generation(app: Any) -> int:
    """Return the app-wide Agents roster generation (0 when never bumped)."""
    try:
        return int(getattr(app, "_agents_roster_generation", 0) or 0)
    except (TypeError, ValueError):
        return 0


def bump_roster_generation(app: Any) -> int:
    """Bump the roster generation and drop cached projection indexes."""
    generation = get_roster_generation(app) + 1
    app._agents_roster_generation = generation
    cache = getattr(app, "_agent_node_projection_index_cache", None)
    if isinstance(cache, dict):
        cache.clear()
    return generation


def notify_roster_status_mutation(app: Any) -> int:
    """Record an in-place agent status mutation on the live roster.

    Status mutations change what later phases key off the generation (wait
    maps, fleet signatures) even when the projection index itself only reads
    structural fields, so they bump exactly like a roster assignment.
    """
    return bump_roster_generation(app)


def set_agents_roster(
    app: Any,
    *,
    agents: Any = _UNSET,
    agents_with_children: Any = _UNSET,
) -> None:
    """Assign the Agents roster lists and bump the roster generation.

    Every production ``_agents`` / ``_agents_with_children`` assignment must
    go through this setter so new sites cannot forget the bump; a guard test
    (``tests/ace/tui/test_agents_roster_generation.py``) fails on raw
    assignments elsewhere under ``actions/``.
    """
    if agents_with_children is not _UNSET:
        app._agents_with_children = agents_with_children
    if agents is not _UNSET:
        app._agents = agents
    bump_roster_generation(app)


def _roster_fingerprint(roster: tuple[Any, ...]) -> tuple[Any, ...]:
    """Return a content key covering every row field the index build reads."""
    fingerprint: list[Any] = []
    for agent in roster:
        try:
            fingerprint.append(
                (
                    agent.identity,
                    agent.cl_name,
                    agent.raw_suffix,
                    agent.parent_timestamp,
                    bool(agent.is_clan_container),
                    bool(agent.is_monitor),
                    bool(agent.is_gate),
                    bool(agent.is_named_proc),
                    bool(agent.is_workflow_step_child),
                    bool(agent.is_agent_session_member_child),
                    agent.agent_session,
                    agent.agent_session_role,
                    bool(agent.agent_session_parallel),
                    bool(agent.is_agent_session_container_row),
                )
            )
        except AttributeError:
            fingerprint.append((getattr(agent, "identity", None),))
    return tuple(fingerprint)


def _projection_cache_for(app: Any) -> dict[Any, Any] | None:
    """Return the app's projection-index cache, creating it when possible."""
    cache = getattr(app, "_agent_node_projection_index_cache", None)
    if cache is None:
        cache = {}
        try:
            app._agent_node_projection_index_cache = cache
        except (AttributeError, TypeError):
            return None
    return cache if isinstance(cache, dict) else None


def cached_agent_node_projection_index(
    app: Any,
    roster: Iterable[Any],
) -> Any:
    """Return the ownership index for *roster*, reusing the cached build.

    The key is ``(roster generation, roster fingerprint)``: repeated callers
    within one generation (bulk ack, reconcile, finalize) share a single
    build, while any assignment or status mutation bumps the generation and
    misses. A miss delegates to :func:`agent_node_projection_index`, so the
    ``agent_nodes.projection_index`` trace span still fires per real build.
    """
    from ...models.agent_nodes import agent_node_projection_index

    materialized = tuple(roster)
    key = (get_roster_generation(app), _roster_fingerprint(materialized))
    cache = _projection_cache_for(app)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit
    index = agent_node_projection_index(materialized)
    if cache is not None:
        if len(cache) >= _CACHE_MAX_ENTRIES:
            cache.clear()
        cache[key] = index
    return index


__all__ = [
    "bump_roster_generation",
    "cached_agent_node_projection_index",
    "get_roster_generation",
    "notify_roster_status_mutation",
    "set_agents_roster",
]

"""App-wide cache for agent wait-status maps (phase runtime-tick-caches).

``collect_agent_wait_status_maps`` rescans the whole roster, rebuilds clan
groups, and resolves tribe wait bindings. The 1 Hz runtime tick used to pay
that cost once per clan container per tick via ``patch_row``. This module
caches one maps object per app, keyed by ``(roster generation,
tribe-assignment generation, roster identity, roster length)`` so repeated
tick callers share a single build within one generation.

Roster assignments and in-place status mutations bump the roster generation
(``_roster_generation``); optimistic tribe/clan-tribe edits bump the
tribe-assignment generation instead so the projection index is not
needlessly invalidated. Direct list replacement without a bump (tests,
harness scaffolding) still misses via the identity/length pair. In-place
field mutations that bypass both bumps would serve stale maps; all
production wait-relevant in-place mutations go through one of the two
bump paths.
"""

from __future__ import annotations

from typing import Any

_CACHE_ATTR = "_agent_wait_status_maps_cache"


def _wait_cache_key(
    app: Any,
    roster: list[Any] | tuple[Any, ...] | None,
) -> tuple[Any, ...]:
    """Return the O(1) cache key for *app*'s current wait inputs."""
    from sase.ace.tui.actions.agents._roster_generation import (
        get_roster_generation,
        get_tribe_assignment_generation,
    )

    roster_id: int | None = None
    roster_len = -1
    try:
        if roster is not None:
            roster_id = id(roster)
            roster_len = len(roster)
    except Exception:  # noqa: BLE001 - defensive cache key only.
        roster_id = None
        roster_len = -1
    return (
        get_roster_generation(app),
        get_tribe_assignment_generation(app),
        roster_id,
        roster_len,
    )


def _roster_for_app(app: Any) -> list[Any] | tuple[Any, ...] | None:
    """Return the roster list ``collect`` would scan for *app*."""
    for attr_name in ("_agents_with_children", "_agents"):
        try:
            roster = getattr(app, attr_name, None)
        except Exception:  # noqa: BLE001 - unmounted widgets have no app.
            continue
        if roster:
            return roster
    return None


def cached_agent_wait_status_maps_for_app(app: Any) -> Any | None:
    """Return *app*'s cached wait maps, building once per key.

    Returns ``None`` when *app* has no roster to scan. A miss delegates to
    :func:`collect_agent_wait_status_maps`, so the build stays in one place.
    """
    from sase.ace.tui._agent_completion_wait import collect_agent_wait_status_maps

    if app is None:
        return None
    roster = _roster_for_app(app)
    if not roster:
        return None
    key = _wait_cache_key(app, roster)
    try:
        cached = getattr(app, _CACHE_ATTR, None)
    except Exception:  # noqa: BLE001 - defensive cache read only.
        cached = None
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == key:
        return cached[1]
    maps = collect_agent_wait_status_maps(roster)
    try:
        setattr(app, _CACHE_ATTR, (key, maps))
    except (AttributeError, TypeError):
        pass
    return maps


__all__ = [
    "cached_agent_wait_status_maps_for_app",
]

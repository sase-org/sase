"""In-process freshness token for agent-name registry consumers."""

from __future__ import annotations

from threading import Lock

_LOCK = Lock()
_GENERATION = 0


def agent_name_registry_freshness_token() -> int:
    """Return the current in-process registry generation."""
    with _LOCK:
        return _GENERATION


def invalidate_agent_name_registry_freshness() -> int:
    """Bump the registry generation after a registry mutation."""
    global _GENERATION
    with _LOCK:
        _GENERATION += 1
        return _GENERATION


__all__ = [
    "agent_name_registry_freshness_token",
    "invalidate_agent_name_registry_freshness",
]

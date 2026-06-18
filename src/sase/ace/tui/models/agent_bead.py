"""TUI wrappers for inferring bead metadata from agent records."""

from __future__ import annotations

from collections import OrderedDict
import os
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Final

from sase.agent.bead_display import (
    derive_agent_bead_id_from_name,
    format_agent_bead_display_for_name,
)

from .agent import Agent

BEAD_DISPLAY_CACHE_MISS: Final = object()
_CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 256
BeadDisplayCacheKey = tuple[str, str | None, str | None]


class _BeadDisplayCache:
    """Small TTL-bounded cache for enriched bead display strings."""

    def __init__(
        self, *, ttl_seconds: float = _CACHE_TTL_SECONDS, max_entries: int
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[BeadDisplayCacheKey, tuple[float, str | None]] = (
            OrderedDict()
        )
        self._lock = RLock()

    def get(self, key: BeadDisplayCacheKey) -> str | None | object:
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return BEAD_DISPLAY_CACHE_MISS

            expires_at, value = entry
            if expires_at <= now:
                self._entries.pop(key, None)
                return BEAD_DISPLAY_CACHE_MISS

            self._entries.move_to_end(key)
            return value

    def set(self, key: BeadDisplayCacheKey, value: str | None) -> None:
        expires_at = monotonic() + self._ttl_seconds
        with self._lock:
            self._entries[key] = (expires_at, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_BEAD_DISPLAY_CACHE = _BeadDisplayCache(max_entries=_CACHE_MAX_ENTRIES)


def derive_agent_bead_id(agent: Agent) -> str | None:
    """Infer a bead id from an agent name written by ``sase bead work``."""
    return derive_agent_bead_id_from_name(agent.agent_name)


def cached_bead_display(agent: Agent) -> str | None | object:
    """Return cached enriched bead display text, if present and fresh."""
    key = _bead_display_cache_key(agent)
    if key is None:
        return None
    return _BEAD_DISPLAY_CACHE.get(key)


def should_resolve_bead_display(agent: Agent) -> bool:
    """Return True when the agent has an uncached bead display."""
    key = _bead_display_cache_key(agent)
    if key is None:
        return False
    return _BEAD_DISPLAY_CACHE.get(key) is BEAD_DISPLAY_CACHE_MISS


def resolve_bead_display(agent: Agent) -> str | None:
    """Resolve and cache enriched bead display text.

    This may touch bead stores and must only be called off the Textual event
    loop.
    """
    key = _bead_display_cache_key(agent)
    if key is None:
        return None

    display = format_agent_bead_display(agent, include_description=True)
    _BEAD_DISPLAY_CACHE.set(key, display)
    return display


def format_agent_bead_display(
    agent: Agent, *, include_description: bool = True
) -> str | None:
    """Format the bead metadata value for an agent details header."""
    return format_agent_bead_display_for_name(
        agent.agent_name,
        include_description=include_description,
        project_name=_agent_project_name(agent),
        workspace_dir=agent.workspace_dir,
    )


def _agent_project_name(agent: Agent) -> str | None:
    if not agent.project_file:
        return None
    project_name = Path(agent.project_file).parent.name
    return project_name or None


def _agent_workspace_cache_key(agent: Agent) -> str | None:
    if not agent.workspace_dir:
        return None
    return os.path.normpath(os.path.expanduser(agent.workspace_dir))


def _bead_display_cache_key(agent: Agent) -> BeadDisplayCacheKey | None:
    bead_id = derive_agent_bead_id(agent)
    if bead_id is None:
        return None
    return (bead_id, _agent_project_name(agent), _agent_workspace_cache_key(agent))

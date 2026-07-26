"""Cached bead-status enrichment for agent wait targets."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Final

from sase.bead.store_locator import bead_statuses_for_project

from .agent import Agent
from .agent_time import wait_display_agent

WAIT_BEAD_STATUS_CACHE_MISS: Final = object()
_CACHE_TTL_SECONDS = 15.0
_CACHE_MISS_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 256
WaitBeadStatusCacheKey = tuple[str, str]


class _WaitBeadStatusCache:
    """Small TTL-bounded cache for waited-for bead statuses."""

    def __init__(
        self,
        *,
        ttl_seconds: float = _CACHE_TTL_SECONDS,
        miss_ttl_seconds: float = _CACHE_MISS_TTL_SECONDS,
        max_entries: int,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._miss_ttl_seconds = miss_ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[
            WaitBeadStatusCacheKey,
            tuple[float, str | None],
        ] = OrderedDict()
        self._lock = RLock()

    def get(self, key: WaitBeadStatusCacheKey) -> str | None | object:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return WAIT_BEAD_STATUS_CACHE_MISS

            _, value = entry
            self._entries.move_to_end(key)
            return value

    def should_resolve(self, key: WaitBeadStatusCacheKey) -> bool:
        """Return whether *key* has no entry or needs TTL revalidation."""
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return True

            expires_at, _ = entry
            self._entries.move_to_end(key)
            return expires_at <= now

    def set(self, key: WaitBeadStatusCacheKey, value: str | None) -> None:
        ttl_seconds = self._miss_ttl_seconds if value is None else self._ttl_seconds
        expires_at = monotonic() + ttl_seconds
        with self._lock:
            self._entries[key] = (expires_at, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_WAIT_BEAD_STATUS_CACHE = _WaitBeadStatusCache(max_entries=_CACHE_MAX_ENTRIES)


def _cached_wait_bead_statuses(
    agent: Agent,
) -> tuple[tuple[str, str | None], ...] | None:
    """Return memory-only cached statuses for the bead waits rendered by *agent*."""
    wait_agent = wait_display_agent(agent)
    bead_ids = wait_agent.waiting_for_beads
    if not bead_ids:
        return None

    project_key = _wait_bead_project_key(agent, wait_agent)
    if project_key is None:
        return tuple((bead_id, None) for bead_id in bead_ids)

    result: list[tuple[str, str | None]] = []
    for bead_id in bead_ids:
        value = _WAIT_BEAD_STATUS_CACHE.get((project_key, bead_id))
        result.append(
            (
                bead_id,
                value if isinstance(value, str) else None,
            )
        )
    return tuple(result)


def resolve_wait_bead_statuses(
    agent: Agent,
) -> tuple[tuple[str, str | None], ...] | None:
    """Resolve statuses for the bead waits rendered by *agent*.

    This may touch bead stores and must only be called off the Textual event
    loop.
    """
    wait_agent = wait_display_agent(agent)
    bead_ids = wait_agent.waiting_for_beads
    if not bead_ids:
        return None

    project_key = _wait_bead_project_key(agent, wait_agent)
    if project_key is None:
        return tuple((bead_id, None) for bead_id in bead_ids)

    stale_ids = list(
        dict.fromkeys(
            bead_id
            for bead_id in bead_ids
            if _WAIT_BEAD_STATUS_CACHE.should_resolve((project_key, bead_id))
        )
    )
    if stale_ids:
        resolved = bead_statuses_for_project(project_key, stale_ids)
        for bead_id in stale_ids:
            status = resolved.get(bead_id) if resolved is not None else None
            _WAIT_BEAD_STATUS_CACHE.set((project_key, bead_id), status)

    return _cached_wait_bead_statuses(agent)


def _wait_bead_project_key(agent: Agent, wait_agent: Agent) -> str | None:
    project_file = wait_agent.project_file or agent.project_file
    if not project_file:
        return None
    project_key = Path(project_file).parent.name
    return project_key or None

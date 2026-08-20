"""Cached bead-status enrichment for agent wait targets."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Final

from sase.bead.store_locator import bead_statuses_for_project

from .agent import Agent, AgentType
from .agent_time import wait_display_agent

WAIT_BEAD_STATUS_CACHE_MISS: Final = object()
_CACHE_TTL_SECONDS = 15.0
_CACHE_MISS_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 256
WaitBeadStatusCacheKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class _WaitBeadStatusSnapshotEntry:
    """Memory-only cache state for one waited-on bead target."""

    bead_id: str
    status: str | None
    is_cold: bool = False


@dataclass(frozen=True, slots=True)
class WaitBeadStatusSnapshot:
    """Memory-only waited-bead statuses, preserving cold versus unknown."""

    entries: tuple[_WaitBeadStatusSnapshotEntry, ...]

    def entry_for(self, bead_id: str) -> _WaitBeadStatusSnapshotEntry | None:
        """Return the entry for *bead_id*, if the rendered wait references it."""
        for entry in self.entries:
            if entry.bead_id == bead_id:
                return entry
        return None

    def status_pairs(
        self, *, cold_as_unknown: bool = True
    ) -> tuple[tuple[str, str | None], ...]:
        """Return the legacy ``(bead_id, status)`` detail-header shape."""
        return tuple(
            (entry.bead_id, None if entry.is_cold and cold_as_unknown else entry.status)
            for entry in self.entries
        )

    def projection_key(self) -> tuple[tuple[str, str | None, bool], ...]:
        """Return the cache-visible state used for warmup change detection."""
        return tuple(
            (entry.bead_id, entry.status, entry.is_cold) for entry in self.entries
        )


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


def cached_wait_bead_status_snapshot(
    agent: Agent,
) -> WaitBeadStatusSnapshot | None:
    """Return memory-only cached statuses for bead waits rendered by *agent*."""
    wait_agent = wait_display_agent(agent)
    bead_ids = wait_agent.waiting_for_beads
    if not bead_ids:
        return None

    project_key = _wait_bead_project_key(agent, wait_agent)
    if project_key is None:
        return WaitBeadStatusSnapshot(
            tuple(
                _WaitBeadStatusSnapshotEntry(bead_id=bead_id, status=None)
                for bead_id in bead_ids
            )
        )

    result: list[_WaitBeadStatusSnapshotEntry] = []
    for bead_id in bead_ids:
        value = _WAIT_BEAD_STATUS_CACHE.get((project_key, bead_id))
        if value is WAIT_BEAD_STATUS_CACHE_MISS:
            result.append(
                _WaitBeadStatusSnapshotEntry(
                    bead_id=bead_id,
                    status=None,
                    is_cold=True,
                )
            )
        else:
            result.append(
                _WaitBeadStatusSnapshotEntry(
                    bead_id=bead_id,
                    status=value if isinstance(value, str) else None,
                )
            )
    return WaitBeadStatusSnapshot(tuple(result))


def _cached_wait_bead_statuses(
    agent: Agent,
) -> tuple[tuple[str, str | None], ...] | None:
    """Return the legacy memory-only waited-bead status shape."""
    snapshot = cached_wait_bead_status_snapshot(agent)
    return snapshot.status_pairs() if snapshot is not None else None


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

    warm_wait_bead_statuses((agent,))

    return _cached_wait_bead_statuses(agent)


def should_resolve_wait_bead_statuses(agent: Agent) -> bool:
    """Return whether any waited-on bead status needs cache warmup."""
    wait_agent = wait_display_agent(agent)
    bead_ids = wait_agent.waiting_for_beads
    if not bead_ids:
        return False
    project_key = _wait_bead_project_key(agent, wait_agent)
    if project_key is None:
        return False
    return any(
        _WAIT_BEAD_STATUS_CACHE.should_resolve((project_key, bead_id))
        for bead_id in bead_ids
    )


def warm_wait_bead_statuses(
    agents: Iterable[Agent],
) -> set[tuple[AgentType, str, str | None]]:
    """Resolve stale waited-bead statuses in project batches.

    Returns identities whose cache-visible projection changed. Store lookups
    happen here, so callers must run this off the Textual event loop.
    """
    agent_list = list(agents)
    before = {
        agent.identity: snapshot.projection_key()
        for agent in agent_list
        if (snapshot := cached_wait_bead_status_snapshot(agent)) is not None
    }
    project_bead_ids: dict[str, OrderedDict[str, None]] = {}
    for agent in agent_list:
        wait_agent = wait_display_agent(agent)
        project_key = _wait_bead_project_key(agent, wait_agent)
        if project_key is None:
            continue
        for bead_id in dict.fromkeys(wait_agent.waiting_for_beads):
            key = (project_key, bead_id)
            if not _WAIT_BEAD_STATUS_CACHE.should_resolve(key):
                continue
            project_bead_ids.setdefault(project_key, OrderedDict()).setdefault(
                bead_id,
                None,
            )

    for project_key, bead_ids_by_id in project_bead_ids.items():
        bead_ids = list(bead_ids_by_id)
        try:
            resolved = bead_statuses_for_project(project_key, bead_ids)
        except Exception:
            resolved = None
        for bead_id in bead_ids:
            status = resolved.get(bead_id) if resolved is not None else None
            _WAIT_BEAD_STATUS_CACHE.set((project_key, bead_id), status)

    changed: set[tuple[AgentType, str, str | None]] = set()
    for agent in agent_list:
        previous = before.get(agent.identity)
        if previous is None:
            continue
        snapshot = cached_wait_bead_status_snapshot(agent)
        current = snapshot.projection_key() if snapshot is not None else None
        if current != previous:
            changed.add(agent.identity)
    return changed


def _wait_bead_project_key(agent: Agent, wait_agent: Agent) -> str | None:
    project_file = wait_agent.project_file or agent.project_file
    if not project_file:
        return None
    project_key = Path(project_file).parent.name
    return project_key or None


__all__ = [
    "WAIT_BEAD_STATUS_CACHE_MISS",
    "WaitBeadStatusCacheKey",
    "WaitBeadStatusSnapshot",
    "cached_wait_bead_status_snapshot",
    "resolve_wait_bead_statuses",
    "should_resolve_wait_bead_statuses",
    "warm_wait_bead_statuses",
]

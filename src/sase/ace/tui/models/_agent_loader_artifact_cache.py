"""Single-generation cache for warm bounded artifact-index snapshots."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from threading import RLock
from typing import TYPE_CHECKING

from sase.core.agent_scan_list_wire import AgentArtifactListSnapshotWire

from ._agent_loader_artifact_state import AgentLoadState

ArtifactIndexSignature = tuple[
    tuple[str, int | None, int | None],
    tuple[str, int | None, int | None],
]
#: Exact query keys for the single compact TUI snapshot generation.
ArtifactSnapshotCacheKey = tuple[str, str, str, str, str]


@dataclass(frozen=True)
class _ArtifactSnapshotCacheStats:
    """Process-local diagnostics for the TUI artifact snapshot cache."""

    hits: int = 0
    misses: int = 0
    stores: int = 0
    mutation_refusals: int = 0
    evictions: int = 0
    bypasses: int = 0


def _cache_hit_load_state(state: AgentLoadState) -> AgentLoadState:
    return replace(
        state,
        marker_signatures_checked=0,
        rows_repaired=0,
        rows_discovered=0,
        rows_removed=0,
        record_json_decoded=0,
    )


class _ArtifactSnapshotCache[SnapshotT]:
    """Mtime/size-guarded cache for one warm bounded index snapshot.

    A single retained generation: every ``put`` with a different key
    evicts the previous generation (counted as an eviction), so retained
    graphs cannot grow with the number of filter, root, window, or
    scan-option changes. Same-key lock-busy reads may still serve the one
    stale generation; a different key never does.
    """

    def __init__(self, *, max_entries: int) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[
            ArtifactSnapshotCacheKey,
            tuple[ArtifactIndexSignature, SnapshotT, AgentLoadState],
        ] = OrderedDict()
        self._stats = _ArtifactSnapshotCacheStats()
        self._lock = RLock()
        self._request_generation = 0

    def begin_request(self) -> int:
        """Return a token that lets only the latest query publish a result."""
        with self._lock:
            self._request_generation += 1
            return self._request_generation

    def get(
        self,
        key: ArtifactSnapshotCacheKey,
        signature: ArtifactIndexSignature,
    ) -> tuple[SnapshotT, AgentLoadState] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._stats = replace(self._stats, misses=self._stats.misses + 1)
                return None
            cached_signature, snapshot, state = entry
            if cached_signature != signature:
                # Keep the last good snapshot for lock-busy stale reads.
                self._entries.move_to_end(key)
                self._stats = replace(self._stats, misses=self._stats.misses + 1)
                return None
            self._entries.move_to_end(key)
            self._stats = replace(self._stats, hits=self._stats.hits + 1)
            return snapshot, _cache_hit_load_state(state)

    def get_stale(
        self,
        key: ArtifactSnapshotCacheKey,
    ) -> tuple[SnapshotT, AgentLoadState] | None:
        """Return the last good snapshot for *key*, ignoring index signature."""

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            _cached_signature, snapshot, state = entry
            self._entries.move_to_end(key)
            self._stats = replace(self._stats, hits=self._stats.hits + 1)
            return snapshot, _cache_hit_load_state(state)

    def put(
        self,
        key: ArtifactSnapshotCacheKey,
        signature: ArtifactIndexSignature,
        snapshot: SnapshotT,
        state: AgentLoadState,
        *,
        request_generation: int | None = None,
    ) -> bool:
        with self._lock:
            if (
                request_generation is not None
                and request_generation != self._request_generation
            ):
                return False
            self._entries[key] = (signature, snapshot, state)
            self._entries.move_to_end(key)
            stats = replace(self._stats, stores=self._stats.stores + 1)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
                stats = replace(stats, evictions=stats.evictions + 1)
            self._stats = stats
            return True

    def record_mutation_refusal(self) -> None:
        with self._lock:
            self._stats = replace(
                self._stats,
                mutation_refusals=self._stats.mutation_refusals + 1,
            )

    def record_bypass(self) -> None:
        with self._lock:
            self._stats = replace(self._stats, bypasses=self._stats.bypasses + 1)

    def clear(self) -> None:
        with self._lock:
            # Invalidate any query still running outside the cache lock.
            self._request_generation += 1
            self._entries.clear()
            self._stats = _ArtifactSnapshotCacheStats()

    def stats(self) -> _ArtifactSnapshotCacheStats:
        with self._lock:
            return self._stats


ARTIFACT_SNAPSHOT_CACHE: _ArtifactSnapshotCache[AgentArtifactListSnapshotWire] = (
    _ArtifactSnapshotCache(max_entries=1)
)

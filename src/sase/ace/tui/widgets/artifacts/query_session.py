"""Shared asynchronous Rust query evaluation for flat Artifacts panes."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from textual.worker import Worker, WorkerState

from sase.ace.query.profile_reference import canonical_query_for_profile
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryCacheKey,
    ArtifactQueryIndex,
    ArtifactQueryResult,
    evaluate_artifact_query_many,
)


class ArtifactQuerySession:
    """Bounded, generation-keyed query-result cache with worker coalescing."""

    def __init__(
        self,
        owner: Any,
        *,
        group: str,
        on_current_result: Callable[[ArtifactQueryResult], None],
        cache_size: int = 32,
    ) -> None:
        self._owner = owner
        self._group = group
        self._on_current_result = on_current_result
        self._cache_size = max(1, cache_size)
        self._cache: OrderedDict[ArtifactQueryCacheKey, ArtifactQueryResult] = (
            OrderedDict()
        )
        self._workers: dict[Worker[Any], ArtifactQueryCacheKey] = {}
        self._in_flight: dict[ArtifactQueryCacheKey, Worker[Any]] = {}
        self._pending: tuple[str, ArtifactQueryIndex, ArtifactQueryCacheKey] | None = (
            None
        )
        self._current_key: ArtifactQueryCacheKey | None = None

    def clear(self) -> None:
        """Forget cached/in-flight work, cancelling live workers."""

        for worker in tuple(self._workers):
            if not worker.is_finished:
                worker.cancel()
        self._cache.clear()
        self._workers.clear()
        self._in_flight.clear()
        self._pending = None
        self._current_key = None

    def remember(self, result: ArtifactQueryResult) -> None:
        """Seed the cache with a result produced by a snapshot worker."""

        self._remember(result)

    def result(
        self,
        query: str,
        index: ArtifactQueryIndex,
        *,
        active: bool = True,
    ) -> ArtifactQueryResult | None:
        """Return a cached result or schedule one off-thread."""

        canonical_query = canonical_query_for_profile(query, index.profile)
        key = index.cache_key(canonical_query)
        if active:
            self._current_key = key

        cached = self._cache.get(key)
        if cached is not None:
            if active:
                self._pending = None
            self._cache.move_to_end(key)
            return cached

        if key in self._in_flight:
            if active:
                self._pending = None
            return None

        if self._workers:
            self._pending = (query, index, key)
            return None

        self._start(query, index, key)
        return None

    def _start(
        self,
        query: str,
        index: ArtifactQueryIndex,
        key: ArtifactQueryCacheKey,
    ) -> None:
        """Launch the sole live worker for this pane session."""

        def task() -> ArtifactQueryResult:
            return evaluate_artifact_query_many(
                query,
                index,
                canonical_query=key.canonical_query,
            )

        worker = self._owner.run_worker(
            task,
            thread=True,
            group=self._group,
            exclusive=False,
            exit_on_error=False,
        )
        self._workers[worker] = key
        self._in_flight[key] = worker

    def handle_worker_state_changed(self, event: Worker.StateChanged) -> bool:
        """Handle a Textual worker event owned by this session."""

        key = self._workers.get(event.worker)
        if key is None:
            return False
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return True

        self._workers.pop(event.worker, None)
        if self._in_flight.get(key) is event.worker:
            self._in_flight.pop(key, None)
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, ArtifactQueryResult) and result.cache_key == key:
                self._remember(result)
                if key == self._current_key:
                    self._on_current_result(result)

        pending = self._pending
        self._pending = None
        if pending is not None:
            query, index, pending_key = pending
            cached = self._cache.get(pending_key)
            if cached is not None:
                self._cache.move_to_end(pending_key)
                if pending_key == self._current_key:
                    self._on_current_result(cached)
            else:
                self._start(query, index, pending_key)
        return True

    def _remember(self, result: ArtifactQueryResult) -> None:
        self._cache[result.cache_key] = result
        self._cache.move_to_end(result.cache_key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


__all__ = ["ArtifactQuerySession"]

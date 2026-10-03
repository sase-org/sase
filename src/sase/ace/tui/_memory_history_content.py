"""Version-body and comparison queries for ACE memory history.

One section of :class:`sase.ace.tui.memory_history.AceMemoryHistory`:
the content-addressed body and comparison LRUs. Committed bodies cache
by blob OID; committed pairs cache by blob pair; anything involving now
or staged always refetches. Import from
:mod:`sase.ace.tui.memory_history`, not from here.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui._memory_history_base import HistoryQueryBase
from sase.ace.tui.util.trace import tui_trace

#: Bounded content caches (guidance sizes from the epic plan §5.2).
_BODY_LRU_SIZE = 128
_COMPARISON_LRU_SIZE = 64

_LIVE_VERSIONS = frozenset({"", "now", "stg", "staged", "uncommitted"})


class ContentQueries(HistoryQueryBase):
    """Content-addressed body and comparison queries."""

    @staticmethod
    def _is_live_version(version: str) -> bool:
        """Return whether *version* names now/staged (never cached)."""
        return str(version).strip().lower() in _LIVE_VERSIONS

    def version_body(self, scope: Any, selector: str, version: str) -> dict[str, Any]:
        """Return one version wire with its body.

        Committed bodies cache by blob OID in a 128-entry LRU; now
        and staged always refetch and are never cached.
        """
        scope_key = str(getattr(scope, "scope_key", "") or "")
        version_arg = str(version)
        with tui_trace("memory.history.query", op="version_body") as extra:
            if self._is_live_version(version_arg):
                extra["hit"] = False
                return dict(
                    self._service.version(
                        scope, selector, version_arg, include_body=True
                    )
                )
            memo_key = (scope_key, str(selector), version_arg)
            with self._lock:
                blob = self._known_blobs.get(memo_key)
                if blob is not None:
                    cached = self._body_lru.get((scope_key, blob))
                    if cached is not None:
                        self._body_lru.move_to_end((scope_key, blob))
                        extra["hit"] = True
                        return cached
            extra["hit"] = False
            owner, flight = self._join_flight(("body", *memo_key))
            if not owner:
                flight.event.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            try:
                wire = dict(
                    self._service.version(
                        scope, selector, version_arg, include_body=True
                    )
                )
            except Exception as exc:
                flight.error = exc
                self._settle_flight(("body", *memo_key), flight)
                raise
            learned = self._learn_blob(scope_key, str(selector), version_arg, wire)
            if learned is not None:
                with self._lock:
                    self._body_lru[(scope_key, learned)] = wire
                    self._body_lru.move_to_end((scope_key, learned))
                    while len(self._body_lru) > _BODY_LRU_SIZE:
                        self._body_lru.popitem(last=False)
            self._settle_flight(("body", *memo_key), flight, result=wire)
            return wire

    def _learn_blob(
        self, scope_key: str, selector: str, version: str, wire: dict[str, Any]
    ) -> str | None:
        """Remember a version wire's blob OID; None when unknown."""
        try:
            blob = wire.get("blob_oid")
            blob_str = str(blob) if isinstance(blob, str) and blob else None
        except AttributeError:
            blob_str = None
        with self._lock:
            self._known_blobs[(scope_key, selector, str(version))] = blob_str
        return blob_str

    def _blob_for(
        self, scope: Any, scope_key: str, selector: str, version: str
    ) -> str | None:
        """Return the known blob OID for a version, learning it if needed."""
        with self._lock:
            if (scope_key, selector, str(version)) in self._known_blobs:
                return self._known_blobs[(scope_key, selector, str(version))]
        try:
            wire = dict(
                self._service.version(scope, selector, str(version), include_body=False)
            )
        except Exception:
            with self._lock:
                self._known_blobs[(scope_key, selector, str(version))] = None
            return None
        return self._learn_blob(scope_key, selector, str(version), wire)

    def comparison(
        self,
        scope: Any,
        selector: str,
        base: str,
        target: str,
        *,
        target_selector: str | None = None,
    ) -> dict[str, Any]:
        """Return the word-diff comparison wire for two versions.

        Committed pairs cache by ``(scope, base blob, target blob)``
        in a 64-entry LRU. Anything involving now or staged always
        refetches and is never cached.
        """
        scope_key = str(getattr(scope, "scope_key", "") or "")
        target_sel = (
            str(target_selector) if target_selector is not None else str(selector)
        )
        with tui_trace("memory.history.query", op="comparison") as extra:
            if self._is_live_version(base) or self._is_live_version(target):
                extra["hit"] = False
                compared = self._service.compare(
                    scope, str(selector), str(base), target_sel, str(target)
                )
                return dict(compared.get("comparison", compared))
            base_blob = self._blob_for(scope, scope_key, str(selector), str(base))
            target_blob = self._blob_for(scope, scope_key, target_sel, str(target))
            if base_blob is None or target_blob is None:
                extra["hit"] = False
                compared = self._service.compare(
                    scope, str(selector), str(base), target_sel, str(target)
                )
                return dict(compared.get("comparison", compared))
            cache_key = (scope_key, base_blob, target_blob)
            with self._lock:
                cached = self._comparison_lru.get(cache_key)
                if cached is not None:
                    self._comparison_lru.move_to_end(cache_key)
                    extra["hit"] = True
                    return cached
            extra["hit"] = False
            owner, flight = self._join_flight(("comparison", *cache_key))
            if not owner:
                flight.event.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            try:
                compared = self._service.compare(
                    scope, str(selector), str(base), target_sel, str(target)
                )
                wire = dict(compared.get("comparison", compared))
            except Exception as exc:
                flight.error = exc
                self._settle_flight(("comparison", *cache_key), flight)
                raise
            with self._lock:
                self._comparison_lru[cache_key] = wire
                self._comparison_lru.move_to_end(cache_key)
                while len(self._comparison_lru) > _COMPARISON_LRU_SIZE:
                    self._comparison_lru.popitem(last=False)
            self._settle_flight(("comparison", *cache_key), flight, result=wire)
            return wire

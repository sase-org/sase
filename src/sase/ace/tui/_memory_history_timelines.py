"""Timeline queries for ACE memory history.

One section of :class:`sase.ace.tui.memory_history.AceMemoryHistory`:
the stale-while-revalidate timeline memo plus its background
revalidation. Import from :mod:`sase.ace.tui.memory_history`, not from
here.
"""

from __future__ import annotations

import threading
from typing import Any

from sase.ace.tui._memory_history_base import HistoryQueryBase, TimelineEntry
from sase.ace.tui.util.trace import tui_trace

#: A timeline memo older than this revalidates in the background while
#: the stale snapshot still renders immediately.
_TIMELINE_STALE_S = 2.0


def _timeline_fingerprint(wire: dict[str, Any]) -> tuple[Any, ...]:
    """Return a cheap change marker for a timeline wire dict."""
    try:
        versions = wire.get("versions", ())
        committed = [
            row
            for row in versions
            if isinstance(row, dict) and int(row.get("ordinal", 0) or 0) > 0
        ]
        newest: dict[str, Any] = {}
        for row in committed:
            try:
                ordinal = int(row.get("ordinal", 0) or 0)
            except (TypeError, ValueError):
                continue
            try:
                best = int(newest.get("ordinal", 0) or 0)
            except (TypeError, ValueError):
                best = 0
            if ordinal >= best:
                newest = row
        return (
            str(wire.get("state", "") or ""),
            str(wire.get("tip", "") or wire.get("head", "") or ""),
            len(committed),
            int(newest.get("ordinal", 0) or 0),
            str(newest.get("commit", "") or ""),
            str(newest.get("blob_oid", "") or ""),
        )
    except Exception:
        return ("unavailable",)


class TimelineQueries(HistoryQueryBase):
    """Stale-while-revalidate timeline queries."""

    @staticmethod
    def _fingerprint(wire: dict[str, Any]) -> tuple[Any, ...]:
        """Return the timeline change marker sections memoize against."""
        return _timeline_fingerprint(wire)

    def timeline(
        self, scope: Any, selector: str, *, include_hidden: bool = False
    ) -> dict[str, Any]:
        """Return one subject's timeline wire dict (stale-while-revalidate).

        *selector* is the core selector (panel selectors are
        translated before this call). A memo hit renders immediately;
        when the entry is older than about 2 s a background
        revalidation refreshes the memo without blocking this call.
        """
        scope_key = str(getattr(scope, "scope_key", "") or "")
        key = (scope_key, str(selector), bool(include_hidden))
        with tui_trace("memory.history.query", op="timeline") as extra:
            with self._lock:
                entry = self._timeline_memo.get(key)
            if entry is not None:
                extra["hit"] = True
                if self._clock() - entry.validated_at > _TIMELINE_STALE_S:
                    self._spawn_timeline_revalidation(key, scope, str(selector))
                return entry.wire
            extra["hit"] = False
            return self._fetch_timeline(key, scope, str(selector), bool(include_hidden))

    def _fetch_timeline(
        self,
        key: tuple[str, str, bool],
        scope: Any,
        selector: str,
        include_hidden: bool,
    ) -> dict[str, Any]:
        """Fetch and memoize one timeline through the single-flight."""
        owner, flight = self._join_flight(("timeline", *key))
        if not owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            return flight.result
        try:
            wire = dict(
                self._service.timeline(scope, selector, include_hidden=include_hidden)
            )
        except Exception as exc:
            flight.error = exc
            self._settle_flight(("timeline", *key), flight)
            raise
        entry = TimelineEntry(
            wire=wire,
            fingerprint=_timeline_fingerprint(wire),
            validated_at=self._clock(),
        )
        with self._lock:
            self._timeline_memo[key] = entry
        self._settle_flight(("timeline", *key), flight, result=wire)
        return wire

    def _spawn_timeline_revalidation(
        self, key: tuple[str, str, bool], scope: Any, selector: str
    ) -> None:
        """Refresh a stale memo entry off-thread without blocking."""
        with self._lock:
            if key in self._revalidating or ("timeline", *key) in self._flights:
                return
            self._revalidating.add(key)

        def _revalidate() -> None:
            try:
                wire = dict(
                    self._service.timeline(scope, selector, include_hidden=key[2])
                )
            except Exception:
                return
            finally:
                with self._lock:
                    self._revalidating.discard(key)
            try:
                entry = TimelineEntry(
                    wire=wire,
                    fingerprint=_timeline_fingerprint(wire),
                    validated_at=self._clock(),
                )
            except Exception:
                return
            with self._lock:
                self._timeline_memo[key] = entry

        thread = threading.Thread(
            target=_revalidate,
            name="ace-memory-history-revalidate",
            daemon=True,
        )
        thread.start()

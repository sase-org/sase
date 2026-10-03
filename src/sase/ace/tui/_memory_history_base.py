"""Shared state and single-flight core for ACE memory-history queries.

Holds the pieces every memory-history query section needs: the memo
store plus single-flight board (:class:`HistoryQueryBase`) and the
records shared by more than one section (:class:`TimelineEntry` for
the timeline memo, :class:`_Flight` for in-flight calls). The section
mixins (``_memory_history_timelines``, ``_memory_history_content``,
``_memory_history_collections``, ``_memory_history_tokens``) subclass
:class:`HistoryQueryBase` (``CollectionQueries`` extends ``TokenQueries``
for its change-token memos), so every query shares one memo store
without importing a ``_``-prefixed name across modules. Import from
:mod:`sase.ace.tui.memory_history`, not from here.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.memory.history.service import shared_history_service


@dataclass
class TimelineEntry:
    """One memoized timeline: the wire plus its freshness markers."""

    wire: dict[str, Any]
    fingerprint: tuple[Any, ...]
    validated_at: float


@dataclass
class _Flight:
    """One in-flight single-flight call shared by concurrent waiters."""

    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None


class HistoryQueryBase:
    """Memo store and single-flight board for memory-history queries."""

    def __init__(
        self,
        service: Any | None = None,
        *,
        _clock: Callable[[], float] | None = None,
    ) -> None:
        import time as _time

        self._service = service if service is not None else shared_history_service()
        self._clock = _clock or _time.monotonic
        self._lock = threading.RLock()
        self._timeline_memo: dict[tuple[str, str, bool], TimelineEntry] = {}
        self._flights: dict[tuple[Any, ...], _Flight] = {}
        self._revalidating: set[tuple[str, str, bool]] = set()
        self._body_lru: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._comparison_lru: OrderedDict[tuple[str, str, str], dict[str, Any]] = (
            OrderedDict()
        )
        self._known_blobs: dict[tuple[str, str, str], str | None] = {}
        self._subjects_memo: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
        self._feed_memo: dict[
            tuple[str, ...], tuple[tuple[Any, ...], dict[str, Any]]
        ] = {}
        self._seen_tokens: dict[tuple[str, str], tuple[Any, ...]] = {}
        self._git_dirs: dict[str, Path | None] = {}

    @property
    def service(self) -> Any:
        """Return the wrapped (shared) history service."""
        return self._service

    # --- scopes -----------------------------------------------------

    def scope_for_ref(self, ref: Any) -> Any | None:
        """Return the history scope for a panel scope-ring entry.

        Project entries build from ``content_root``; the home entry
        uses the chezmoi home scope (``None`` when home has no VCS).
        ``None`` when the scope cannot be built.
        """
        try:
            kind = getattr(ref, "kind", "project")
            if kind == "home":
                try:
                    return self._service.home_scope()
                except Exception:
                    return None
            content_root = getattr(ref, "content_root", "") or ""
            if not content_root:
                return None
            return self._service.project_scope(Path(content_root))
        except Exception:
            return None

    # --- single-flight ----------------------------------------------

    def _join_flight(self, key: tuple[Any, ...]) -> tuple[bool, _Flight]:
        """Enter the single-flight for *key*; True when this call owns it."""
        with self._lock:
            flight = self._flights.get(key)
            if flight is not None:
                return (False, flight)
            flight = _Flight()
            self._flights[key] = flight
            return (True, flight)

    def _settle_flight(
        self, key: tuple[Any, ...], flight: _Flight, *, result: Any = None
    ) -> None:
        """Publish a flight result (or ``flight.error``) and wake waiters."""
        with self._lock:
            self._flights.pop(key, None)
            flight.result = result
            flight.event.set()

    # --- warm-up -----------------------------------------------------------

    def warm(self, scopes: list[Any]) -> dict[str, bool]:
        """Sync each scope once; per-scope failures report False, never raise."""
        outcome: dict[str, bool] = {}
        for scope in scopes:
            key = str(getattr(scope, "scope_key", "") or "")
            try:
                self._service.sync(scope)
            except Exception:
                outcome[key] = False
            else:
                outcome[key] = True
        return outcome

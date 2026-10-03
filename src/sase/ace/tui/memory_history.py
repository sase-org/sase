"""App-scoped memory-history queries for ACE.

One :class:`AceMemoryHistory` per ACE app wraps the process-wide
:func:`~sase.memory.history.service.shared_history_service`. Every
method blocks, so callers run them in thread workers or pump-free
tasks, never on the event loop or a keystroke path (epic design
``plan:202610/memory_history_tui.md`` §5.2).

- Timelines use stale-while-revalidate plus explicit invalidation
  plus stat-only change tokens; the UI repaints only when the
  fingerprint changed.
- Bodies and committed comparisons are cached by blob OID, so those
  caches can never go stale. Anything involving now or staged is
  never cached.
- Concurrent requests for the same key share one in-flight call
  (single-flight).
- No query calls ``sync()`` first: core queries sync internally.
  Only the quiet-time warm-up syncs.

This module is the public face of five private siblings:
:mod:`sase.ace.tui._memory_history_base` (memo store, single-flight,
scopes, warm-up), ``_memory_history_timelines`` (stale-while-revalidate
timelines), ``_memory_history_content`` (body/comparison LRUs),
``_memory_history_collections`` (subjects/feed memos), and
``_memory_history_tokens`` (change tokens and invalidation). Import
from here, not from them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui._memory_history_collections import CollectionQueries
from sase.ace.tui._memory_history_content import ContentQueries
from sase.ace.tui._memory_history_timelines import TimelineQueries
from sase.ace.tui._memory_history_tokens import TokenQueries
from sase.memory.history.service import shared_history_service


class AceMemoryHistory(
    TimelineQueries, ContentQueries, CollectionQueries, TokenQueries
):
    """Memoized, single-flight history queries for one ACE app."""


def ace_memory_history(app: Any) -> AceMemoryHistory:
    """Return the app-scoped :class:`AceMemoryHistory`, creating it lazily.

    Stored on the app, so tests get a fresh instance per app. Wraps
    the process-wide shared service.
    """
    history = getattr(app, "_ace_memory_history", None)
    if isinstance(history, AceMemoryHistory):
        return history
    history = AceMemoryHistory()
    try:
        app._ace_memory_history = history
    except AttributeError:
        pass
    return history


def schedule_history_warmup(app: Any, *, scopes: list[Any] | None = None) -> bool:
    """Schedule the once-per-app history warm-up off-thread; never blocks.

    Syncs the launch project scope and home after ACE's startup
    stopwatch ends, so the first ``H`` never pays the cold index
    cost. First paint never waits on it: this only queues a thread
    worker and returns.
    """
    if bool(getattr(app, "_history_warm_scheduled", False)):
        return False
    try:
        app._history_warm_scheduled = True
    except AttributeError:
        return False

    def _scopes() -> list[Any]:
        if scopes is not None:
            return list(scopes)
        found: list[Any] = []
        try:
            service = shared_history_service()
        except Exception:
            return found
        try:
            found.append(service.project_scope(Path.cwd()))
        except Exception:
            pass
        try:
            home = service.home_scope()
        except Exception:
            home = None
        if home is not None:
            found.append(home)
        return found

    def task() -> None:
        try:
            history = ace_memory_history(app)
        except Exception:
            return
        try:
            history.warm(_scopes())
        except Exception:
            pass

    try:
        app.run_worker(
            task,
            thread=True,
            exclusive=False,
            group="ace-memory-history-warm",
            exit_on_error=False,
        )
    except Exception:
        return False
    return True


__all__ = [
    "AceMemoryHistory",
    "ace_memory_history",
    "schedule_history_warmup",
]

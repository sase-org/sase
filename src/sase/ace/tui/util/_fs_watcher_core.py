"""Watcher core state: init, coalesce timing, and dispatch gating."""

from __future__ import annotations

import inspect
import logging
import select
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ._fs_watcher_common import (
    IN_CLOSE_WRITE,
    IN_CREATE,
    IN_DELETE,
    IN_DELETE_SELF,
    IN_MODIFY,
    IN_MOVED_FROM,
    IN_MOVED_TO,
    IN_MOVE_SELF,
    is_ignored_watch_name,
)

log = logging.getLogger(__name__)

DEFAULT_EVENT_MASK = (
    IN_MODIFY
    | IN_CLOSE_WRITE
    | IN_MOVED_FROM
    | IN_MOVED_TO
    | IN_CREATE
    | IN_DELETE
    | IN_DELETE_SELF
    | IN_MOVE_SELF
)

DEFAULT_COALESCE_S = 0.2
DEFAULT_DISPATCH_DEADLINE_S = 1.0
PIPE_IDLE_FALLBACK_S = 0.5


def _callback_accepts_positional(callback: Callable[..., object]) -> bool:
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False


class WatcherCore:
    """Core watcher state shared by the watch-table and runner mixins.

    Construction collects watch paths but does not touch disk; subclass
    ``start`` spins up the worker thread and ``stop`` tears it down.
    """

    def __init__(
        self,
        paths: list[Path],
        on_change: Callable[..., None],
        schedule_callback: Callable[[Callable[[], None]], object],
        *,
        mask: int = DEFAULT_EVENT_MASK,
        coalesce_s: float = DEFAULT_COALESCE_S,
        deadline_s: float = DEFAULT_DISPATCH_DEADLINE_S,
        is_relevant: Callable[[Path], bool] | None = None,
        clock: Callable[[], float] | None = None,
        selector: Callable[..., tuple[list[int], list[int], list[int]]] | None = None,
    ) -> None:
        self._paths: list[Path] = [Path(p) for p in paths]
        self._on_change = on_change
        self._on_change_accepts_paths = _callback_accepts_positional(on_change)
        self._schedule_callback = schedule_callback
        self._mask = mask
        self._coalesce_s = coalesce_s
        self._deadline_s = deadline_s
        self._is_relevant = is_relevant
        self._clock = clock or time.monotonic
        self._select = selector or select.select
        self._fd: int = -1
        self._watch_paths_by_wd: dict[int, Path] = {}
        self._wd_by_path: dict[str, int] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Self-pipe ends used to wake the worker's ``select()`` on stop.
        # Created in ``start``; ``-1`` when unavailable or stopped.
        self._wake_r: int = -1
        self._wake_w: int = -1
        self._first_pending_mono: float = 0.0
        self._last_event_mono: float = 0.0
        self._pending_paths: set[Path] = set()
        self._lock = threading.Lock()
        self._watch_lock = threading.Lock()
        self._watch_cap_warning_emitted = False
        self._stat_select_timeout_wakeups = 0
        self._stat_inotify_readable_wakeups = 0
        self._stat_raw_events = 0
        self._stat_accepted_events = 0
        self._stat_ignored_events = 0
        self._stat_rejected_events = 0
        self._stat_queued_dispatches = 0
        self._stat_ui_dispatches = 0
        self._stat_dispatched_paths = 0

    def stats(self) -> dict[str, int]:
        """Return inexpensive wakeup/dispatch counters for this instance."""
        return {
            "select_timeout_wakeups": self._stat_select_timeout_wakeups,
            "inotify_readable_wakeups": self._stat_inotify_readable_wakeups,
            "raw_events": self._stat_raw_events,
            "accepted_events": self._stat_accepted_events,
            "ignored_events": self._stat_ignored_events,
            "rejected_events": self._stat_rejected_events,
            "queued_dispatches": self._stat_queued_dispatches,
            "ui_dispatches": self._stat_ui_dispatches,
            "dispatched_paths": self._stat_dispatched_paths,
        }

    def _pending_select_timeout(self) -> float | None:
        """Return the next ``select`` timeout from pending coalescing state.

        Idle with a stop self-pipe blocks until an event. Idle without a
        pipe uses :data:`PIPE_IDLE_FALLBACK_S`. Pending events use the
        sooner of the trailing coalesce window and the hard dispatch
        deadline measured from the first relevant path.
        """
        with self._lock:
            first = self._first_pending_mono
            last = self._last_event_mono
        if first == 0.0:
            if self._wake_r >= 0:
                return None
            return PIPE_IDLE_FALLBACK_S
        now = self._clock()
        remaining_coalesce = self._coalesce_s - (now - last)
        remaining_deadline = self._deadline_s - (now - first)
        remaining = min(remaining_coalesce, remaining_deadline)
        return remaining if remaining > 0.0 else 0.0

    def _note_relevant_paths(self, paths: set[Path]) -> None:
        """Arm coalesced dispatch for *paths* without resetting the deadline."""
        now = self._clock()
        with self._lock:
            if self._first_pending_mono == 0.0:
                self._first_pending_mono = now
            self._last_event_mono = now
            self._pending_paths.update(paths)

    def _path_is_consumed(self, path: Path) -> bool:
        """Return whether *path* should arm a UI dispatch."""
        if is_ignored_watch_name(path.name):
            return False
        if self._is_relevant is None:
            return True
        try:
            return bool(self._is_relevant(path))
        except Exception:
            log.debug("is_relevant failed for %s; failing open", path, exc_info=True)
            return True

    def _maybe_flush(self) -> None:
        """Dispatch coalesced events to the UI thread once idle or due."""
        if self._stop_event.is_set():
            return
        now = self._clock()
        with self._lock:
            first = self._first_pending_mono
            last = self._last_event_mono
            if first == 0.0:
                return
            coalesce_ready = (now - last) >= self._coalesce_s
            deadline_ready = (now - first) >= self._deadline_s
            if not (coalesce_ready or deadline_ready):
                return
            self._first_pending_mono = 0.0
            self._last_event_mono = 0.0
            changed_paths = tuple(sorted(self._pending_paths))
            self._pending_paths.clear()
        if self._stop_event.is_set():
            return
        try:

            def dispatch() -> None:
                self._dispatch_change(changed_paths)

            self._schedule_callback(dispatch)
            self._stat_queued_dispatches += 1
        except RuntimeError:
            # Textual rejects ``call_from_thread`` after the app exits;
            # treat that as a clean shutdown signal.
            self._stop_event.set()
        except Exception:
            log.exception("artifact watcher callback dispatch failed")

    def _dispatch_change(self, changed_paths: tuple[Path, ...]) -> None:
        self._stat_ui_dispatches += 1
        self._stat_dispatched_paths += len(changed_paths)
        if self._on_change_accepts_paths:
            self._on_change(changed_paths)
        else:
            self._on_change()

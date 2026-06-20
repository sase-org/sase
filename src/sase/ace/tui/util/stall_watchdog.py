"""Always-on event-loop stall watchdog for the ace TUI."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from typing import Any

from sase.logs import log_tui_stall

log = logging.getLogger(__name__)

ENV_DISABLE = "SASE_TUI_STALL_DISABLE"
ENV_THRESHOLD = "SASE_TUI_STALL_THRESHOLD"
ENV_THRESHOLD_SECONDS = "SASE_TUI_STALL_THRESHOLD_SECONDS"
ENV_POLL_INTERVAL = "SASE_TUI_STALL_POLL_INTERVAL"

DEFAULT_THRESHOLD_SECONDS = 5.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.5
_TRUTHY = {"1", "true", "yes", "on"}

ContextProvider = Callable[[], Mapping[str, Any]]


def is_enabled() -> bool:
    """Return whether the always-on stall watchdog should run."""
    return os.environ.get(ENV_DISABLE, "").lower() not in _TRUTHY


def start_event_loop_stall_watchdog(
    loop: asyncio.AbstractEventLoop,
    *,
    context_provider: ContextProvider | None = None,
) -> _EventLoopStallWatchdog | None:
    """Start the watchdog unless disabled by environment."""
    if not is_enabled():
        return None
    watchdog = _EventLoopStallWatchdog(loop, context_provider=context_provider)
    watchdog.start()
    return watchdog


class _EventLoopStallWatchdog:
    """Detect event-loop stalls from a daemon thread.

    The watchdog schedules a cheap beacon onto the Textual event loop. If that
    beacon stops running for longer than ``threshold_seconds``, the watchdog
    captures the loop thread's Python stack from outside the blocked loop and
    appends a durable JSONL record.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        context_provider: ContextProvider | None = None,
        threshold_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        loop_thread_ident: int | None = None,
    ) -> None:
        self._loop = loop
        self._context_provider = context_provider
        self._threshold_seconds = (
            threshold_seconds
            if threshold_seconds is not None
            else _float_env(
                ENV_THRESHOLD_SECONDS,
                _float_env(ENV_THRESHOLD, DEFAULT_THRESHOLD_SECONDS),
            )
        )
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else _float_env(ENV_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_SECONDS)
        )
        self._loop_thread_ident = loop_thread_ident or threading.get_ident()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_progress_mono = time.monotonic()
        self._ping_pending = False
        self._in_stall = False
        self._stall_started_mono: float | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the daemon watchdog thread."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="sase-tui-stall-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Stop the watchdog thread."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop_event.wait(self._poll_interval_seconds):
            if self._loop.is_closed():
                return
            self._schedule_ping()
            now_mono = time.monotonic()
            with self._lock:
                gap = now_mono - self._last_progress_mono
                in_stall = self._in_stall
            if gap >= self._threshold_seconds and not in_stall:
                self._record_stall(now_mono, gap)
            elif gap < self._threshold_seconds and in_stall:
                self._record_recovery(now_mono)

    def _schedule_ping(self) -> None:
        with self._lock:
            if self._ping_pending:
                return
            self._ping_pending = True
        try:
            self._loop.call_soon_threadsafe(self._mark_loop_progress)
        except RuntimeError:
            with self._lock:
                self._ping_pending = False
            self._stop_event.set()

    def _mark_loop_progress(self) -> None:
        now_mono = time.monotonic()
        with self._lock:
            self._last_progress_mono = now_mono
            self._ping_pending = False

    def _record_stall(self, now_mono: float, stall_seconds: float) -> None:
        with self._lock:
            if self._in_stall:
                return
            self._in_stall = True
            self._stall_started_mono = now_mono - stall_seconds
        record = self._stall_record(stall_seconds)
        log_tui_stall(record)
        log.warning(
            "TUI event loop stall detected: %.3fs pid=%s",
            stall_seconds,
            record["pid"],
        )

    def _record_recovery(self, now_mono: float) -> None:
        with self._lock:
            started = self._stall_started_mono
            self._in_stall = False
            self._stall_started_mono = None
        if started is None:
            return
        log.warning("TUI event loop recovered after %.3fs", now_mono - started)

    def _stall_record(self, stall_seconds: float) -> dict[str, Any]:
        context = self._context()
        stack = _format_thread_stack(self._loop_thread_ident)
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": "tui_stall",
            "pid": os.getpid(),
            "stall_seconds": round(stall_seconds, 3),
            "threshold_seconds": self._threshold_seconds,
            "poll_interval_seconds": self._poll_interval_seconds,
            "loop_thread_ident": self._loop_thread_ident,
            "watchdog_thread_ident": threading.get_ident(),
            "main_thread_stack": stack,
            "sase_version": _sase_version(),
        }
        for key, value in context.items():
            if value is not None:
                record[key] = value
        return record

    def _context(self) -> dict[str, Any]:
        context: dict[str, Any] = {}
        try:
            from .trace import get_trace_context

            context.update(get_trace_context())
        except Exception:
            log.debug("Failed to snapshot TUI trace context", exc_info=True)
        if self._context_provider is None:
            return context
        try:
            context.update(dict(self._context_provider()))
        except Exception:
            log.debug("Failed to snapshot TUI stall context", exc_info=True)
        return context


def _format_thread_stack(thread_ident: int) -> list[str]:
    frame = sys._current_frames().get(thread_ident)
    if frame is None:
        return []
    return traceback.format_stack(frame)


def _sase_version() -> str | None:
    try:
        from sase import __version__

        return __version__
    except Exception:
        return None


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default

"""Always-on event-loop and Textual message-pump stall watchdog."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from sase.logs import log_tui_stall

log = logging.getLogger(__name__)

ENV_DISABLE = "SASE_TUI_STALL_DISABLE"
ENV_THRESHOLD = "SASE_TUI_STALL_THRESHOLD"
ENV_THRESHOLD_SECONDS = "SASE_TUI_STALL_THRESHOLD_SECONDS"
ENV_POLL_INTERVAL = "SASE_TUI_STALL_POLL_INTERVAL"
ENV_PUMP_DISABLE = "SASE_TUI_PUMP_STALL_DISABLE"
ENV_PUMP_THRESHOLD = "SASE_TUI_PUMP_STALL_THRESHOLD"
ENV_PUMP_THRESHOLD_SECONDS = "SASE_TUI_PUMP_STALL_THRESHOLD_SECONDS"
ENV_PUMP_POLL_INTERVAL = "SASE_TUI_PUMP_STALL_POLL_INTERVAL"
ENV_HITCH_DISABLE = "SASE_TUI_HITCH_DISABLE"
ENV_HITCH_THRESHOLD_SECONDS = "SASE_TUI_HITCH_THRESHOLD_SECONDS"
ENV_PUMP_HITCH_DISABLE = "SASE_TUI_PUMP_HITCH_DISABLE"
ENV_PUMP_HITCH_THRESHOLD_SECONDS = "SASE_TUI_PUMP_HITCH_THRESHOLD_SECONDS"

DEFAULT_THRESHOLD_SECONDS = 5.0
DEFAULT_HITCH_THRESHOLD_SECONDS = 1.5
DEFAULT_POLL_INTERVAL_SECONDS = 0.5
DEFAULT_HITCH_RATE_LIMIT_PER_MINUTE = 4
HITCH_RATE_LIMIT_WINDOW_SECONDS = 60.0
MAX_WORKER_THREAD_STACKS = 16
MAX_WORKER_THREAD_STACK_DEPTH = 64
_TRUTHY = {"1", "true", "yes", "on"}

ContextProvider = Callable[[], Mapping[str, Any]]


def is_enabled() -> bool:
    """Return whether the always-on stall watchdog should run."""
    return os.environ.get(ENV_DISABLE, "").lower() not in _TRUTHY


def start_event_loop_stall_watchdog(
    loop: asyncio.AbstractEventLoop,
    *,
    app: Any | None = None,
    context_provider: ContextProvider | None = None,
) -> _EventLoopStallWatchdog | None:
    """Start the watchdog unless disabled by environment."""
    if not is_enabled():
        return None
    watchdog = _EventLoopStallWatchdog(
        loop,
        pump_app=app,
        context_provider=context_provider,
    )
    watchdog.start()
    return watchdog


def subscribe_watchdog_to_suspend_signals(
    app: Any,
    watchdog: _EventLoopStallWatchdog | None,
) -> bool:
    """Pause the watchdog across Textual ``suspend()`` terminal handoffs.

    The installed Textual runtime publishes ``app_suspend_signal`` before it
    parks the loop and ``app_resume_signal`` after it restarts. Subscribing
    with ``immediate=True`` runs the pause/resume callback synchronously during
    publish; the default posts it back to the app, which is too late because
    ``suspend()`` blocks the loop immediately after publishing.

    This is the global safety net for every ``app.suspend()`` call site, not
    just the helper-migrated ones. It is fully guarded so Textual versions
    without these exact instance signals keep working — in that case the
    external-tool helper falls back to pausing the watchdog around its own
    suspend block. Returns whether both signals were wired.

    The resume hook is subscribed first so a mid-wiring failure can never leave
    a pause subscription without its matching resume (an unbalanced resume on a
    depth-zero watchdog is a harmless no-op).
    """
    if watchdog is None:
        return False
    suspend_signal = getattr(app, "app_suspend_signal", None)
    resume_signal = getattr(app, "app_resume_signal", None)
    subscribe_suspend = getattr(suspend_signal, "subscribe", None)
    subscribe_resume = getattr(resume_signal, "subscribe", None)
    if not callable(subscribe_suspend) or not callable(subscribe_resume):
        return False
    try:
        subscribe_resume(app, lambda _data: watchdog.resume(), immediate=True)
        subscribe_suspend(app, lambda _data: watchdog.pause(), immediate=True)
    except Exception:
        log.debug("stall watchdog suspend-signal wiring skipped", exc_info=True)
        return False
    return True


class _EventLoopStallWatchdog:
    """Detect event-loop and Textual message-pump stalls from a daemon thread.

    The watchdog schedules a cheap beacon onto the Textual event loop. If that
    beacon stops running for longer than ``threshold_seconds``, the watchdog
    captures the loop thread's Python stack from outside the blocked loop and
    appends a durable JSONL record.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        pump_app: Any | None = None,
        context_provider: ContextProvider | None = None,
        threshold_seconds: float | None = None,
        hitch_threshold_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        pump_threshold_seconds: float | None = None,
        pump_hitch_threshold_seconds: float | None = None,
        pump_poll_interval_seconds: float | None = None,
        hitch_rate_limit_per_minute: int = DEFAULT_HITCH_RATE_LIMIT_PER_MINUTE,
        hitch_rate_limit_window_seconds: float = HITCH_RATE_LIMIT_WINDOW_SECONDS,
        loop_thread_ident: int | None = None,
    ) -> None:
        self._loop = loop
        self._hitch_enabled = (
            os.environ.get(ENV_HITCH_DISABLE, "").lower() not in _TRUTHY
        )
        self._pump_stall_enabled = (
            os.environ.get(ENV_PUMP_DISABLE, "").lower() not in _TRUTHY
        )
        self._pump_hitch_enabled = (
            os.environ.get(ENV_PUMP_HITCH_DISABLE, "").lower() not in _TRUTHY
        )
        self._pump_app = (
            pump_app
            if pump_app is not None
            and (self._pump_stall_enabled or self._pump_hitch_enabled)
            else None
        )
        self._context_provider = context_provider
        self._threshold_seconds = (
            threshold_seconds
            if threshold_seconds is not None
            else _float_env(
                ENV_THRESHOLD_SECONDS,
                _float_env(ENV_THRESHOLD, DEFAULT_THRESHOLD_SECONDS),
            )
        )
        self._hitch_threshold_seconds = (
            hitch_threshold_seconds
            if hitch_threshold_seconds is not None
            else _float_env(
                ENV_HITCH_THRESHOLD_SECONDS,
                DEFAULT_HITCH_THRESHOLD_SECONDS,
            )
        )
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else _float_env(ENV_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_SECONDS)
        )
        self._pump_threshold_seconds = (
            pump_threshold_seconds
            if pump_threshold_seconds is not None
            else _float_env(
                ENV_PUMP_THRESHOLD_SECONDS,
                _float_env(ENV_PUMP_THRESHOLD, DEFAULT_THRESHOLD_SECONDS),
            )
        )
        self._pump_hitch_threshold_seconds = (
            pump_hitch_threshold_seconds
            if pump_hitch_threshold_seconds is not None
            else _float_env(
                ENV_PUMP_HITCH_THRESHOLD_SECONDS,
                DEFAULT_HITCH_THRESHOLD_SECONDS,
            )
        )
        self._pump_poll_interval_seconds = (
            pump_poll_interval_seconds
            if pump_poll_interval_seconds is not None
            else _float_env(
                ENV_PUMP_POLL_INTERVAL,
                DEFAULT_POLL_INTERVAL_SECONDS,
            )
        )
        self._loop_thread_ident = loop_thread_ident or threading.get_ident()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_progress_mono = time.monotonic()
        self._ping_pending = False
        self._in_hitch = False
        self._hitch_started_mono: float | None = None
        self._hitch_was_recorded = False
        self._in_stall = False
        self._stall_started_mono: float | None = None
        self._pump_ping_pending = False
        self._pump_ping_started_mono: float | None = None
        self._last_pump_ping_mono = 0.0
        self._pump_in_hitch = False
        self._pump_hitch_started_mono: float | None = None
        self._pump_hitch_was_recorded = False
        self._pump_in_stall = False
        self._pump_stall_started_mono: float | None = None
        self._hitch_rate_limiter = _HitchRateLimiter(
            max_records=hitch_rate_limit_per_minute,
            window_seconds=hitch_rate_limit_window_seconds,
        )
        self._pump_hitch_rate_limiter = _HitchRateLimiter(
            max_records=hitch_rate_limit_per_minute,
            window_seconds=hitch_rate_limit_window_seconds,
        )
        self._pause_depth = 0
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

    def pause(self) -> None:
        """Pause stall detection for an intentional terminal handoff.

        Nested calls are reference-counted; detection only resumes after a
        matching number of :meth:`resume` calls. Safe to call from the loop
        thread immediately before ``App.suspend()`` parks the loop — while
        paused the watchdog keeps the progress clock fresh and never pings the
        blocked loop, so a deliberate suspend is not read as a stall.
        """
        with self._lock:
            self._pause_depth += 1
            self._last_progress_mono = time.monotonic()
            self._reset_pump_state_locked()

    def resume(self) -> None:
        """Resume stall detection after a terminal handoff completes.

        Balances :meth:`pause`. On the final (depth-zero) resume the progress
        clock and all pending/stall bookkeeping are reset so a completed
        suspend cannot produce an immediate synthetic stall or recovery on the
        next poll. Extra/unbalanced resumes are ignored.
        """
        with self._lock:
            if self._pause_depth == 0:
                return
            self._pause_depth -= 1
            if self._pause_depth > 0:
                return
            self._last_progress_mono = time.monotonic()
            self._ping_pending = False
            self._in_hitch = False
            self._hitch_started_mono = None
            self._hitch_was_recorded = False
            self._in_stall = False
            self._stall_started_mono = None
            self._reset_pump_state_locked()

    def _run(self) -> None:
        while not self._stop_event.wait(self._poll_interval_seconds):
            if self._loop.is_closed():
                return
            now_mono = time.monotonic()
            with self._lock:
                paused = self._pause_depth > 0
                if paused:
                    self._last_progress_mono = now_mono
            if paused:
                continue
            self._schedule_ping()
            self._schedule_pump_ping(now_mono)
            with self._lock:
                gap = now_mono - self._last_progress_mono
                in_hitch = self._in_hitch
                in_stall = self._in_stall
                pump_started = self._pump_ping_started_mono
                pump_gap = (
                    now_mono - pump_started
                    if self._pump_ping_pending and pump_started is not None
                    else 0.0
                )
                pump_in_hitch = self._pump_in_hitch
                pump_in_stall = self._pump_in_stall
            if self._hitch_enabled:
                if gap >= self._hitch_threshold_seconds and not in_hitch:
                    self._record_hitch(now_mono, gap)
                elif gap < self._hitch_threshold_seconds and in_hitch:
                    self._record_hitch_recovery(now_mono)
            if gap >= self._threshold_seconds and not in_stall:
                self._record_stall(now_mono, gap)
            elif gap < self._threshold_seconds and in_stall:
                self._record_recovery(now_mono)
            if self._pump_hitch_enabled:
                if pump_gap >= self._pump_hitch_threshold_seconds and not pump_in_hitch:
                    self._record_pump_hitch(now_mono, pump_gap)
                elif pump_gap < self._pump_hitch_threshold_seconds and pump_in_hitch:
                    self._record_pump_hitch_recovery(now_mono)
            if self._pump_stall_enabled:
                if pump_gap >= self._pump_threshold_seconds and not pump_in_stall:
                    self._record_pump_stall(now_mono, pump_gap)
                elif pump_gap < self._pump_threshold_seconds and pump_in_stall:
                    self._record_pump_recovery(now_mono)

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

    def _schedule_pump_ping(self, now_mono: float) -> None:
        if self._pump_app is None:
            return
        with self._lock:
            if self._pump_ping_pending:
                return
            if now_mono - self._last_pump_ping_mono < self._pump_poll_interval_seconds:
                return
            self._pump_ping_pending = True
            self._pump_ping_started_mono = now_mono
            self._last_pump_ping_mono = now_mono
        try:
            self._loop.call_soon_threadsafe(self._enqueue_pump_mark)
        except RuntimeError:
            with self._lock:
                self._pump_ping_pending = False
                self._pump_ping_started_mono = None
            self._stop_event.set()

    def _enqueue_pump_mark(self) -> None:
        pump_app = self._pump_app
        if pump_app is None:
            return
        try:
            pump_app.call_later(self._mark_pump_progress)
        except Exception:
            log.debug("Failed to enqueue TUI message-pump beacon", exc_info=True)
            with self._lock:
                self._pump_ping_pending = False
                self._pump_ping_started_mono = None

    def _mark_pump_progress(self) -> None:
        with self._lock:
            self._pump_ping_pending = False
            self._pump_ping_started_mono = None

    def _record_hitch(self, now_mono: float, stall_seconds: float) -> None:
        with self._lock:
            if self._in_hitch:
                return
            self._in_hitch = True
            self._hitch_started_mono = now_mono - stall_seconds
            suppressed_count = self._hitch_rate_limiter.admit(now_mono)
            self._hitch_was_recorded = suppressed_count is not None
        if suppressed_count is None:
            return
        record = self._hitch_record(
            "tui_hitch",
            stall_seconds,
            threshold_seconds=self._hitch_threshold_seconds,
            suppressed_count=suppressed_count,
        )
        log_tui_stall(record)
        log.info(
            "TUI event loop hitch detected: %.3fs pid=%s",
            stall_seconds,
            record["pid"],
        )

    def _record_hitch_recovery(self, now_mono: float) -> None:
        with self._lock:
            started = self._hitch_started_mono
            was_recorded = self._hitch_was_recorded
            self._in_hitch = False
            self._hitch_started_mono = None
            self._hitch_was_recorded = False
        if started is None or not was_recorded:
            return
        duration = now_mono - started
        log_tui_stall(self._hitch_recovery_record("tui_hitch_recovered", duration))
        log.info("TUI event loop recovered from hitch after %.3fs", duration)

    def _record_pump_hitch(self, now_mono: float, stall_seconds: float) -> None:
        with self._lock:
            if self._pump_in_hitch:
                return
            self._pump_in_hitch = True
            self._pump_hitch_started_mono = now_mono - stall_seconds
            suppressed_count = self._pump_hitch_rate_limiter.admit(now_mono)
            self._pump_hitch_was_recorded = suppressed_count is not None
        if suppressed_count is None:
            return
        record = self._hitch_record(
            "tui_pump_hitch",
            stall_seconds,
            threshold_seconds=self._pump_hitch_threshold_seconds,
            suppressed_count=suppressed_count,
        )
        log_tui_stall(record)
        log.info(
            "TUI message pump hitch detected: %.3fs pid=%s",
            stall_seconds,
            record["pid"],
        )

    def _record_pump_hitch_recovery(self, now_mono: float) -> None:
        with self._lock:
            started = self._pump_hitch_started_mono
            was_recorded = self._pump_hitch_was_recorded
            self._pump_in_hitch = False
            self._pump_hitch_started_mono = None
            self._pump_hitch_was_recorded = False
        if started is None or not was_recorded:
            return
        duration = now_mono - started
        log_tui_stall(self._hitch_recovery_record("tui_pump_hitch_recovered", duration))
        log.info("TUI message pump recovered from hitch after %.3fs", duration)

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
        duration = now_mono - started
        log_tui_stall(self._recovery_record("tui_stall_recovered", duration))
        log.warning("TUI event loop recovered after %.3fs", duration)

    def _record_pump_stall(self, now_mono: float, stall_seconds: float) -> None:
        with self._lock:
            if self._pump_in_stall:
                return
            self._pump_in_stall = True
            self._pump_stall_started_mono = now_mono - stall_seconds
        try:
            self._loop.call_soon_threadsafe(
                self._write_pump_stall_record,
                stall_seconds,
            )
        except RuntimeError:
            self._write_pump_stall_record(stall_seconds, capture_tasks=False)

    def _write_pump_stall_record(
        self,
        stall_seconds: float,
        *,
        capture_tasks: bool = True,
    ) -> None:
        record = self._pump_stall_record(
            stall_seconds,
            capture_tasks=capture_tasks,
        )
        log_tui_stall(record)
        log.warning(
            "TUI message pump stall detected: %.3fs pid=%s",
            stall_seconds,
            record["pid"],
        )

    def _record_pump_recovery(self, now_mono: float) -> None:
        with self._lock:
            started = self._pump_stall_started_mono
            self._pump_in_stall = False
            self._pump_stall_started_mono = None
        if started is None:
            return
        duration = now_mono - started
        log_tui_stall(self._recovery_record("tui_pump_stall_recovered", duration))
        log.warning("TUI message pump recovered after %.3fs", duration)

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
            "pause_depth": self._current_pause_depth(),
            "sase_version": _sase_version(),
        }
        for key, value in context.items():
            if value is not None:
                record[key] = value
        return record

    def _hitch_record(
        self,
        event: str,
        stall_seconds: float,
        *,
        threshold_seconds: float,
        suppressed_count: int,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            "pid": os.getpid(),
            "stall_seconds": round(stall_seconds, 3),
            "threshold_seconds": threshold_seconds,
            "main_thread_stack": _format_thread_stack(self._loop_thread_ident),
            "suppressed_count": suppressed_count,
        }
        for key, value in self._context().items():
            if value is not None:
                record[key] = value
        return record

    def _hitch_recovery_record(
        self,
        event: str,
        duration_seconds: float,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            "pid": os.getpid(),
            "duration_seconds": round(duration_seconds, 3),
            "main_thread_stack": _format_thread_stack(self._loop_thread_ident),
        }
        for key, value in self._context().items():
            if value is not None:
                record[key] = value
        return record

    def _pump_stall_record(
        self,
        stall_seconds: float,
        *,
        capture_tasks: bool,
    ) -> dict[str, Any]:
        watchdog_thread_ident = (
            self._thread.ident
            if self._thread is not None and self._thread.ident is not None
            else threading.get_ident()
        )
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": "tui_pump_stall",
            "pid": os.getpid(),
            "stall_seconds": round(stall_seconds, 3),
            "threshold_seconds": self._pump_threshold_seconds,
            "poll_interval_seconds": self._pump_poll_interval_seconds,
            "loop_thread_ident": self._loop_thread_ident,
            "watchdog_thread_ident": watchdog_thread_ident,
            "main_thread_stack": _format_thread_stack(self._loop_thread_ident),
            "asyncio_task_stacks": (
                _format_asyncio_task_stacks(self._loop) if capture_tasks else []
            ),
            "worker_thread_stacks": _format_worker_thread_stacks(
                excluded_idents={
                    self._loop_thread_ident,
                    watchdog_thread_ident,
                }
            ),
            "pause_depth": self._current_pause_depth(),
            "sase_version": _sase_version(),
        }
        for key, value in self._context().items():
            if value is not None:
                record[key] = value
        return record

    def _recovery_record(
        self,
        event: str,
        duration_seconds: float,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            "pid": os.getpid(),
            "duration_seconds": round(duration_seconds, 3),
            "pause_depth": self._current_pause_depth(),
            "sase_version": _sase_version(),
        }
        for key, value in self._context().items():
            if value is not None:
                record[key] = value
        return record

    def _current_pause_depth(self) -> int:
        with self._lock:
            return self._pause_depth

    def _reset_pump_state_locked(self) -> None:
        self._pump_ping_pending = False
        self._pump_ping_started_mono = None
        self._last_pump_ping_mono = time.monotonic()
        self._pump_in_hitch = False
        self._pump_hitch_started_mono = None
        self._pump_hitch_was_recorded = False
        self._pump_in_stall = False
        self._pump_stall_started_mono = None

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


class _HitchRateLimiter:
    """Bound compact hitch episodes while reporting accumulated suppression."""

    def __init__(self, *, max_records: int, window_seconds: float) -> None:
        self._max_records = max(1, max_records)
        self._window_seconds = max(0.001, window_seconds)
        self._recorded_at: deque[float] = deque()
        self._suppressed_count = 0

    def admit(self, now_mono: float) -> int | None:
        cutoff = now_mono - self._window_seconds
        while self._recorded_at and self._recorded_at[0] <= cutoff:
            self._recorded_at.popleft()
        if len(self._recorded_at) >= self._max_records:
            self._suppressed_count += 1
            return None
        self._recorded_at.append(now_mono)
        suppressed_count = self._suppressed_count
        self._suppressed_count = 0
        return suppressed_count


def _format_thread_stack(thread_ident: int) -> list[str]:
    frame = sys._current_frames().get(thread_ident)
    if frame is None:
        return []
    return traceback.format_stack(frame)


def _format_worker_thread_stacks(
    *,
    excluded_idents: set[int],
    max_threads: int = MAX_WORKER_THREAD_STACKS,
    max_depth: int = MAX_WORKER_THREAD_STACK_DEPTH,
) -> list[dict[str, Any]]:
    """Return bounded stacks for live threads other than loop/watchdog."""
    stacks: list[dict[str, Any]] = []
    try:
        frames = sys._current_frames()
        threads_by_ident = {
            thread.ident: thread
            for thread in threading.enumerate()
            if thread.ident is not None
        }

        def _thread_sort_key(ident: int) -> tuple[str, int]:
            thread = threads_by_ident.get(ident)
            return (thread.name if thread is not None else "", ident)

        worker_idents = sorted(
            (ident for ident in frames if ident not in excluded_idents),
            key=_thread_sort_key,
        )[:max_threads]
    except Exception:
        log.debug("Failed to enumerate worker threads for pump stall", exc_info=True)
        return stacks

    for ident in worker_idents:
        try:
            thread = threads_by_ident.get(ident)
            stacks.append(
                {
                    "name": thread.name if thread is not None else "unknown",
                    "ident": ident,
                    "daemon": thread.daemon if thread is not None else None,
                    "stack": traceback.format_stack(
                        frames[ident],
                        limit=max_depth,
                    ),
                }
            )
        except Exception:
            log.debug("Failed to format worker thread stack", exc_info=True)
    return stacks


def _format_asyncio_task_stacks(
    loop: asyncio.AbstractEventLoop,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    try:
        live_tasks = sorted(asyncio.all_tasks(loop), key=lambda task: task.get_name())
    except Exception:
        log.debug("Failed to enumerate asyncio tasks for pump stall", exc_info=True)
        return tasks
    for task in live_tasks:
        try:
            await_chain = _format_coroutine_await_chain(task.get_coro())
            stack = [
                line
                for frame in task.get_stack(limit=64)
                for line in traceback.format_stack(frame)
            ]
            stack.extend(line for awaited in await_chain for line in awaited["stack"])
            tasks.append(
                {
                    "name": task.get_name(),
                    "coroutine": repr(task.get_coro()),
                    "done": task.done(),
                    "stack": stack,
                    "await_chain": await_chain,
                }
            )
        except Exception:
            log.debug("Failed to format asyncio task stack", exc_info=True)
    return tasks


def _format_coroutine_await_chain(coro: Any) -> list[dict[str, Any]]:
    """Walk nested ``await`` objects so records include the actual handler."""
    chain: list[dict[str, Any]] = []
    current: Any = coro
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        frame = getattr(current, "cr_frame", None)
        if frame is None:
            frame = getattr(current, "gi_frame", None)
        if frame is None:
            frame = getattr(current, "ag_frame", None)
        chain.append(
            {
                "coroutine": repr(current),
                "stack": traceback.format_stack(frame) if frame is not None else [],
            }
        )
        current = getattr(current, "cr_await", None) or getattr(
            current, "gi_yieldfrom", None
        )
    return chain


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

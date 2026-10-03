"""Loop and message-pump monitoring for the TUI stall watchdog."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from ._stall_watchdog_config import (
    DEFAULT_HITCH_RATE_LIMIT_PER_MINUTE,
    DEFAULT_HITCH_THRESHOLD_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_THRESHOLD_SECONDS,
    ENV_HITCH_DISABLE,
    ENV_HITCH_THRESHOLD_SECONDS,
    ENV_POLL_INTERVAL,
    ENV_PUMP_DISABLE,
    ENV_PUMP_HITCH_DISABLE,
    ENV_PUMP_HITCH_THRESHOLD_SECONDS,
    ENV_PUMP_POLL_INTERVAL,
    ENV_PUMP_THRESHOLD,
    ENV_PUMP_THRESHOLD_SECONDS,
    ENV_THRESHOLD,
    ENV_THRESHOLD_SECONDS,
    HITCH_RATE_LIMIT_WINDOW_SECONDS,
    ContextProvider,
    float_env,
    HitchRateLimiter,
    _TRUTHY,
)
from ._stall_watchdog_records import StallRecordMixin

log = logging.getLogger(f"{__package__}.stall_watchdog")

HEARTBEAT_PROVIDER_NAME = "stall_watchdog"


def _snapshot_app_instance_id(app: Any | None) -> str | None:
    """Read the app instance ID minted at construction, if present.

    Never raises: without an app (or without GC telemetry) the watchdog
    simply omits ``app_instance_id`` from its rows.
    """
    if app is None:
        return None
    try:
        from .gc_telemetry import app_instance_id
    except Exception:
        return None
    try:
        return app_instance_id(app)
    except Exception:
        return None


class EventLoopStallWatchdog(StallRecordMixin):
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
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loop = loop
        self._monotonic = monotonic
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
            else float_env(
                ENV_THRESHOLD_SECONDS,
                float_env(ENV_THRESHOLD, DEFAULT_THRESHOLD_SECONDS),
            )
        )
        self._hitch_threshold_seconds = (
            hitch_threshold_seconds
            if hitch_threshold_seconds is not None
            else float_env(
                ENV_HITCH_THRESHOLD_SECONDS,
                DEFAULT_HITCH_THRESHOLD_SECONDS,
            )
        )
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else float_env(ENV_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_SECONDS)
        )
        self._pump_threshold_seconds = (
            pump_threshold_seconds
            if pump_threshold_seconds is not None
            else float_env(
                ENV_PUMP_THRESHOLD_SECONDS,
                float_env(ENV_PUMP_THRESHOLD, DEFAULT_THRESHOLD_SECONDS),
            )
        )
        self._pump_hitch_threshold_seconds = (
            pump_hitch_threshold_seconds
            if pump_hitch_threshold_seconds is not None
            else float_env(
                ENV_PUMP_HITCH_THRESHOLD_SECONDS,
                DEFAULT_HITCH_THRESHOLD_SECONDS,
            )
        )
        self._pump_poll_interval_seconds = (
            pump_poll_interval_seconds
            if pump_poll_interval_seconds is not None
            else float_env(
                ENV_PUMP_POLL_INTERVAL,
                DEFAULT_POLL_INTERVAL_SECONDS,
            )
        )
        self._loop_thread_ident = loop_thread_ident or threading.get_ident()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_progress_mono = self._monotonic()
        self._last_poll_mono = self._last_progress_mono
        self._app_instance_id = _snapshot_app_instance_id(pump_app)
        self._ping_pending = False
        self._in_hitch = False
        self._hitch_started_mono: float | None = None
        self._hitch_was_recorded = False
        self._hitch_late = False
        self._hitch_poll_lag_s = 0.0
        self._hitch_detected_by = "loop_gap"
        self._in_stall = False
        self._stall_started_mono: float | None = None
        self._loop_hitch_episodes = 0
        self._loop_hitch_seconds = 0.0
        self._loop_suppressed_episodes = 0
        self._loop_suppressed_seconds = 0.0
        self._pump_ping_pending = False
        self._pump_ping_started_mono: float | None = None
        self._last_pump_ping_mono = 0.0
        self._pump_in_hitch = False
        self._pump_hitch_started_mono: float | None = None
        self._pump_hitch_was_recorded = False
        self._pump_hitch_late = False
        self._pump_hitch_poll_lag_s = 0.0
        self._pump_hitch_detected_by = "pump_gap"
        self._pump_in_stall = False
        self._pump_stall_started_mono: float | None = None
        self._pump_hitch_episodes = 0
        self._pump_hitch_seconds = 0.0
        self._pump_suppressed_episodes = 0
        self._pump_suppressed_seconds = 0.0
        self._hitch_rate_limiter = HitchRateLimiter(
            max_records=hitch_rate_limit_per_minute,
            window_seconds=hitch_rate_limit_window_seconds,
        )
        self._pump_hitch_rate_limiter = HitchRateLimiter(
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
        self._register_heartbeat_provider()

    def stop(self, timeout: float = 1.0) -> None:
        """Stop the watchdog thread."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._unregister_heartbeat_provider()

    def _register_heartbeat_provider(self) -> None:
        """Publish exact hitch totals to the GC telemetry heartbeat."""
        try:
            from .gc_telemetry import register_heartbeat_provider

            register_heartbeat_provider(
                HEARTBEAT_PROVIDER_NAME, self._heartbeat_hitch_totals
            )
        except Exception:
            log.debug("stall watchdog heartbeat provider skipped", exc_info=True)

    def _unregister_heartbeat_provider(self) -> None:
        try:
            from .gc_telemetry import unregister_heartbeat_provider

            unregister_heartbeat_provider(HEARTBEAT_PROVIDER_NAME)
        except Exception:
            log.debug(
                "stall watchdog heartbeat provider removal skipped", exc_info=True
            )

    def _heartbeat_hitch_totals(self) -> dict[str, Any]:
        """Snapshot episode totals since the last heartbeat, then reset.

        Called from the GC telemetry flush thread while writing each
        ``tui_memory_heartbeat`` row, so the counters always cover exactly
        the window since the previous heartbeat. Never raises.
        """
        try:
            with self._lock:
                totals = {
                    "loop_hitch_episodes": self._loop_hitch_episodes,
                    "loop_hitch_seconds": round(self._loop_hitch_seconds, 3),
                    "loop_suppressed_episodes": self._loop_suppressed_episodes,
                    "loop_suppressed_seconds": round(self._loop_suppressed_seconds, 3),
                    "pump_hitch_episodes": self._pump_hitch_episodes,
                    "pump_hitch_seconds": round(self._pump_hitch_seconds, 3),
                    "pump_suppressed_episodes": self._pump_suppressed_episodes,
                    "pump_suppressed_seconds": round(self._pump_suppressed_seconds, 3),
                }
                self._loop_hitch_episodes = 0
                self._loop_hitch_seconds = 0.0
                self._loop_suppressed_episodes = 0
                self._loop_suppressed_seconds = 0.0
                self._pump_hitch_episodes = 0
                self._pump_hitch_seconds = 0.0
                self._pump_suppressed_episodes = 0
                self._pump_suppressed_seconds = 0.0
            return totals
        except Exception:
            log.debug("stall watchdog heartbeat totals failed", exc_info=True)
            return {}

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
            self._last_progress_mono = self._monotonic()
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
            self._last_progress_mono = self._monotonic()
            self._last_poll_mono = self._last_progress_mono
            self._ping_pending = False
            self._in_hitch = False
            self._hitch_started_mono = None
            self._hitch_was_recorded = False
            self._hitch_late = False
            self._hitch_poll_lag_s = 0.0
            self._hitch_detected_by = "loop_gap"
            self._in_stall = False
            self._stall_started_mono = None
            self._reset_pump_state_locked()

    def _in_hitch_after_poll(self) -> bool:
        """Return whether the loop-gap path already owns the hitch episode."""
        with self._lock:
            return self._in_hitch

    def _run(self) -> None:
        while not self._stop_event.wait(self._poll_interval_seconds):
            if not self._poll_once():
                return

    def _poll_once(self) -> bool:
        if self._loop.is_closed():
            return False
        now_mono = self._monotonic()
        with self._lock:
            paused = self._pause_depth > 0
            if paused:
                self._last_progress_mono = now_mono
                self._last_poll_mono = now_mono
        if paused:
            return True
        self._schedule_ping()
        self._schedule_pump_ping(now_mono)
        with self._lock:
            gap = now_mono - self._last_progress_mono
            in_hitch = self._in_hitch
            in_stall = self._in_stall
            poll_gap = now_mono - self._last_poll_mono
            self._last_poll_mono = now_mono
            pump_started = self._pump_ping_started_mono
            pump_gap = (
                now_mono - pump_started
                if self._pump_ping_pending and pump_started is not None
                else 0.0
            )
            pump_in_hitch = self._pump_in_hitch
            pump_in_stall = self._pump_in_stall
        poll_lag_s = poll_gap - self._poll_interval_seconds
        if self._hitch_enabled:
            if gap >= self._hitch_threshold_seconds and not in_hitch:
                self._record_hitch(now_mono, gap)
            elif gap < self._hitch_threshold_seconds and in_hitch:
                self._record_hitch_recovery(now_mono)
        if (
            self._hitch_enabled
            and poll_gap >= self._hitch_threshold_seconds
            and not self._in_hitch_after_poll()
        ):
            # The whole process stopped — including this watchdog thread —
            # even though the loop beacon already ran and the loop gap looks
            # small. This is the GIL-race blind spot: a stop-the-world pause
            # on another thread freezes every thread, and the beacon recovers
            # before this poll notices. The shared hitch state machine keeps
            # this from double-recording an episode the loop-gap path owns.
            self._record_hitch(
                now_mono,
                poll_gap,
                late=True,
                poll_lag_s=max(0.0, poll_lag_s),
                detected_by="watchdog_lateness",
            )
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
        return True

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
        now_mono = self._monotonic()
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

    def _reset_pump_state_locked(self) -> None:
        self._pump_ping_pending = False
        self._pump_ping_started_mono = None
        self._last_pump_ping_mono = self._monotonic()
        self._pump_in_hitch = False
        self._pump_hitch_started_mono = None
        self._pump_hitch_was_recorded = False
        self._pump_in_stall = False
        self._pump_stall_started_mono = None

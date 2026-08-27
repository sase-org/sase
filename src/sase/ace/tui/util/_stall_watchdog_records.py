"""Record state transitions and payloads for the TUI stall watchdog."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

from sase.logs import log_tui_stall

from ._stall_watchdog_capture import (
    format_asyncio_task_stacks,
    format_thread_stack,
    format_worker_thread_stacks,
    sase_version,
)
from ._stall_watchdog_config import ContextProvider, HitchRateLimiter

log = logging.getLogger(f"{__package__}.stall_watchdog")


class StallRecordMixin:
    """Emit stall transitions and build their diagnostic records."""

    _loop: asyncio.AbstractEventLoop
    _loop_thread_ident: int
    _thread: threading.Thread | None
    _lock: threading.Lock
    _context_provider: ContextProvider | None
    _threshold_seconds: float
    _poll_interval_seconds: float
    _pump_threshold_seconds: float
    _pump_poll_interval_seconds: float
    _in_hitch: bool
    _hitch_started_mono: float | None
    _hitch_was_recorded: bool
    _in_stall: bool
    _stall_started_mono: float | None
    _pump_in_hitch: bool
    _pump_hitch_started_mono: float | None
    _pump_hitch_was_recorded: bool
    _pump_in_stall: bool
    _pump_stall_started_mono: float | None
    _hitch_threshold_seconds: float
    _pump_hitch_threshold_seconds: float
    _hitch_rate_limiter: HitchRateLimiter
    _pump_hitch_rate_limiter: HitchRateLimiter
    _pause_depth: int

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
        # Build and write the record on this worker thread, not the event
        # loop: dispatching it via call_soon_threadsafe made stack capture
        # and JSONL serialization run on the loop as soon as it recovered,
        # extending the very freeze this is measuring.
        self._write_pump_stall_record(stall_seconds)

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
        stack = format_thread_stack(self._loop_thread_ident)
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
            "sase_version": sase_version(),
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
            "main_thread_stack": format_thread_stack(self._loop_thread_ident),
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
            "main_thread_stack": format_thread_stack(self._loop_thread_ident),
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
            "main_thread_stack": format_thread_stack(self._loop_thread_ident),
            "asyncio_task_stacks": (
                format_asyncio_task_stacks(self._loop) if capture_tasks else []
            ),
            "worker_thread_stacks": format_worker_thread_stacks(
                excluded_idents={
                    self._loop_thread_ident,
                    watchdog_thread_ident,
                }
            ),
            "pause_depth": self._current_pause_depth(),
            "sase_version": sase_version(),
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
            "sase_version": sase_version(),
        }
        for key, value in self._context().items():
            if value is not None:
                record[key] = value
        return record

    def _current_pause_depth(self) -> int:
        with self._lock:
            return self._pause_depth

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

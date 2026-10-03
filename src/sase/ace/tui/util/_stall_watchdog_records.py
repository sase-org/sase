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
    _pump_app: Any | None
    _app_instance_id: str | None
    _hitch_late: bool
    _hitch_poll_lag_s: float
    _hitch_detected_by: str
    _pump_hitch_late: bool
    _pump_hitch_poll_lag_s: float
    _pump_hitch_detected_by: str
    _loop_hitch_episodes: int
    _loop_hitch_seconds: float
    _loop_suppressed_episodes: int
    _loop_suppressed_seconds: float
    _pump_hitch_episodes: int
    _pump_hitch_seconds: float
    _pump_suppressed_episodes: int
    _pump_suppressed_seconds: float

    def _record_hitch(
        self,
        now_mono: float,
        stall_seconds: float,
        *,
        late: bool = False,
        poll_lag_s: float = 0.0,
        detected_by: str = "loop_gap",
    ) -> None:
        with self._lock:
            if self._in_hitch:
                return
            self._in_hitch = True
            self._hitch_started_mono = now_mono - stall_seconds
            self._hitch_late = late
            self._hitch_poll_lag_s = poll_lag_s
            self._hitch_detected_by = detected_by
            suppressed_count = self._hitch_rate_limiter.admit(now_mono)
            self._hitch_was_recorded = suppressed_count is not None
        if suppressed_count is None:
            return
        record = self._hitch_record(
            "tui_hitch",
            stall_seconds,
            threshold_seconds=self._hitch_threshold_seconds,
            suppressed_count=suppressed_count,
            late=late,
            poll_lag_s=poll_lag_s,
            detected_by=detected_by,
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
            late = self._hitch_late
            poll_lag_s = self._hitch_poll_lag_s
            detected_by = self._hitch_detected_by
            self._in_hitch = False
            self._hitch_started_mono = None
            self._hitch_was_recorded = False
            self._hitch_late = False
            self._hitch_poll_lag_s = 0.0
            self._hitch_detected_by = "loop_gap"
        if started is None:
            return
        duration = now_mono - started
        # Every episode counts toward the heartbeat totals, including
        # rate-limited ones that never produced a hitch row.
        self._accumulate_hitch_totals("loop", duration, was_recorded)
        if not was_recorded:
            return
        overlap_s, generations, triggers = _gc_overlap(started, now_mono)
        log_tui_stall(
            self._hitch_recovery_record(
                "tui_hitch_recovered",
                duration,
                late=late,
                poll_lag_s=poll_lag_s,
                detected_by=detected_by,
                gc_overlap_s=overlap_s,
                gc_generations=generations,
                gc_triggers=triggers,
            )
        )
        log.info("TUI event loop recovered from hitch after %.3fs", duration)

    def _record_pump_hitch(self, now_mono: float, stall_seconds: float) -> None:
        with self._lock:
            if self._pump_in_hitch:
                return
            self._pump_in_hitch = True
            self._pump_hitch_started_mono = now_mono - stall_seconds
            self._pump_hitch_late = False
            self._pump_hitch_poll_lag_s = 0.0
            self._pump_hitch_detected_by = "pump_gap"
            suppressed_count = self._pump_hitch_rate_limiter.admit(now_mono)
            self._pump_hitch_was_recorded = suppressed_count is not None
        if suppressed_count is None:
            return
        record = self._hitch_record(
            "tui_pump_hitch",
            stall_seconds,
            threshold_seconds=self._pump_hitch_threshold_seconds,
            suppressed_count=suppressed_count,
            late=False,
            poll_lag_s=0.0,
            detected_by="pump_gap",
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
            late = self._pump_hitch_late
            poll_lag_s = self._pump_hitch_poll_lag_s
            detected_by = self._pump_hitch_detected_by
            self._pump_in_hitch = False
            self._pump_hitch_started_mono = None
            self._pump_hitch_was_recorded = False
            self._pump_hitch_late = False
            self._pump_hitch_poll_lag_s = 0.0
            self._pump_hitch_detected_by = "pump_gap"
        if started is None:
            return
        duration = now_mono - started
        self._accumulate_hitch_totals("pump", duration, was_recorded)
        if not was_recorded:
            return
        overlap_s, generations, triggers = _gc_overlap(started, now_mono)
        log_tui_stall(
            self._hitch_recovery_record(
                "tui_pump_hitch_recovered",
                duration,
                late=late,
                poll_lag_s=poll_lag_s,
                detected_by=detected_by,
                gc_overlap_s=overlap_s,
                gc_generations=generations,
                gc_triggers=triggers,
            )
        )
        log.info("TUI message pump recovered from hitch after %.3fs", duration)

    def _accumulate_hitch_totals(
        self, tier: str, duration_seconds: float, recorded: bool
    ) -> None:
        """Count one recovered episode toward the heartbeat totals.

        ``tier`` is ``"loop"`` or ``"pump"``. Rate-limited episodes still
        count their duration; they additionally count as suppressed.
        """
        duration = max(0.0, duration_seconds)
        with self._lock:
            if tier == "pump":
                self._pump_hitch_episodes += 1
                self._pump_hitch_seconds += duration
                if not recorded:
                    self._pump_suppressed_episodes += 1
                    self._pump_suppressed_seconds += duration
            else:
                self._loop_hitch_episodes += 1
                self._loop_hitch_seconds += duration
                if not recorded:
                    self._loop_suppressed_episodes += 1
                    self._loop_suppressed_seconds += duration

    def _record_stall(self, now_mono: float, stall_seconds: float) -> None:
        with self._lock:
            if self._in_stall:
                return
            self._in_stall = True
            self._stall_started_mono = now_mono - stall_seconds
        record = self._stall_record(
            stall_seconds,
            late=False,
            poll_lag_s=0.0,
            detected_by="loop_gap",
        )
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
        overlap_s, generations, triggers = _gc_overlap(started, now_mono)
        log_tui_stall(
            self._recovery_record(
                "tui_stall_recovered",
                duration,
                threshold_seconds=self._threshold_seconds,
                poll_interval_seconds=self._poll_interval_seconds,
                gc_overlap_s=overlap_s,
                gc_generations=generations,
                gc_triggers=triggers,
            )
        )
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
            late=False,
            poll_lag_s=0.0,
            detected_by="pump_gap",
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
        overlap_s, generations, triggers = _gc_overlap(started, now_mono)
        log_tui_stall(
            self._recovery_record(
                "tui_pump_stall_recovered",
                duration,
                threshold_seconds=self._pump_threshold_seconds,
                poll_interval_seconds=self._pump_poll_interval_seconds,
                gc_overlap_s=overlap_s,
                gc_generations=generations,
                gc_triggers=triggers,
            )
        )
        log.warning("TUI message pump recovered after %.3fs", duration)

    def _net_stall_seconds(
        self,
        duration_seconds: float,
        *,
        threshold_seconds: float,
        poll_interval_seconds: float,
    ) -> float:
        """Duration minus one poll interval, floored at the tier threshold.

        The subtraction accounts for detection quantization: the stall could
        have started at any point since the previous poll. The floor keeps an
        admitted episode from reporting a net duration below the threshold
        that admitted it. ``stall_seconds`` itself is left unchanged.
        """
        net = duration_seconds - poll_interval_seconds
        return round(max(net, threshold_seconds), 3)

    def _stall_record(
        self,
        stall_seconds: float,
        *,
        late: bool = False,
        poll_lag_s: float = 0.0,
        detected_by: str = "loop_gap",
    ) -> dict[str, Any]:
        context = self._context()
        stack = format_thread_stack(self._loop_thread_ident)
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": "tui_stall",
            "pid": os.getpid(),
            "stall_seconds": round(stall_seconds, 3),
            "threshold_seconds": self._threshold_seconds,
            "poll_interval_seconds": self._poll_interval_seconds,
            "late": late,
            "poll_lag_s": round(max(0.0, poll_lag_s), 3),
            "net_stall_seconds": self._net_stall_seconds(
                stall_seconds,
                threshold_seconds=self._threshold_seconds,
                poll_interval_seconds=self._poll_interval_seconds,
            ),
            "detected_by": detected_by,
            "loop_thread_ident": self._loop_thread_ident,
            "watchdog_thread_ident": threading.get_ident(),
            "main_thread_stack": stack,
            "pause_depth": self._current_pause_depth(),
            "sase_version": sase_version(),
        }
        instance_id = self._app_instance_id
        if instance_id is not None:
            record["app_instance_id"] = instance_id
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
        late: bool = False,
        poll_lag_s: float = 0.0,
        detected_by: str = "loop_gap",
    ) -> dict[str, Any]:
        poll_interval_seconds = (
            self._pump_poll_interval_seconds
            if event.startswith("tui_pump_")
            else self._poll_interval_seconds
        )
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            "pid": os.getpid(),
            "stall_seconds": round(stall_seconds, 3),
            "threshold_seconds": threshold_seconds,
            "late": late,
            "poll_lag_s": round(max(0.0, poll_lag_s), 3),
            "net_stall_seconds": self._net_stall_seconds(
                stall_seconds,
                threshold_seconds=threshold_seconds,
                poll_interval_seconds=poll_interval_seconds,
            ),
            "detected_by": detected_by,
            "main_thread_stack": format_thread_stack(self._loop_thread_ident),
            "suppressed_count": suppressed_count,
        }
        instance_id = self._app_instance_id
        if instance_id is not None:
            record["app_instance_id"] = instance_id
        for key, value in self._context().items():
            if value is not None:
                record[key] = value
        return record

    def _hitch_recovery_record(
        self,
        event: str,
        duration_seconds: float,
        *,
        late: bool = False,
        poll_lag_s: float = 0.0,
        detected_by: str = "loop_gap",
        gc_overlap_s: float = 0.0,
        gc_generations: list[int] | None = None,
        gc_triggers: list[str] | None = None,
    ) -> dict[str, Any]:
        threshold_seconds, poll_interval_seconds = (
            (self._pump_hitch_threshold_seconds, self._pump_poll_interval_seconds)
            if event.startswith("tui_pump_")
            else (self._hitch_threshold_seconds, self._poll_interval_seconds)
        )
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            "pid": os.getpid(),
            "duration_seconds": round(duration_seconds, 3),
            "late": late,
            "poll_lag_s": round(max(0.0, poll_lag_s), 3),
            "net_stall_seconds": self._net_stall_seconds(
                duration_seconds,
                threshold_seconds=threshold_seconds,
                poll_interval_seconds=poll_interval_seconds,
            ),
            "detected_by": detected_by,
            "gc_overlap_s": round(max(0.0, gc_overlap_s), 3),
            "gc_generations": list(gc_generations) if gc_generations else [],
            "gc_triggers": list(gc_triggers) if gc_triggers else [],
            "main_thread_stack": format_thread_stack(self._loop_thread_ident),
        }
        instance_id = self._app_instance_id
        if instance_id is not None:
            record["app_instance_id"] = instance_id
        for key, value in self._context().items():
            if value is not None:
                record[key] = value
        return record

    def _pump_stall_record(
        self,
        stall_seconds: float,
        *,
        capture_tasks: bool,
        late: bool = False,
        poll_lag_s: float = 0.0,
        detected_by: str = "pump_gap",
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
            "late": late,
            "poll_lag_s": round(max(0.0, poll_lag_s), 3),
            "net_stall_seconds": self._net_stall_seconds(
                stall_seconds,
                threshold_seconds=self._pump_threshold_seconds,
                poll_interval_seconds=self._pump_poll_interval_seconds,
            ),
            "detected_by": detected_by,
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
        instance_id = self._app_instance_id
        if instance_id is not None:
            record["app_instance_id"] = instance_id
        for key, value in self._context().items():
            if value is not None:
                record[key] = value
        return record

    def _recovery_record(
        self,
        event: str,
        duration_seconds: float,
        *,
        threshold_seconds: float,
        poll_interval_seconds: float,
        gc_overlap_s: float = 0.0,
        gc_generations: list[int] | None = None,
        gc_triggers: list[str] | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            "pid": os.getpid(),
            "duration_seconds": round(duration_seconds, 3),
            "net_stall_seconds": self._net_stall_seconds(
                duration_seconds,
                threshold_seconds=threshold_seconds,
                poll_interval_seconds=poll_interval_seconds,
            ),
            "gc_overlap_s": round(max(0.0, gc_overlap_s), 3),
            "gc_generations": list(gc_generations) if gc_generations else [],
            "gc_triggers": list(gc_triggers) if gc_triggers else [],
            "pause_depth": self._current_pause_depth(),
            "sase_version": sase_version(),
        }
        instance_id = self._app_instance_id
        if instance_id is not None:
            record["app_instance_id"] = instance_id
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


def _gc_overlap(
    hitch_start_mono: float, hitch_end_mono: float
) -> tuple[float, list[int], list[str]]:
    """Attribute GC pause time to a recovered stall window.

    Queries the GC telemetry ring for collections ending at or after the
    hitch start and sums the overlap of each collection with the hitch
    window, returning ``(overlap_seconds, generations, triggers)``. Never
    raises: without GC telemetry (or on any failure) the hitch simply
    reports zero overlap.
    """
    try:
        from .gc_telemetry import recent_collections

        collections = recent_collections(hitch_start_mono)
    except Exception:
        log.debug("GC overlap attribution skipped", exc_info=True)
        return 0.0, [], []
    try:
        overlap = 0.0
        generations: set[int] = set()
        triggers: set[str] = set()
        for entry in collections:
            try:
                start = float(entry["start_mono"])
                end = float(entry["end_mono"])
            except (KeyError, TypeError, ValueError):
                continue
            first = max(start, hitch_start_mono)
            last = min(end, hitch_end_mono)
            if last <= first:
                continue
            overlap += last - first
            try:
                generations.add(int(entry["generation"]))
            except (KeyError, TypeError, ValueError):
                pass
            trigger = entry.get("trigger")
            if isinstance(trigger, str) and trigger:
                triggers.add(trigger)
        return round(overlap, 3), sorted(generations), sorted(triggers)
    except Exception:
        log.debug("GC overlap attribution failed", exc_info=True)
        return 0.0, [], []

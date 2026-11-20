"""GC pause recorder, heartbeat flush, and stall-row emission."""

from __future__ import annotations

import gc
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.ace.tui.util.startup_clock import wall_time_for_mono

from ._gc_telemetry_config import (
    FIRST_HEARTBEAT_DELAY_S,
    FLUSH_INTERVAL_S,
    FULL_GENERATION,
    HEARTBEAT_INTERVAL_S,
    NOTABLE_PAUSE_S,
    QUEUE_MAX,
    RATE_LIMIT_PER_MIN,
    RATE_LIMIT_WINDOW_S,
    RECENT_RING_MAX,
    PRESSURE_SAMPLE_INTERVAL_S,
    THREAD_NAME,
    YOUNG_PAUSE_ROW_MIN_S,
)

_PROC_STATUS_PATH = Path("/proc/self/status")
_PROC_STAT_PATH = Path("/proc/self/stat")

_heartbeat_providers: dict[str, Callable[[], dict[str, Any]]] = {}


def emit_stall_row(row: dict[str, Any]) -> None:
    """Write one stall JSONL row through ``sase.logs.log_tui_stall``."""
    from sase.logs import log_tui_stall

    log_tui_stall(row)


def register_heartbeat_provider(name: str, fn: Callable[[], dict[str, Any]]) -> None:
    """Contribute extra fields to each ``tui_memory_heartbeat`` row.

    Providers never overwrite the telemetry core fields. A raising provider
    is skipped for that heartbeat.
    """
    _heartbeat_providers[name] = fn


def unregister_heartbeat_provider(name: str) -> None:
    """Remove a heartbeat provider registered with :func:`register_heartbeat_provider`."""
    _heartbeat_providers.pop(name, None)


def default_executor_heartbeat_fields(loop: Any) -> dict[str, Any]:
    """Return a cheap best-effort gauge for the loop's default executor."""
    if loop is None:
        return {
            "default_executor_workers": None,
            "default_executor_threads": None,
            "default_executor_queue_depth": None,
            "default_executor_saturated": None,
        }
    executor = getattr(loop, "_default_executor", None)
    if executor is None:
        return {
            "default_executor_workers": 0,
            "default_executor_threads": 0,
            "default_executor_queue_depth": 0,
            "default_executor_saturated": False,
        }
    try:
        workers = int(executor._max_workers)
        threads = len(executor._threads)
        queue_depth = int(executor._work_queue.qsize())
        return {
            "default_executor_workers": workers,
            "default_executor_threads": threads,
            "default_executor_queue_depth": queue_depth,
            "default_executor_saturated": (
                workers > 0 and threads >= workers and queue_depth > 0
            ),
        }
    except Exception:  # noqa: BLE001 - diagnostic gauge must never affect heartbeat.
        return {
            "default_executor_workers": None,
            "default_executor_threads": None,
            "default_executor_queue_depth": None,
            "default_executor_saturated": None,
        }


class GCTelemetry:
    """One installed GC telemetry instance: recorder plus flush thread."""

    def __init__(
        self,
        *,
        app_instance_id: str,
        flush_interval_s: float = FLUSH_INTERVAL_S,
        heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
        first_heartbeat_delay_s: float = FIRST_HEARTBEAT_DELAY_S,
        rate_limit_per_min: int = RATE_LIMIT_PER_MIN,
        status_path: Path = _PROC_STATUS_PATH,
        stat_path: Path = _PROC_STAT_PATH,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.instance_id = app_instance_id
        self.flush_interval_s = flush_interval_s
        self.heartbeat_interval_s = heartbeat_interval_s
        self.first_heartbeat_delay_s = first_heartbeat_delay_s
        self.rate_limit_per_min = rate_limit_per_min
        self._status_path = status_path
        self._stat_path = stat_path
        self._monotonic = monotonic
        self._wall = wall
        self._emit = emit if emit is not None else emit_stall_row
        self._gen_counts: list[int] = []
        self._gen_total_s: list[float] = []
        self._gen_max_s: list[float] = []
        self._gen1_since_full = 0
        self._young_notable_count = 0
        self._young_notable_total_s = 0.0
        self._young_notable_max_s = 0.0
        self._last_full_end_mono: float | None = None
        self._recent: deque[tuple[int, float, float, str, str]] = deque(
            maxlen=RECENT_RING_MAX
        )
        self._queue: deque[dict[str, Any]] = deque()
        self._queue_dropped = 0
        self._extra_queue: deque[dict[str, Any]] = deque()
        self._extra_queue_dropped = 0
        now = self._monotonic()
        self._install_mono = now
        self._last_heartbeat_mono = now
        self._last_flush_mono = now
        self._next_heartbeat_mono = now + self.first_heartbeat_delay_s
        self._window_start_mono = now
        self._window_admitted = 0
        self._suppressed = 0
        self._last_rss: int | None = None
        self._last_major_faults: int | None = None
        self._last_full_pause_s: float | None = None
        self._next_pressure_sample_mono = now
        self._pressure_sample_mono: float | None = None
        self._pressure_vmswap_bytes: int | None = None
        self._pressure_vmswap_growth_bytes: int | None = None
        self._pressure_major_faults: int | None = None
        self._pressure_major_faults_per_s: float | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def latest_rss(self) -> int | None:
        """Latest RSS sample in bytes, or ``None`` before the first sample."""
        return self._last_rss

    def _record_stop(
        self,
        generation: int,
        start_mono: float,
        end_mono: float,
        thread: str,
        trigger: str,
        collected: int,
        uncollectable: int,
        input_age_s: float | None = None,
        major_faults_delta: int | None = None,
    ) -> None:
        duration = end_mono - start_mono
        if duration < 0.0:
            duration = 0.0
        while len(self._gen_counts) <= generation:
            self._gen_counts.append(0)
            self._gen_total_s.append(0.0)
            self._gen_max_s.append(0.0)
        self._gen_counts[generation] += 1
        self._gen_total_s[generation] += duration
        if duration > self._gen_max_s[generation]:
            self._gen_max_s[generation] = duration
        if generation >= FULL_GENERATION:
            self._gen1_since_full = 0
            self._last_full_end_mono = end_mono
            self._last_full_pause_s = round(duration, 6)
        elif generation == 1:
            self._gen1_since_full += 1
        self._recent.append((generation, start_mono, end_mono, thread, trigger))
        if generation < FULL_GENERATION and duration >= NOTABLE_PAUSE_S:
            self._young_notable_count += 1
            self._young_notable_total_s += duration
            if duration > self._young_notable_max_s:
                self._young_notable_max_s = duration
        if generation >= FULL_GENERATION or duration >= YOUNG_PAUSE_ROW_MIN_S:
            record = {
                "generation": generation,
                "duration_s": round(duration, 6),
                "thread": thread,
                "trigger": trigger,
                "collected": collected,
                "uncollectable": uncollectable,
                "start_mono": start_mono,
                "end_mono": end_mono,
                "input_age_s": input_age_s,
                "major_faults_delta": major_faults_delta,
            }
            if len(self._queue) < QUEUE_MAX:
                self._queue.append(record)
            else:
                self._queue_dropped += 1

    def recent_collections(self, since_mono: float) -> list[dict[str, Any]]:
        """Return ring entries ending at or after ``since_mono``."""
        try:
            entries = list(self._recent)
        except (IndexError, RuntimeError):
            return []
        return [
            {
                "generation": generation,
                "start_mono": start_mono,
                "end_mono": end_mono,
                "thread": thread,
                "trigger": trigger,
            }
            for generation, start_mono, end_mono, thread, trigger in entries
            if end_mono >= since_mono
        ]

    def last_full_collection_mono(self) -> float | None:
        """End time of the latest full collection, if any was recorded."""
        return self._last_full_end_mono

    def gen1_since_last_full(self) -> int:
        """Gen-1 collections recorded since the latest full collection."""
        return self._gen1_since_full

    def last_full_pause_s(self) -> float | None:
        """Duration of the latest full collection observed by the callback."""
        return self._last_full_pause_s

    def memory_pressure_snapshot(self) -> dict[str, int | float | None] | None:
        """Return the latest off-thread swap and major-fault sample."""
        sampled = self._pressure_sample_mono
        if sampled is None:
            return None
        return {
            "vmswap_bytes": self._pressure_vmswap_bytes,
            "vmswap_growth_bytes": self._pressure_vmswap_growth_bytes,
            "major_faults_per_s": self._pressure_major_faults_per_s,
            "sample_age_s": max(0.0, self._monotonic() - sampled),
        }

    def queue_row(self, event: str, extra: dict[str, Any]) -> None:
        """Queue an auxiliary telemetry row for the existing flush worker."""
        if len(self._extra_queue) >= QUEUE_MAX:
            self._extra_queue_dropped += 1
            return
        row: dict[str, Any] = {
            "event": event,
            "ts": self._wall(),
            "pid": os.getpid(),
            "app_instance_id": self.instance_id,
        }
        for key, value in extra.items():
            row.setdefault(key, value)
        self._extra_queue.append(row)

    def start(self) -> None:
        """Start the daemon flush thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=THREAD_NAME,
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the flush thread to exit and wait briefly for it."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self.flush_interval_s):
            try:
                self._poll()
            except Exception:
                continue

    def _poll(self) -> None:
        now = self._monotonic()
        if now >= self._next_pressure_sample_mono:
            self._next_pressure_sample_mono = now + PRESSURE_SAMPLE_INTERVAL_S
            self._sample_memory_pressure(now)
        if now - self._last_flush_mono >= self.flush_interval_s:
            self._last_flush_mono = now
            self._flush_queued(now)
        if now >= self._next_heartbeat_mono:
            self._next_heartbeat_mono = now + self.heartbeat_interval_s
            self._write_heartbeat(now)

    def _sample_memory_pressure(self, now: float) -> None:
        """Refresh cached pressure probes away from the Textual event loop."""
        rss, swap = _read_status_bytes(self._status_path)
        major = _read_major_faults(self._stat_path)
        if rss is not None:
            self._last_rss = rss
        # Growth since the previous sample is the paging signal; a residual
        # level that stays flat is not pressure.
        previous_swap = self._pressure_vmswap_bytes
        self._pressure_vmswap_growth_bytes = (
            None if swap is None or previous_swap is None else swap - previous_swap
        )
        self._pressure_vmswap_bytes = swap
        previous_major = self._pressure_major_faults
        previous_mono = self._pressure_sample_mono
        if major is None:
            self._pressure_major_faults_per_s = None
        elif previous_major is None or previous_mono is None:
            self._pressure_major_faults_per_s = 0.0
        else:
            elapsed = max(0.0, now - previous_mono)
            self._pressure_major_faults_per_s = (
                None if elapsed <= 0.0 else max(0, major - previous_major) / elapsed
            )
        if major is not None:
            self._pressure_major_faults = major
        self._pressure_sample_mono = now

    def _flush_queued(self, now: float) -> None:
        if now - self._window_start_mono >= RATE_LIMIT_WINDOW_S:
            self._window_start_mono = now
            self._window_admitted = 0
        while self._extra_queue:
            row = self._extra_queue.popleft()
            if self._extra_queue_dropped:
                row.setdefault("suppressed_count", self._extra_queue_dropped)
                self._extra_queue_dropped = 0
            self._emit(row)
        while self._queue:
            if self._window_admitted >= self.rate_limit_per_min:
                self._suppressed += len(self._queue)
                self._suppressed += self._queue_dropped
                self._queue_dropped = 0
                self._queue.clear()
                return
            record = self._queue.popleft()
            suppressed = self._suppressed + self._queue_dropped
            self._suppressed = 0
            self._queue_dropped = 0
            self._window_admitted += 1
            self._emit(self._pause_row(record, suppressed))

    def _pause_row(self, record: dict[str, Any], suppressed: int) -> dict[str, Any]:
        start_mono = record["start_mono"]
        start_ts = wall_time_for_mono(
            start_mono, wall_now=self._wall(), mono_now=self._monotonic()
        )
        input_age = record.get("input_age_s")
        return {
            "event": "tui_gc_pause",
            "ts": self._wall(),
            "pid": os.getpid(),
            "app_instance_id": self.instance_id,
            "generation": record["generation"],
            "duration_s": record["duration_s"],
            "thread": record["thread"],
            "trigger": record["trigger"],
            "collected": record["collected"],
            "uncollectable": record["uncollectable"],
            "suppressed_count": suppressed,
            "start_ts": round(start_ts, 6),
            "input_age_s": (None if input_age is None else round(float(input_age), 6)),
            "major_faults_delta": record.get("major_faults_delta"),
        }

    def _write_heartbeat(self, now: float) -> None:
        rss, swap = _read_status_bytes(self._status_path)
        major = _read_major_faults(self._stat_path)
        major_delta: int | None = None
        if major is not None:
            if self._last_major_faults is not None:
                major_delta = max(0, major - self._last_major_faults)
            self._last_major_faults = major
        if rss is not None:
            self._last_rss = rss
        uptime_s = round(now - self._install_mono, 6)
        window_s = round(now - self._last_heartbeat_mono, 6)
        self._last_heartbeat_mono = now
        generations: dict[str, dict[str, float | int]] = {}
        for generation in range(len(self._gen_counts)):
            count = self._gen_counts[generation]
            total = self._gen_total_s[generation]
            peak = self._gen_max_s[generation]
            # Subtract what was read so a collection landing mid-heartbeat
            # stays counted in the next window instead of being lost.
            self._gen_counts[generation] -= count
            self._gen_total_s[generation] -= total
            if self._gen_max_s[generation] <= peak:
                self._gen_max_s[generation] = 0.0
            generations[str(generation)] = {
                "count": count,
                "total_s": round(total, 6),
                "max_s": round(peak, 6),
            }
        young_count = self._young_notable_count
        young_total = self._young_notable_total_s
        young_peak = self._young_notable_max_s
        self._young_notable_count -= young_count
        self._young_notable_total_s -= young_total
        if self._young_notable_max_s <= young_peak:
            self._young_notable_max_s = 0.0
        row: dict[str, Any] = {
            "event": "tui_memory_heartbeat",
            "ts": time.time(),
            "pid": os.getpid(),
            "app_instance_id": self.instance_id,
            "uptime_s": uptime_s,
            "window_s": window_s,
            "rss_bytes": rss,
            "vmswap_bytes": swap,
            "major_faults": major,
            "major_faults_delta": major_delta,
            "major_faults_per_s": self._pressure_major_faults_per_s,
            "pressure_sample_age_s": (
                None
                if self._pressure_sample_mono is None
                else round(max(0.0, now - self._pressure_sample_mono), 3)
            ),
            "gc_count": list(gc.get_count()),
            "gc_threshold": list(gc.get_threshold()),
            "gc_freeze_count": _freeze_count(),
            "gc_generations": generations,
            # Young collections that paused >= NOTABLE_PAUSE_S in this window,
            # whether or not they also earned a ``tui_gc_pause`` row.
            "gc_young_notable": {
                "count": young_count,
                "total_s": round(young_total, 6),
                "max_s": round(young_peak, 6),
            },
            "gc_stats": _gc_stats(),
            "allocated_blocks": _allocated_blocks(),
            "python_version": _python_version(),
        }
        for provider in list(_heartbeat_providers.values()):
            try:
                extra = provider()
            except Exception:
                continue
            if isinstance(extra, dict):
                for key, value in extra.items():
                    row.setdefault(key, value)
        self._emit(row)


def _read_status_bytes(path: Path) -> tuple[int | None, int | None]:
    """Read RSS and VmSwap in bytes from a ``/proc/self/status`` file."""
    rss: int | None = None
    swap: int | None = None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            rss = _parse_kb_line(line)
        elif line.startswith("VmSwap:"):
            swap = _parse_kb_line(line)
        if rss is not None and swap is not None:
            break
    return rss, swap


def _parse_kb_line(line: str) -> int | None:
    parts = line.split()
    if len(parts) < 2:
        return None
    try:
        value = int(parts[1])
    except ValueError:
        return None
    if len(parts) >= 3 and parts[2] == "kB":
        value *= 1024
    return value


def _read_major_faults(path: Path) -> int | None:
    """Read the major-fault counter from a ``/proc/self/stat`` file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        after_comm = text[text.rfind(")") + 2 :].split()
        return int(after_comm[9])
    except (ValueError, IndexError):
        return None


def _freeze_count() -> int | None:
    freeze_count = getattr(gc, "get_freeze_count", None)
    if not callable(freeze_count):
        return None
    try:
        return int(freeze_count())
    except Exception:
        return None


def _gc_stats() -> list[dict[str, int]] | None:
    get_stats = getattr(gc, "get_stats", None)
    if not callable(get_stats):
        return None
    try:
        stats = get_stats()
    except Exception:
        return None
    if not isinstance(stats, list):
        return None
    return stats


def _allocated_blocks() -> int | None:
    getter = getattr(sys, "getallocatedblocks", None)
    if not callable(getter):
        return None
    try:
        return int(getter())
    except Exception:
        return None


def _python_version() -> str:
    return sys.version.split()[0]

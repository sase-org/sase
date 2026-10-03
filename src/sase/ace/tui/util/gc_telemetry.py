"""GC pause recorder and memory heartbeat for the ACE TUI.

A lock-free ``gc.callbacks`` recorder tags every collection with its trigger
(``"automatic"`` unless wrapped in :func:`gc_trigger`), keeps exact
per-generation running totals, a bounded ring of recent collections for
watchdog overlap attribution, and a bounded queue of notable pauses. A daemon
flush thread drains the queue into ``tui_gc_pause`` rows and writes a
5-minute ``tui_memory_heartbeat`` row. Both go through
``sase.logs.log_tui_stall`` into ``tui_stalls.jsonl``; the Rust perf-log
aggregator only counts ``STALL_EVENTS``/``RECOVERY_EVENTS``, so the new row
kinds need no ``sase-core`` change.

Only the ``gc.callbacks`` entry point is constrained: a collection can fire
while the flusher holds a lock, so the callback performs plain attribute
updates and ``deque`` appends only. The flush thread may use locks, I/O,
and logging freely.
"""

from __future__ import annotations

import gc
import os
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ENV_DISABLE = "SASE_TUI_GC_TELEMETRY_DISABLE"
ENV_FLUSH_INTERVAL = "SASE_TUI_GC_TELEMETRY_FLUSH_SECONDS"
ENV_HEARTBEAT_INTERVAL = "SASE_TUI_GC_TELEMETRY_HEARTBEAT_SECONDS"

FLUSH_INTERVAL_S = 2.0
HEARTBEAT_INTERVAL_S = 5 * 60.0
FIRST_HEARTBEAT_DELAY_S = 15.0
RATE_LIMIT_PER_MIN = 60
RATE_LIMIT_WINDOW_S = 60.0
RECENT_RING_MAX = 256
QUEUE_MAX = 2048
NOTABLE_PAUSE_S = 0.050
FULL_GENERATION = 2
THREAD_NAME = "sase-tui-gc-telemetry"

UNTAGGED_TRIGGER = "automatic"

_PROC_STATUS_PATH = Path("/proc/self/status")
_PROC_STAT_PATH = Path("/proc/self/stat")


class _PendingStart(threading.local):
    """Per-thread in-flight collection state for the ``gc`` callback."""

    start_mono: float | None
    thread: str
    trigger: str

    def __init__(self) -> None:
        self.start_mono = None
        self.thread = ""
        self.trigger = UNTAGGED_TRIGGER


_active: GCTelemetry | None = None
_trigger_tag: str = UNTAGGED_TRIGGER
_pending_start = _PendingStart()
_heartbeat_providers: dict[str, Callable[[], dict[str, Any]]] = {}


def _disabled_by_env() -> bool:
    return os.environ.get(ENV_DISABLE) == "1"


@contextmanager
def gc_trigger(name: str) -> Iterator[None]:
    """Tag collections running inside the block with ``name``.

    The ``gc.callbacks`` entry copies the current tag into each record.
    Untagged collections record as ``"automatic"``. Nesting restores the
    outer tag on exit.
    """
    global _trigger_tag
    previous = _trigger_tag
    _trigger_tag = name
    try:
        yield
    finally:
        _trigger_tag = previous


def register_heartbeat_provider(name: str, fn: Callable[[], dict[str, Any]]) -> None:
    """Contribute extra fields to each ``tui_memory_heartbeat`` row.

    Providers never overwrite the telemetry core fields. A raising provider
    is skipped for that heartbeat.
    """
    _heartbeat_providers[name] = fn


def unregister_heartbeat_provider(name: str) -> None:
    """Remove a heartbeat provider registered with :func:`register_heartbeat_provider`."""
    _heartbeat_providers.pop(name, None)


def new_app_instance_id() -> str:
    """Mint one short random ID per app instance."""
    return secrets.token_hex(4)


def app_instance_id(app: Any) -> str | None:
    """Return the app instance ID minted at construction, if present."""
    value = getattr(app, "_app_instance_id", None)
    return value if isinstance(value, str) and value else None


def latest_rss_bytes() -> int | None:
    """Return the latest heartbeat RSS sample, without touching ``/proc``."""
    active = _active
    if active is None:
        return None
    return active.latest_rss


def recent_collections(since_mono: float) -> list[dict[str, Any]]:
    """Return recent collections ending at or after ``since_mono``."""
    active = _active
    if active is None:
        return []
    return active.recent_collections(since_mono)


def _gc_callback(phase: str, info: dict[str, Any]) -> None:
    recorder = _active
    if recorder is None:
        return
    if phase == "start":
        _pending_start.start_mono = time.monotonic()
        _pending_start.thread = threading.current_thread().name
        _pending_start.trigger = _trigger_tag
    elif phase == "stop":
        end_mono = time.monotonic()
        start_mono = _pending_start.start_mono
        if start_mono is None:
            start_mono = end_mono
        recorder._record_stop(
            int(info.get("generation", 0)),
            start_mono,
            end_mono,
            _pending_start.thread or threading.current_thread().name,
            _pending_start.trigger,
            int(info.get("collected", 0)),
            int(info.get("uncollectable", 0)),
        )
        _pending_start.start_mono = None


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
        self._emit = emit if emit is not None else _emit_stall_row
        self._gen_counts: list[int] = []
        self._gen_total_s: list[float] = []
        self._gen_max_s: list[float] = []
        self._gen1_since_full = 0
        self._last_full_end_mono: float | None = None
        self._recent: deque[tuple[int, float, float, str, str]] = deque(
            maxlen=RECENT_RING_MAX
        )
        self._queue: deque[dict[str, Any]] = deque()
        self._queue_dropped = 0
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
        elif generation == 1:
            self._gen1_since_full += 1
        self._recent.append((generation, start_mono, end_mono, thread, trigger))
        if generation >= FULL_GENERATION or duration >= NOTABLE_PAUSE_S:
            record = {
                "generation": generation,
                "duration_s": round(duration, 6),
                "thread": thread,
                "trigger": trigger,
                "collected": collected,
                "uncollectable": uncollectable,
                "start_mono": start_mono,
                "end_mono": end_mono,
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
        if now - self._last_flush_mono >= self.flush_interval_s:
            self._last_flush_mono = now
            self._flush_queued(now)
        if now >= self._next_heartbeat_mono:
            self._next_heartbeat_mono = now + self.heartbeat_interval_s
            self._write_heartbeat(now)

    def _flush_queued(self, now: float) -> None:
        if now - self._window_start_mono >= RATE_LIMIT_WINDOW_S:
            self._window_start_mono = now
            self._window_admitted = 0
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
        return {
            "event": "tui_gc_pause",
            "ts": time.time(),
            "pid": os.getpid(),
            "app_instance_id": self.instance_id,
            "generation": record["generation"],
            "duration_s": record["duration_s"],
            "thread": record["thread"],
            "trigger": record["trigger"],
            "collected": record["collected"],
            "uncollectable": record["uncollectable"],
            "suppressed_count": suppressed,
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
            "gc_count": list(gc.get_count()),
            "gc_threshold": list(gc.get_threshold()),
            "gc_freeze_count": _freeze_count(),
            "gc_generations": generations,
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


def _emit_stall_row(row: dict[str, Any]) -> None:
    from sase.logs import log_tui_stall

    log_tui_stall(row)


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


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def is_enabled() -> bool:
    """Return whether GC telemetry may install (kill switch aware)."""
    return not _disabled_by_env()


def install_gc_telemetry(
    app: Any = None,
    *,
    flush_interval_s: float | None = None,
    heartbeat_interval_s: float | None = None,
) -> GCTelemetry | None:
    """Install the recorder and flush thread; return the handle or ``None``.

    Safe to call twice: a second install while one is active returns the
    active handle. Never raises: any failure returns ``None``.
    """
    global _active
    try:
        if not is_enabled():
            return None
        callbacks = getattr(gc, "callbacks", None)
        if callbacks is None:
            return None
        active = _active
        if active is not None:
            if _gc_callback not in callbacks:
                callbacks.append(_gc_callback)
            return active
        instance_id = app_instance_id(app) if app is not None else None
        if instance_id is None:
            instance_id = new_app_instance_id()
            if app is not None:
                try:
                    app._app_instance_id = instance_id
                except (AttributeError, TypeError):
                    pass
        telemetry = GCTelemetry(
            app_instance_id=instance_id,
            flush_interval_s=(
                flush_interval_s
                if flush_interval_s is not None
                else _positive_float_env(ENV_FLUSH_INTERVAL, FLUSH_INTERVAL_S)
            ),
            heartbeat_interval_s=(
                heartbeat_interval_s
                if heartbeat_interval_s is not None
                else _positive_float_env(ENV_HEARTBEAT_INTERVAL, HEARTBEAT_INTERVAL_S)
            ),
        )
        callbacks.append(_gc_callback)
        _active = telemetry
        telemetry.start()
        return telemetry
    except Exception:
        return None


def uninstall_gc_telemetry(handle: GCTelemetry | None = None) -> None:
    """Stop the flush thread and remove the callback we installed.

    Only our own callback is removed, so ``gc.callbacks`` is left exactly
    as it was found.
    """
    global _active
    target = handle if handle is not None else _active
    if target is None:
        return
    if _active is target:
        _active = None
    try:
        target.stop()
    except Exception:
        pass
    try:
        callbacks = getattr(gc, "callbacks", None)
        if callbacks is not None and _gc_callback in callbacks:
            callbacks.remove(_gc_callback)
    except Exception:
        pass

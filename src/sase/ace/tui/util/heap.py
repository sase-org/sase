"""Opt-in heap sampler for the long-lived ACE TUI.

Set ``SASE_TUI_HEAP=1`` before starting ``sase ace`` to enable periodic
``tracemalloc`` snapshots. Snapshot collection runs from a pump-free task and
writes compact top-site JSONL records to ``~/.sase/perf/tui_heap.jsonl`` by
default.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import tracemalloc
from pathlib import Path
from typing import Any, cast

from sase.core.paths import sase_subdir

from .pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)

ENV_FLAG = "SASE_TUI_HEAP"
ENV_PATH = "SASE_TUI_HEAP_PATH"
ENV_INTERVAL = "SASE_TUI_HEAP_INTERVAL_SECONDS"
ENV_TOP_N = "SASE_TUI_HEAP_TOP_N"
ENV_NFRAME = "SASE_TUI_HEAP_NFRAME"

DEFAULT_INTERVAL_SECONDS = 5 * 60.0
DEFAULT_TOP_N = 25
DEFAULT_NFRAME = 25
REGISTRY_ATTR = "_heap_sampler_async_tasks"


def is_enabled() -> bool:
    """Return True when ``SASE_TUI_HEAP=1`` is set in the environment."""
    return os.environ.get(ENV_FLAG) == "1"


def _heap_log_path() -> Path:
    """Return the JSONL path for heap samples (env-overridable)."""
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    return sase_subdir("perf") / "tui_heap.jsonl"


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


class TUIHeapSampler:
    """Periodic ``tracemalloc`` snapshot writer for one ACE app process."""

    def __init__(
        self,
        *,
        log_path: Path | None = None,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        top_n: int = DEFAULT_TOP_N,
        nframe: int = DEFAULT_NFRAME,
    ) -> None:
        self.log_path = log_path if log_path is not None else _heap_log_path()
        self.interval_seconds = interval_seconds
        self.top_n = top_n
        self.nframe = nframe
        self._running = False

    @classmethod
    def from_env(cls) -> TUIHeapSampler | None:
        """Build a sampler from env configuration, or ``None`` when disabled."""
        if not is_enabled():
            return None
        return cls(
            interval_seconds=_positive_float_env(
                ENV_INTERVAL,
                DEFAULT_INTERVAL_SECONDS,
            ),
            top_n=_positive_int_env(ENV_TOP_N, DEFAULT_TOP_N),
            nframe=_positive_int_env(ENV_NFRAME, DEFAULT_NFRAME),
        )

    def start_tracing(self) -> None:
        """Start ``tracemalloc`` if this process is not already tracing."""
        if not tracemalloc.is_tracing():
            tracemalloc.start(self.nframe)

    def schedule_sample(self, owner: object, *, reason: str) -> bool:
        """Schedule one sample body through ``spawn_pump_free_task``.

        Returns ``False`` when a previous sample is still running or no event
        loop is available. The heavy snapshot/write body runs in a worker
        thread; the timer callback only spawns the task.
        """
        if self._running:
            return False
        self._running = True
        task = spawn_pump_free_task(
            owner,
            self._sample_async(reason),
            name="tui-heap-sample",
            registry_attr=REGISTRY_ATTR,
        )
        if task is None:
            self._running = False
            return False
        return True

    async def _sample_async(self, reason: str) -> None:
        try:
            await asyncio.to_thread(self.write_sample, reason=reason)
        finally:
            self._running = False

    def write_sample(self, *, reason: str) -> None:
        """Take a snapshot and append a compact top-allocation JSON record."""
        tracing_was_active = tracemalloc.is_tracing()
        self.start_tracing()
        snapshot = tracemalloc.take_snapshot()
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        stats = snapshot.statistics("lineno")[: self.top_n]
        record = {
            "ts": time.time(),
            "pid": os.getpid(),
            "reason": reason,
            "current_bytes": current_bytes,
            "peak_bytes": peak_bytes,
            "top_n": self.top_n,
            "nframe": self.nframe,
            "tracing_was_active": tracing_was_active,
            "sites": [_stat_record(stat) for stat in stats],
        }
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError as exc:
            log.debug("heap sample write failed: %s", exc)


def _stat_record(stat: tracemalloc.Statistic) -> dict[str, Any]:
    frame = stat.traceback[0]
    return {
        "filename": frame.filename,
        "lineno": frame.lineno,
        "size_bytes": stat.size,
        "count": stat.count,
        "traceback": [
            {"filename": tb_frame.filename, "lineno": tb_frame.lineno}
            for tb_frame in stat.traceback
        ],
    }


def start_tui_heap_sampler(app: object) -> object | None:
    """Start the app's configured heap sampler, if present."""
    sampler = getattr(app, "_heap_sampler", None)
    if sampler is None:
        return None
    sampler.start_tracing()
    sampler.schedule_sample(app, reason="startup")
    target = cast(Any, app)
    timer = target.set_interval(
        sampler.interval_seconds,
        lambda: sampler.schedule_sample(app, reason="interval"),
        name="heap-sampler",
    )
    target._heap_sampler_timer = timer
    return timer


def stop_tui_heap_sampler(app: object) -> None:
    """Stop the app's heap sampler timer, if one was registered."""
    timer = getattr(app, "_heap_sampler_timer", None)
    if timer is None:
        return
    stop = getattr(timer, "stop", None)
    if callable(stop):
        stop()
    cast(Any, app)._heap_sampler_timer = None

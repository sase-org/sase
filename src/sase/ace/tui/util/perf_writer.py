"""Bounded off-thread writes for opt-in interaction telemetry."""

from __future__ import annotations

import logging
from functools import cache
import queue
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class PerfWriter:
    """The process's bounded FIFO; enqueue never waits for filesystem I/O."""

    def __init__(self) -> None:
        self._queue: queue.Queue[
            tuple[Callable[[dict[str, Any]], None], dict[str, Any]]
        ] = queue.Queue(2048)
        threading.Thread(target=self._run, name="sase-tui-perf", daemon=True).start()

    def submit(
        self, sink: Callable[[dict[str, Any]], None], row: dict[str, Any]
    ) -> bool:
        try:
            self._queue.put_nowait((sink, row))
        except queue.Full:
            return False
        return True

    def _run(self) -> None:
        while True:
            try:
                sink, row = self._queue.get(timeout=30)
            except queue.Empty:
                # The thread must stay available for the next interaction.
                continue
            try:
                sink(row)
            except Exception:
                log.debug("Interaction telemetry write failed", exc_info=True)
            finally:
                self._queue.task_done()
                del sink, row


@cache
def shared_perf_writer() -> PerfWriter:
    """Start the opt-in writer once, during app construction."""
    return PerfWriter()

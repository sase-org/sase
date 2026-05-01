"""Structured timing helpers for agent launch paths."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


def _timing_info_enabled() -> bool:
    value = os.environ.get("SASE_AGENT_LAUNCH_TIMING", "")
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass
class LaunchTimingRecorder:
    """Collect and log elapsed times for one launch operation.

    Debug logging is always emitted when the logger is configured for it.
    Setting ``SASE_AGENT_LAUNCH_TIMING=1`` promotes the same structured
    records to info-level logs for ad hoc profiling.
    """

    operation: str
    fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._start = time.perf_counter()
        self._stages: list[dict[str, Any]] = []
        self._info_enabled = _timing_info_enabled()

    def __enter__(self) -> LaunchTimingRecorder:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        outcome = "error" if exc_type is not None else "ok"
        self.finish(outcome=outcome)

    @contextmanager
    def stage(self, name: str, **fields: Any) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            record = {"stage": name, "elapsed_ms": elapsed_ms, **fields}
            self._stages.append(record)
            self._log("stage", record)

    def mark(self, name: str, **fields: Any) -> None:
        record = {"stage": name, "elapsed_ms": 0.0, **fields}
        self._stages.append(record)
        self._log("stage", record)

    def finish(self, **fields: Any) -> None:
        if getattr(self, "_finished", False):
            return
        self._finished = True
        total_ms = (time.perf_counter() - self._start) * 1000.0
        record = {
            "total_ms": total_ms,
            "stage_count": len(self._stages),
            **self.fields,
            **fields,
        }
        self._log("summary", record)

    def _log(self, event: str, record: dict[str, Any]) -> None:
        payload = {"operation": self.operation, "event": event, **record}
        log.debug("agent_launch_timing %s", payload)
        if self._info_enabled:
            log.info("agent_launch_timing %s", payload)

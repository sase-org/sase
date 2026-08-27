"""Configuration and rate limiting for the TUI stall watchdog."""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

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
MAX_ASYNCIO_TASK_STACKS = 32
MAX_ASYNCIO_TASK_STACK_DEPTH = 64
_TRUTHY = {"1", "true", "yes", "on"}

ContextProvider = Callable[[], Mapping[str, Any]]


class HitchRateLimiter:
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


def float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default

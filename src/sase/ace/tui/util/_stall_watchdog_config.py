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
# Hitch rows are the compact tier: their main-thread stack keeps only the
# innermost frames (the blocking call and its nearest callers). Recovery rows
# sample after the loop already resumed, so they keep a shorter tail. Full
# hitch stacks were most of ``tui_stalls.jsonl``'s bytes.
HITCH_STACK_DEPTH = 24
HITCH_RECOVERY_STACK_DEPTH = 8
# While a loop stall is ongoing, re-sample the main-thread stack every
# interval (at most ``STALL_RESAMPLE_MAX`` samples, each depth-capped) so the
# ``tui_stall_recovered`` row of a 100-second stall shows more than the one
# stack captured at the threshold.
STALL_RESAMPLE_INTERVAL_SECONDS = 10.0
STALL_RESAMPLE_MAX = 6
STALL_RESAMPLE_STACK_DEPTH = 32
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

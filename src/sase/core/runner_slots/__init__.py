"""Pure runner-slot admission logic."""

from __future__ import annotations

from ._admission import (
    DEFAULT_WAIT_PRIORITY,
    RunnerSlotWaiter,
    better_priority_agent_pending,
    deference_satisfied,
    deference_window_seconds,
    is_root_user_agent_record,
    is_runner_slot_user_agent_record,
    live_runner_slot_waiters,
    may_start,
    normalize_wait_priority,
    runner_slot_waiter_sort_key,
    running_root_agent_count,
)

__all__ = [
    "DEFAULT_WAIT_PRIORITY",
    "RunnerSlotWaiter",
    "better_priority_agent_pending",
    "deference_satisfied",
    "deference_window_seconds",
    "is_root_user_agent_record",
    "is_runner_slot_user_agent_record",
    "live_runner_slot_waiters",
    "may_start",
    "normalize_wait_priority",
    "runner_slot_waiter_sort_key",
    "running_root_agent_count",
]

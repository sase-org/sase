"""Pure runner-slot admission logic."""

from __future__ import annotations

from ._admission import (
    RunnerSlotWaiter,
    is_root_user_agent_record,
    is_runner_slot_user_agent_record,
    live_runner_slot_waiters,
    may_start,
    running_root_agent_count,
)

__all__ = [
    "RunnerSlotWaiter",
    "is_root_user_agent_record",
    "is_runner_slot_user_agent_record",
    "live_runner_slot_waiters",
    "may_start",
    "running_root_agent_count",
]

"""Pure runner-slot admission logic."""

from __future__ import annotations

from ._admission import (
    DEFAULT_WAIT_PRIORITY,
    RunnerSlotWaiter,
    better_priority_agent_pending,
    deference_satisfied,
    deference_window_seconds,
    group_records_by_runner_slot_family,
    is_root_user_agent_record,
    is_real_gate_member_record,
    is_runner_slot_occupying_record,
    is_runner_slot_user_agent_record,
    live_runner_slot_waiters,
    may_start,
    normalize_wait_priority,
    runner_slot_family_key,
    runner_slot_queue_display_key,
    runner_slot_waiter_sort_key,
    running_agent_slot_count,
)

__all__ = [
    "DEFAULT_WAIT_PRIORITY",
    "RunnerSlotWaiter",
    "better_priority_agent_pending",
    "deference_satisfied",
    "deference_window_seconds",
    "group_records_by_runner_slot_family",
    "is_root_user_agent_record",
    "is_real_gate_member_record",
    "is_runner_slot_occupying_record",
    "is_runner_slot_user_agent_record",
    "live_runner_slot_waiters",
    "may_start",
    "normalize_wait_priority",
    "runner_slot_family_key",
    "runner_slot_queue_display_key",
    "runner_slot_waiter_sort_key",
    "running_agent_slot_count",
]

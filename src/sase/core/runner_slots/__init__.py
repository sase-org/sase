"""Runner-slot admission logic and host-wide scan-reuse helpers."""

from __future__ import annotations

from ._admission import (
    DEFAULT_QUEUE_WEIGHT,
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
    runner_capacity_snapshot,
    runner_capacity_snapshot_from_capacity_records,
    runner_slot_candidate_record,
    runner_slot_family_key,
    runner_slot_queue_display_key,
    runner_slot_waiter_sort_key,
    running_agent_slot_count,
)
from ._scan_cache import load_or_refresh_runner_slot_scan
from ._signal import (
    notify_runner_slot_state_changed,
    runner_slot_state_token,
)

__all__ = [
    "DEFAULT_QUEUE_WEIGHT",
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
    "load_or_refresh_runner_slot_scan",
    "may_start",
    "normalize_wait_priority",
    "notify_runner_slot_state_changed",
    "runner_capacity_snapshot",
    "runner_capacity_snapshot_from_capacity_records",
    "runner_slot_candidate_record",
    "runner_slot_family_key",
    "runner_slot_queue_display_key",
    "runner_slot_state_token",
    "runner_slot_waiter_sort_key",
    "running_agent_slot_count",
]

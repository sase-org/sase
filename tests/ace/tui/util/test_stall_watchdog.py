"""Tests for the TUI event-loop stall watchdog (facade).

The tests formerly defined here now live in
`test_stall_watchdog_loop.py` (loop stall/hitch episodes),
`test_stall_watchdog_pump.py` (queue-pump episodes),
`test_stall_watchdog_suspend.py` (pause/resume and suspend-signal wiring),
and `test_stall_watchdog_hitch_truth.py` (watchdog-truth hitch additions).
Shared fakes live under public names in `._stall_watchdog_support`. This
module lazily re-exports every public test so the historic import path keeps
working.

Re-exports resolve through PEP 562 `__getattr__` with no `__dir__` entries,
so pytest collects each test exactly once from its owning module instead of
twice through this facade. Only public test names are re-exported; no
`_`-prefixed name is imported across the split modules.
"""

from __future__ import annotations

# ruff: noqa: F822 -- __all__ entries resolve lazily via __getattr__ below and
# are intentionally not bound statically, so pytest collects each test only
# from its owning module.

import importlib

__all__ = [
    "test_heartbeat_provider_registers_on_start",
    "test_hitch_rows_carry_app_instance_id",
    "test_late_poll_with_serviced_beacon_records_one_late_hitch",
    "test_loop_gap_and_lateness_never_double_record",
    "test_nested_pause_requires_final_resume_before_detection",
    "test_paused_watchdog_emits_no_stall_while_loop_blocked",
    "test_paused_watchdog_quiets_loop_and_pump_beacons",
    "test_pump_stall_record_includes_bounded_worker_thread_stacks",
    "test_pump_stall_record_is_written_synchronously_off_the_loop",
    "test_recovery_attributes_gc_overlap_from_telemetry_ring",
    "test_resumed_watchdog_records_one_later_real_stall",
    "test_subscribe_returns_false_without_watchdog",
    "test_subscribe_tolerates_missing_signal_attributes",
    "test_subscribe_wires_both_signals_immediately",
    "test_suppressed_episodes_count_in_heartbeat_totals",
    "test_watchdog_emits_nothing_while_loop_progresses",
    "test_watchdog_keeps_hitch_and_stall_state_machines_independent",
    "test_watchdog_rate_limits_hitch_episodes_and_reports_suppression",
    "test_watchdog_reads_hitch_thresholds_and_disables_from_env",
    "test_watchdog_records_compact_loop_hitch_and_recovery",
    "test_watchdog_records_compact_pump_hitch_and_recovery",
    "test_watchdog_records_one_stall_with_stack_and_context",
    "test_watchdog_records_pump_stall_stack_and_recovery",
    "test_watchdog_writes_loop_recovery_record",
]

_LAZY_SUBMODULES = (
    ".test_stall_watchdog_loop",
    ".test_stall_watchdog_pump",
    ".test_stall_watchdog_suspend",
    ".test_stall_watchdog_hitch_truth",
)


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    for submodule in _LAZY_SUBMODULES:
        module = importlib.import_module(submodule, __package__)
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

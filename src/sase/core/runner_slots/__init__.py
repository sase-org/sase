"""Runner-slot admission logic and host-wide scan-reuse helpers."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from ._admission import (
    live_runner_slot_waiters,
    running_agent_slot_count,
)
from ._admission_capacity_records import (
    capacity_session_keys_for_core,
    runner_slot_candidate_record,
)
from ._admission_lock import runner_slot_admission_lock, runner_slot_lock_path
from ._admission_ordering import (
    deference_satisfied,
    deference_window_seconds,
    normalize_wait_priority,
    runner_slot_queue_display_key,
    runner_slot_waiter_sort_key,
)
from ._admission_predicates import (
    better_priority_agent_pending,
    group_records_by_runner_slot_agent_session,
    is_real_gate_member_record,
    is_root_user_agent_record,
    is_runner_slot_occupying_record,
    is_runner_slot_user_agent_record,
    runner_slot_agent_session_key,
)
from ._admission_snapshot import (
    runner_capacity_snapshot,
    runner_capacity_snapshot_from_capacity_records,
)
from ._admission_types import (
    DEFAULT_QUEUE_WEIGHT,
    DEFAULT_WAIT_PRIORITY,
    HOLD_ARMER_WAIT_PRIORITY,
    RunnerSlotWaiter,
)
from ._queue_weight import (
    MONITOR_INHERITED_QUEUE_WEIGHT_EXPLICIT_KEY,
    MONITOR_INHERITED_QUEUE_WEIGHT_KEY,
    MONITOR_QUEUE_WEIGHT_OVERRIDDEN_KEY,
    QUEUE_WEIGHT_ERROR,
    inheritable_queue_weight,
    valid_queue_weight,
)
from ._scan_cache import (
    RunnerSlotScanCache,
    load_or_refresh_runner_slot_scan,
    read_runner_slot_scan_cache,
)
from ._signal import (
    notify_runner_slot_state_changed,
    runner_slot_state_token,
)

if TYPE_CHECKING:
    from ._machine_capacity import (
        DISPLAY_RESCAN_INTERVAL_SECONDS as DISPLAY_RESCAN_INTERVAL_SECONDS,
        MachineCapacityRecordInputs as MachineCapacityRecordInputs,
        MachineCapacityReport as MachineCapacityReport,
        machine_capacity_report as machine_capacity_report,
        machine_capacity_report_from_records as machine_capacity_report_from_records,
    )
    from ._scan import (
        RUNNER_SLOT_SCAN_OPTIONS as RUNNER_SLOT_SCAN_OPTIONS,
        collect_runner_slot_records as collect_runner_slot_records,
        record_liveness_probe as record_liveness_probe,
    )

# Display-report and capacity-scan collectors are first used by CLI/list/TUI
# consumers and admission wrappers, not by importing this package at TUI
# startup. Keep them off the app import closure.
_LAZY_EXPORTS = {
    "DISPLAY_RESCAN_INTERVAL_SECONDS": "sase.core.runner_slots._machine_capacity",
    "MachineCapacityRecordInputs": "sase.core.runner_slots._machine_capacity",
    "MachineCapacityReport": "sase.core.runner_slots._machine_capacity",
    "RUNNER_SLOT_SCAN_OPTIONS": "sase.core.runner_slots._scan",
    "collect_runner_slot_records": "sase.core.runner_slots._scan",
    "machine_capacity_report": "sase.core.runner_slots._machine_capacity",
    "machine_capacity_report_from_records": "sase.core.runner_slots._machine_capacity",
    "record_liveness_probe": "sase.core.runner_slots._scan",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


_PEP562_HOOKS = (__getattr__, __dir__)

__all__ = [
    "DEFAULT_QUEUE_WEIGHT",
    "DEFAULT_WAIT_PRIORITY",
    "DISPLAY_RESCAN_INTERVAL_SECONDS",
    "HOLD_ARMER_WAIT_PRIORITY",
    "MONITOR_INHERITED_QUEUE_WEIGHT_EXPLICIT_KEY",
    "MONITOR_INHERITED_QUEUE_WEIGHT_KEY",
    "MONITOR_QUEUE_WEIGHT_OVERRIDDEN_KEY",
    "QUEUE_WEIGHT_ERROR",
    "RUNNER_SLOT_SCAN_OPTIONS",
    "MachineCapacityRecordInputs",
    "MachineCapacityReport",
    "RunnerSlotScanCache",
    "RunnerSlotWaiter",
    "collect_runner_slot_records",
    "inheritable_queue_weight",
    "valid_queue_weight",
    "better_priority_agent_pending",
    "deference_satisfied",
    "deference_window_seconds",
    "group_records_by_runner_slot_agent_session",
    "is_root_user_agent_record",
    "is_real_gate_member_record",
    "is_runner_slot_occupying_record",
    "is_runner_slot_user_agent_record",
    "live_runner_slot_waiters",
    "load_or_refresh_runner_slot_scan",
    "machine_capacity_report",
    "machine_capacity_report_from_records",
    "normalize_wait_priority",
    "notify_runner_slot_state_changed",
    "read_runner_slot_scan_cache",
    "record_liveness_probe",
    "runner_capacity_snapshot",
    "runner_capacity_snapshot_from_capacity_records",
    "runner_slot_admission_lock",
    "capacity_session_keys_for_core",
    "runner_slot_candidate_record",
    "runner_slot_agent_session_key",
    "runner_slot_lock_path",
    "runner_slot_queue_display_key",
    "runner_slot_state_token",
    "runner_slot_waiter_sort_key",
    "running_agent_slot_count",
]

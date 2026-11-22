"""Monitor agent-session members: long-running commands as agent session members.

Package-level names resolve lazily (PEP 562): importing a submodule such as
``sase.monitor.store`` must not pull in the member/start/resume import graph,
which the always-on stale-running sweep never uses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS = {
    "LaneContext": ("sase.monitor.store_lane", "LaneContext"),
    "MIN_MONITOR_REF_LENGTH": ("sase.monitor.store", "MIN_MONITOR_REF_LENGTH"),
    "MONITOR_GO_MARKER": ("sase.monitor.start", "MONITOR_GO_MARKER"),
    "MONITOR_PENDING_MARKER": ("sase.monitor.start", "MONITOR_PENDING_MARKER"),
    "MONITOR_STATES": ("sase.monitor.models", "MONITOR_STATES"),
    "MonitorAlreadyRunningError": ("sase.monitor.models", "MonitorAlreadyRunningError"),
    "MonitorError": ("sase.monitor.models", "MonitorError"),
    "MonitorLaneError": ("sase.monitor.models", "MonitorLaneError"),
    "MonitorRecord": ("sase.monitor.models", "MonitorRecord"),
    "MonitorRefError": ("sase.monitor.models", "MonitorRefError"),
    "MonitorResumeError": ("sase.monitor.resume", "MonitorResumeError"),
    "MonitorResumeResult": ("sase.monitor.resume", "MonitorResumeResult"),
    "MonitorState": ("sase.monitor.models", "MonitorState"),
    "SHORT_MONITOR_ID_LENGTH": ("sase.monitor.naming", "SHORT_MONITOR_ID_LENGTH"),
    "StartMonitorRequest": ("sase.monitor.start", "StartMonitorRequest"),
    "TERMINAL_MONITOR_STATES": ("sase.monitor.models", "TERMINAL_MONITOR_STATES"),
    "active_monitor_for_lane": ("sase.monitor.store_lane", "active_monitor_for_lane"),
    "allocate_monitor_suffix": ("sase.monitor.naming", "allocate_monitor_suffix"),
    "caller_artifacts_dir": ("sase.monitor.store_lane", "caller_artifacts_dir"),
    "create_monitor_member": ("sase.monitor.member", "create_monitor_member"),
    "default_caller": ("sase.monitor.store_lane", "default_caller"),
    "durable_lane_for_record": ("sase.monitor.store_lane", "durable_lane_for_record"),
    "get_monitor": ("sase.monitor.store", "get_monitor"),
    "has_any_monitor": ("sase.monitor.store_lane", "has_any_monitor"),
    "is_monitor_member_record": ("sase.monitor.models", "is_monitor_member_record"),
    "list_monitors": ("sase.monitor.store", "list_monitors"),
    "monitor_blocking_start_for_lane": (
        "sase.monitor.store_lane",
        "monitor_blocking_start_for_lane",
    ),
    "monitor_state_bucket": ("sase.monitor.models", "monitor_state_bucket"),
    "new_monitor_id": ("sase.monitor.naming", "new_monitor_id"),
    "read_monitor_marker": ("sase.monitor.store", "read_monitor_marker"),
    "reconcile_dead_supervisors": ("sase.monitor.store", "reconcile_dead_supervisors"),
    "reconcile_terminal_deliveries": (
        "sase.monitor.store",
        "reconcile_terminal_deliveries",
    ),
    "reconcile_terminal_delivery": (
        "sase.monitor.resume",
        "reconcile_terminal_delivery",
    ),
    "resolve_caller_agent": ("sase.monitor.store_lane", "resolve_caller_agent"),
    "resolve_exact_agent": ("sase.monitor.store_lane", "resolve_exact_agent"),
    "resolve_lane": ("sase.monitor.store_lane", "resolve_lane"),
    "resolve_monitor_ref": ("sase.monitor.store", "resolve_monitor_ref"),
    "resume_monitor": ("sase.monitor.resume", "resume_monitor"),
    "short_monitor_id": ("sase.monitor.naming", "short_monitor_id"),
    "start_monitor": ("sase.monitor.start", "start_monitor"),
    "stop_monitor": ("sase.monitor.store", "stop_monitor"),
}

if TYPE_CHECKING:
    from .member import (
        create_monitor_member,
    )
    from .models import (
        MONITOR_STATES,
        TERMINAL_MONITOR_STATES,
        MonitorAlreadyRunningError,
        MonitorError,
        MonitorLaneError,
        MonitorRecord,
        MonitorRefError,
        MonitorState,
        is_monitor_member_record,
        monitor_state_bucket,
    )
    from .naming import (
        SHORT_MONITOR_ID_LENGTH,
        allocate_monitor_suffix,
        new_monitor_id,
        short_monitor_id,
    )
    from .resume import (
        MonitorResumeError,
        MonitorResumeResult,
        reconcile_terminal_delivery,
        resume_monitor,
    )
    from .start import (
        MONITOR_GO_MARKER,
        MONITOR_PENDING_MARKER,
        StartMonitorRequest,
        start_monitor,
    )
    from .store import (
        MIN_MONITOR_REF_LENGTH,
        get_monitor,
        list_monitors,
        read_monitor_marker,
        reconcile_dead_supervisors,
        reconcile_terminal_deliveries,
        resolve_monitor_ref,
        stop_monitor,
    )
    from .store_lane import (
        LaneContext,
        active_monitor_for_lane,
        caller_artifacts_dir,
        default_caller,
        durable_lane_for_record,
        has_any_monitor,
        monitor_blocking_start_for_lane,
        resolve_caller_agent,
        resolve_exact_agent,
        resolve_lane,
    )

__all__ = [
    "MIN_MONITOR_REF_LENGTH",
    "MONITOR_STATES",
    "SHORT_MONITOR_ID_LENGTH",
    "TERMINAL_MONITOR_STATES",
    "LaneContext",
    "MonitorAlreadyRunningError",
    "MonitorError",
    "MonitorLaneError",
    "MonitorRecord",
    "MonitorRefError",
    "MonitorResumeError",
    "MonitorResumeResult",
    "MonitorState",
    "MONITOR_GO_MARKER",
    "MONITOR_PENDING_MARKER",
    "StartMonitorRequest",
    "active_monitor_for_lane",
    "allocate_monitor_suffix",
    "caller_artifacts_dir",
    "create_monitor_member",
    "default_caller",
    "durable_lane_for_record",
    "get_monitor",
    "has_any_monitor",
    "is_monitor_member_record",
    "list_monitors",
    "monitor_state_bucket",
    "monitor_blocking_start_for_lane",
    "new_monitor_id",
    "read_monitor_marker",
    "reconcile_dead_supervisors",
    "reconcile_terminal_delivery",
    "reconcile_terminal_deliveries",
    "resolve_caller_agent",
    "resolve_exact_agent",
    "resolve_lane",
    "resolve_monitor_ref",
    "short_monitor_id",
    "start_monitor",
    "stop_monitor",
    "resume_monitor",
]


def __getattr__(name: str) -> object:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__

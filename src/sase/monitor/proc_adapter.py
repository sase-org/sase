"""Public facade for projecting monitors onto the shared proc service."""

from __future__ import annotations

from sase.monitor_state import MONITOR_PROC_ORIGIN

from ._proc_adapter_argv import (
    MONITOR_ARGV_PREFIX,
    MONITOR_FOLLOWUP_KIND,
    monitor_proc_argv,
)
from ._proc_adapter_artifacts import settle_monitor_artifacts
from ._proc_adapter_followup import settle_monitor_followup
from ._proc_adapter_projection import named_proc_owns, overlay_proc_on_monitor

__all__ = [
    "MONITOR_ARGV_PREFIX",
    "MONITOR_FOLLOWUP_KIND",
    "MONITOR_PROC_ORIGIN",
    "monitor_proc_argv",
    "overlay_proc_on_monitor",
    "named_proc_owns",
    "settle_monitor_artifacts",
    "settle_monitor_followup",
]

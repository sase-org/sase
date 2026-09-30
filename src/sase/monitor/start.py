"""The ``start`` API used by both the ``sase monitor`` CLI and epic launch.

This module is a facade: it owns no start logic itself and only re-exports
the names its callers have always imported from here. The flow lives next
door: :mod:`sase.monitor.start_flow` (lane resolution and the ordered launch
transaction up to member creation), :mod:`sase.monitor.start_launch` (proc
submit, claim moves, and the running record), :mod:`sase.monitor.request`
(the request and its identity), :mod:`sase.monitor.proc_adapter` (the
proc-service facade), :mod:`sase.monitor.start_lane` (lane and workspace
resolution), :mod:`sase.monitor.start_claim` (RUNNING-field claim moves),
:mod:`sase.monitor.start_continuation` (continuation-record setup),
:mod:`sase.monitor.start_runtime` (proc/claim failure helpers), and
:mod:`sase.monitor.handoff` (giving the lane to the monitor from inside an
agent).
"""

from __future__ import annotations

from sase.procs.spawn import SUPERVISOR_LOG_NAME

from .claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from .followup_prompt import DEFAULT_NEXT_OUTPUT, NEXT_OUTPUT_CHOICES
from .handoff import (
    MONITOR_PENDING_MARKER,
    maybe_handoff_monitor_from_agent,
    will_handoff_monitor_to_agent_runner,
    write_monitor_pending_marker,
)
from .request import (
    DEFAULT_REASON,
    DEFAULT_START_STATUS,
    DEFAULT_STOP_STATUS,
    DEFAULT_TAIL_LINES,
    DEFAULT_TIMEOUT_SECONDS,
    StartMonitorRequest,
)
from .start_flow import start_monitor
from .transaction import MONITOR_GO_MARKER

__all__ = [
    "DEFAULT_NEXT_OUTPUT",
    "DEFAULT_REASON",
    "DEFAULT_START_STATUS",
    "DEFAULT_STOP_STATUS",
    "DEFAULT_TAIL_LINES",
    "DEFAULT_TIMEOUT_SECONDS",
    "MONITOR_GO_MARKER",
    "MONITOR_PENDING_MARKER",
    "MONITOR_WORKSPACE_CLAIM_WORKFLOW",
    "NEXT_OUTPUT_CHOICES",
    "SUPERVISOR_LOG_NAME",
    "StartMonitorRequest",
    "maybe_handoff_monitor_from_agent",
    "start_monitor",
    "will_handoff_monitor_to_agent_runner",
    "write_monitor_pending_marker",
]

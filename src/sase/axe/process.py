"""Public process-control facade for the axe daemon.

This module preserves the historical ``sase.axe.process`` import surface while
the implementation lives in smaller focused modules.
"""

from ._process_probe import get_axe_pid, is_axe_running
from ._process_start import (
    canonical_axe_start_command,
    start_axe_daemon,
    start_axe_daemon_result,
)
from ._process_status import get_axe_status, get_lumberjack_names
from ._process_stop import (
    stop_axe_daemon,
    stop_axe_daemon_result,
)
from ._process_types import (
    AxeStartResult,
    AxeStopResult,
    StartStatus,
)


__all__ = [
    "AxeStartResult",
    "AxeStopResult",
    "StartStatus",
    "canonical_axe_start_command",
    "get_axe_pid",
    "get_axe_status",
    "get_lumberjack_names",
    "is_axe_running",
    "start_axe_daemon",
    "start_axe_daemon_result",
    "stop_axe_daemon",
    "stop_axe_daemon_result",
]

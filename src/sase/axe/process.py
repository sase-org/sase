"""Public process-control facade for the axe daemon.

This module preserves the historical ``sase.axe.process`` import surface while
the implementation lives in smaller focused modules.
"""

from ._process_probe import get_axe_pid, is_axe_running
from ._process_start import canonical_axe_start_command
from ._process_status import get_axe_status, get_lumberjack_names
from ._process_stop import (
    stop_axe_daemon,
    stop_axe_daemon_result,
)
from ._process_types import AxeStopResult


__all__ = [
    "AxeStopResult",
    "canonical_axe_start_command",
    "get_axe_pid",
    "get_axe_status",
    "get_lumberjack_names",
    "is_axe_running",
    "stop_axe_daemon",
    "stop_axe_daemon_result",
]

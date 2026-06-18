"""Public process-control facade for the axe daemon.

This module preserves the historical ``sase.axe.process`` import surface while
the implementation lives in smaller focused modules.
"""

from ._process_probe import get_axe_pid, is_axe_running
from ._process_start import (
    canonical_axe_start_command,
    should_reexec_axe_start_from_canonical,
    start_axe_daemon,
    start_axe_daemon_result,
)
from ._process_status import get_axe_status, get_lumberjack_names
from ._process_stop import (
    stop_axe_daemon,
    stop_axe_daemon_result,
)
from ._process_types import AxeStartResult, AxeStopResult, StartStatus
from .config import AxeConfig


def restart_axe_daemon(config: AxeConfig | None = None) -> int | None:
    """Restart the axe orchestrator and return the new/live PID."""
    stop_axe_daemon()
    return start_axe_daemon(config)


def restart_axe_daemon_result(config: AxeConfig | None = None) -> AxeStartResult:
    """Restart axe and return detailed startup status."""
    stop_axe_daemon_result()
    return start_axe_daemon_result(config)


__all__ = [
    "AxeStartResult",
    "AxeStopResult",
    "StartStatus",
    "canonical_axe_start_command",
    "get_axe_pid",
    "get_axe_status",
    "get_lumberjack_names",
    "is_axe_running",
    "restart_axe_daemon",
    "restart_axe_daemon_result",
    "should_reexec_axe_start_from_canonical",
    "start_axe_daemon",
    "start_axe_daemon_result",
    "stop_axe_daemon",
    "stop_axe_daemon_result",
]

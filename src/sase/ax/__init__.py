"""Legacy axe scheduler package (quarantined).

This package is a copy of sase.axe, preserved as the legacy implementation
while sase.axe is being rewritten with the new Lumberjack/Chop architecture.
"""

from .core import AxeScheduler
from .process import (
    get_axe_pid,
    get_axe_status,
    is_axe_running,
    start_axe_daemon,
    stop_axe_daemon,
)
from .runner_pool import RunnerPool
from .state import (
    AxeMetrics,
    AxeStatus,
    CycleResult,
    read_cycle_result,
    read_errors,
    read_metrics,
    read_pid_file,
    read_status,
)

__all__ = [
    # Core
    "AxeScheduler",
    # Process control
    "get_axe_pid",
    "get_axe_status",
    "is_axe_running",
    "start_axe_daemon",
    "stop_axe_daemon",
    # Runner pool
    "RunnerPool",
    # State reading (for TUI)
    "AxeMetrics",
    "AxeStatus",
    "CycleResult",
    "read_cycle_result",
    "read_errors",
    "read_metrics",
    "read_pid_file",
    "read_status",
]

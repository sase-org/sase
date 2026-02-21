"""Axe scheduler package for sase.

This package provides schedule-based ChangeSpec monitoring for automatically
running hooks, managing workflows, and checking CL status.
"""

from .core import AxeScheduler
from .process import (
    get_axe_pid,
    get_axe_status,
    is_axe_running,
    start_axe_daemon,
    stop_axe_daemon,
)
from .chop_registry import (
    ChopContext,
    get_all_chops,
    get_chop,
    list_chops,
    register_chop,
)
from .config import AxeConfig, LumberjackConfig, load_axe_config
from .runner_pool import RunnerPool, SharedRunnerPool
from .state import (
    AxeMetrics,
    AxeStatus,
    CycleResult,
    LumberjackMetrics,
    LumberjackStatus,
    list_lumberjack_names,
    read_cycle_result,
    read_errors,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_pid,
    read_lumberjack_status,
    read_metrics,
    read_pid_file,
    read_status,
)

__all__ = [
    # Core
    "AxeScheduler",
    # Config
    "AxeConfig",
    "LumberjackConfig",
    "load_axe_config",
    # Process control
    "get_axe_pid",
    "get_axe_status",
    "is_axe_running",
    "start_axe_daemon",
    "stop_axe_daemon",
    # Chop registry
    "ChopContext",
    "get_all_chops",
    "get_chop",
    "list_chops",
    "register_chop",
    # Runner pool
    "RunnerPool",
    "SharedRunnerPool",
    # State reading (for TUI)
    "AxeMetrics",
    "AxeStatus",
    "CycleResult",
    "LumberjackMetrics",
    "LumberjackStatus",
    "list_lumberjack_names",
    "read_cycle_result",
    "read_errors",
    "read_lumberjack_log_tail",
    "read_lumberjack_metrics",
    "read_lumberjack_pid",
    "read_lumberjack_status",
    "read_metrics",
    "read_pid_file",
    "read_status",
]

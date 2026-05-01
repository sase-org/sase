"""Axe scheduler package for sase.

This package provides schedule-based ChangeSpec monitoring for automatically
running hooks, managing workflows, and checking CL status.
"""

from .lumberjack import Lumberjack
from .orchestrator import Orchestrator
from .process import (
    get_axe_pid,
    get_axe_status,
    get_lumberjack_names,
    is_axe_running,
    restart_axe_daemon,
    start_axe_daemon,
    stop_axe_daemon,
)
from .chop_script_context import ChopScriptContext
from .chop_script_runner import discover_chop_script, list_chop_scripts, run_chop_script
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
    "Lumberjack",
    "Orchestrator",
    # Config
    "AxeConfig",
    "LumberjackConfig",
    "load_axe_config",
    # Process control
    "get_axe_pid",
    "get_axe_status",
    "get_lumberjack_names",
    "is_axe_running",
    "restart_axe_daemon",
    "start_axe_daemon",
    "stop_axe_daemon",
    # Chop scripts
    "ChopScriptContext",
    "discover_chop_script",
    "list_chop_scripts",
    "run_chop_script",
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

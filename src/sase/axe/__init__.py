"""Axe scheduler package for sase.

This package provides schedule-based ChangeSpec monitoring for automatically
running hooks, managing workflows, and checking CL status.
"""

from .jack import Jack
from .orchestrator import Orchestrator
from .process import (
    get_axe_pid,
    get_axe_status,
    get_jack_names,
    is_axe_running,
    start_axe_daemon,
    stop_axe_daemon,
)
from .chop_script_context import ChopScriptContext
from .chop_script_runner import discover_chop_script, list_chop_scripts, run_chop_script
from .config import AxeConfig, JackConfig, load_axe_config
from .runner_pool import RunnerPool, SharedRunnerPool
from .state import (
    AxeMetrics,
    AxeStatus,
    CycleResult,
    JackMetrics,
    JackStatus,
    list_jack_names,
    read_cycle_result,
    read_errors,
    read_jack_log_tail,
    read_jack_metrics,
    read_jack_pid,
    read_jack_status,
    read_metrics,
    read_pid_file,
    read_status,
)

__all__ = [
    # Core
    "Jack",
    "Orchestrator",
    # Config
    "AxeConfig",
    "JackConfig",
    "load_axe_config",
    # Process control
    "get_axe_pid",
    "get_axe_status",
    "get_jack_names",
    "is_axe_running",
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
    "JackMetrics",
    "JackStatus",
    "list_jack_names",
    "read_cycle_result",
    "read_errors",
    "read_jack_log_tail",
    "read_jack_metrics",
    "read_jack_pid",
    "read_jack_status",
    "read_metrics",
    "read_pid_file",
    "read_status",
]

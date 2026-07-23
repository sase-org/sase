"""Axe scheduler package for sase.

This package provides schedule-based ChangeSpec monitoring for automatically
running hooks, managing workflows, and checking PR status.
"""

from .lumberjack import Lumberjack
from .lifecycle_journal import read_recent_lifecycle_events
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
from .config_backend import (
    AxeConfigComposition,
    AxeEntryPreview,
    AxeEntrySelector,
    AxeFieldOperation,
    AxeFieldProvenance,
    AxeInventoryEntry,
    AxeMutationPlan,
    AxeRawContribution,
    apply_axe_entry_edit,
    build_axe_config_inventory,
    compose_axe_config,
    plan_axe_entry_edit,
)
from .runner_pool import RunnerPool, SharedRunnerPool
from .status_collector import collect_axe_status, collect_axe_status_snapshot
from .status_models import (
    AXE_STATUS_WIRE_SCHEMA_VERSION,
    AxeDesiredStateRecord,
    AxeLifecycleEvent,
    AxeLumberjackObservation,
    AxeLumberjackStatus,
    AxeMaintenanceRecord,
    AxeOrchestratorObservation,
    AxeOrchestratorStatus,
    AxeProcessObservation,
    AxeRunnerOccupancy,
    AxeStatusCollectionError,
    AxeStatusIssue,
    AxeStatusRequest,
    AxeStatusSnapshot,
    AxeStatusWireError,
    classify_axe_status,
    rehydrate_axe_status_snapshot,
    serialize_axe_status_request,
)
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
    "AxeConfigComposition",
    "AxeEntryPreview",
    "AxeEntrySelector",
    "AxeFieldOperation",
    "AxeFieldProvenance",
    "AxeInventoryEntry",
    "AxeMutationPlan",
    "AxeRawContribution",
    "LumberjackConfig",
    "apply_axe_entry_edit",
    "build_axe_config_inventory",
    "compose_axe_config",
    "load_axe_config",
    "plan_axe_entry_edit",
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
    # Portable whole-system status
    "AXE_STATUS_WIRE_SCHEMA_VERSION",
    "AxeDesiredStateRecord",
    "AxeLifecycleEvent",
    "AxeLumberjackObservation",
    "AxeLumberjackStatus",
    "AxeMaintenanceRecord",
    "AxeOrchestratorObservation",
    "AxeOrchestratorStatus",
    "AxeProcessObservation",
    "AxeRunnerOccupancy",
    "AxeStatusCollectionError",
    "AxeStatusIssue",
    "AxeStatusRequest",
    "AxeStatusSnapshot",
    "AxeStatusWireError",
    "classify_axe_status",
    "collect_axe_status",
    "collect_axe_status_snapshot",
    "rehydrate_axe_status_snapshot",
    "serialize_axe_status_request",
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
    "read_recent_lifecycle_events",
    "read_status",
]

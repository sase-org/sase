"""Axe scheduler package for sase.

This package provides schedule-based Patch monitoring for automatically
running hooks, managing workflows, and checking PR status.

Package-level attributes are lazy re-exports (PEP 562): importing
``sase.axe`` (including implicitly, via ``import sase.axe.<submodule>``)
does not import ``Lumberjack``, ``Orchestrator``, or any other heavy
submodule until the corresponding attribute is actually accessed. This
keeps ``sase_chop_*`` subprocesses — which only ever need one narrow
submodule such as ``chop_script_context`` or ``state`` — from paying for
the full scheduler/orchestrator/status-collector import graph on every
spawn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS = {
    # Core
    "Lumberjack": ("sase.axe.lumberjack", "Lumberjack"),
    "Orchestrator": ("sase.axe.orchestrator", "Orchestrator"),
    "read_recent_lifecycle_events": (
        "sase.axe.lifecycle_journal",
        "read_recent_lifecycle_events",
    ),
    # Config
    "AxeConfig": ("sase.axe.config", "AxeConfig"),
    "AxeConfigComposition": ("sase.axe.config_backend", "AxeConfigComposition"),
    "AxeEntryPreview": ("sase.axe.config_backend", "AxeEntryPreview"),
    "AxeEntrySelector": ("sase.axe.config_backend", "AxeEntrySelector"),
    "AxeFieldOperation": ("sase.axe.config_backend", "AxeFieldOperation"),
    "AxeFieldProvenance": ("sase.axe.config_backend", "AxeFieldProvenance"),
    "AxeInventoryEntry": ("sase.axe.config_backend", "AxeInventoryEntry"),
    "AxeMutationPlan": ("sase.axe.config_backend", "AxeMutationPlan"),
    "AxeRawContribution": ("sase.axe.config_backend", "AxeRawContribution"),
    "LumberjackConfig": ("sase.axe.config", "LumberjackConfig"),
    "apply_axe_entry_edit": ("sase.axe.config_backend", "apply_axe_entry_edit"),
    "build_axe_config_inventory": (
        "sase.axe.config_backend",
        "build_axe_config_inventory",
    ),
    "compose_axe_config": ("sase.axe.config_backend", "compose_axe_config"),
    "load_axe_config": ("sase.axe.config", "load_axe_config"),
    "plan_axe_entry_edit": ("sase.axe.config_backend", "plan_axe_entry_edit"),
    # Process control
    "get_axe_pid": ("sase.axe.process", "get_axe_pid"),
    "get_axe_status": ("sase.axe.process", "get_axe_status"),
    "get_lumberjack_names": ("sase.axe.process", "get_lumberjack_names"),
    "is_axe_running": ("sase.axe.process", "is_axe_running"),
    "restart_axe_daemon": ("sase.axe.process", "restart_axe_daemon"),
    "start_axe_daemon": ("sase.axe.process", "start_axe_daemon"),
    "stop_axe_daemon": ("sase.axe.process", "stop_axe_daemon"),
    # Chop scripts
    "CHOP_OVERRUN_WIRE_SCHEMA_VERSION": (
        "sase.axe.chop_overrun",
        "CHOP_OVERRUN_WIRE_SCHEMA_VERSION",
    ),
    "ChopScriptContext": ("sase.axe.chop_script_context", "ChopScriptContext"),
    "ChopOverrun": ("sase.axe.chop_overrun", "ChopOverrun"),
    "ChopOverrunLevel": ("sase.axe.chop_overrun", "ChopOverrunLevel"),
    "ChopOverrunWireError": ("sase.axe.chop_overrun", "ChopOverrunWireError"),
    "classify_chop_overrun": ("sase.axe.chop_overrun", "classify_chop_overrun"),
    "discover_chop_script": ("sase.axe.chop_script_runner", "discover_chop_script"),
    "list_chop_scripts": ("sase.axe.chop_script_runner", "list_chop_scripts"),
    "run_chop_script": ("sase.axe.chop_script_runner", "run_chop_script"),
    # Runner pool
    "RunnerPool": ("sase.axe.runner_pool", "RunnerPool"),
    "SharedRunnerPool": ("sase.axe.runner_pool", "SharedRunnerPool"),
    # Portable whole-system status
    "AXE_STATUS_WIRE_SCHEMA_VERSION": (
        "sase.axe.status_models",
        "AXE_STATUS_WIRE_SCHEMA_VERSION",
    ),
    "AxeDesiredStateRecord": ("sase.axe.status_models", "AxeDesiredStateRecord"),
    "AxeLifecycleEvent": ("sase.axe.status_models", "AxeLifecycleEvent"),
    "AxeLumberjackObservation": (
        "sase.axe.status_models",
        "AxeLumberjackObservation",
    ),
    "AxeLumberjackStatus": ("sase.axe.status_models", "AxeLumberjackStatus"),
    "AxeMaintenanceRecord": ("sase.axe.status_models", "AxeMaintenanceRecord"),
    "AxeOrchestratorObservation": (
        "sase.axe.status_models",
        "AxeOrchestratorObservation",
    ),
    "AxeOrchestratorStatus": ("sase.axe.status_models", "AxeOrchestratorStatus"),
    "AxeProcessObservation": ("sase.axe.status_models", "AxeProcessObservation"),
    "AxeRunnerOccupancy": ("sase.axe.status_models", "AxeRunnerOccupancy"),
    "AxeStatusCollectionError": (
        "sase.axe.status_models",
        "AxeStatusCollectionError",
    ),
    "AxeStatusIssue": ("sase.axe.status_models", "AxeStatusIssue"),
    "AxeStatusRequest": ("sase.axe.status_models", "AxeStatusRequest"),
    "AxeStatusSnapshot": ("sase.axe.status_models", "AxeStatusSnapshot"),
    "AxeStatusWireError": ("sase.axe.status_models", "AxeStatusWireError"),
    "classify_axe_status": ("sase.axe.status_models", "classify_axe_status"),
    "collect_axe_status": ("sase.axe.status_collector", "collect_axe_status"),
    "collect_axe_status_snapshot": (
        "sase.axe.status_collector",
        "collect_axe_status_snapshot",
    ),
    "rehydrate_axe_status_snapshot": (
        "sase.axe.status_models",
        "rehydrate_axe_status_snapshot",
    ),
    "serialize_axe_status_request": (
        "sase.axe.status_models",
        "serialize_axe_status_request",
    ),
    # State reading (for TUI)
    "AxeMetrics": ("sase.axe.state", "AxeMetrics"),
    "AxeStatus": ("sase.axe.state", "AxeStatus"),
    "CycleResult": ("sase.axe.state", "CycleResult"),
    "LumberjackMetrics": ("sase.axe.state", "LumberjackMetrics"),
    "LumberjackStatus": ("sase.axe.state", "LumberjackStatus"),
    "list_lumberjack_names": ("sase.axe.state", "list_lumberjack_names"),
    "read_cycle_result": ("sase.axe.state", "read_cycle_result"),
    "read_errors": ("sase.axe.state", "read_errors"),
    "read_lumberjack_log_tail": ("sase.axe.state", "read_lumberjack_log_tail"),
    "read_lumberjack_metrics": ("sase.axe.state", "read_lumberjack_metrics"),
    "read_lumberjack_pid": ("sase.axe.state", "read_lumberjack_pid"),
    "read_lumberjack_status": ("sase.axe.state", "read_lumberjack_status"),
    "read_metrics": ("sase.axe.state", "read_metrics"),
    "read_pid_file": ("sase.axe.state", "read_pid_file"),
    "read_status": ("sase.axe.state", "read_status"),
}

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
    "CHOP_OVERRUN_WIRE_SCHEMA_VERSION",
    "ChopScriptContext",
    "ChopOverrun",
    "ChopOverrunLevel",
    "ChopOverrunWireError",
    "classify_chop_overrun",
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

if TYPE_CHECKING:
    from sase.axe.chop_overrun import (
        CHOP_OVERRUN_WIRE_SCHEMA_VERSION,
        ChopOverrun,
        ChopOverrunLevel,
        ChopOverrunWireError,
        classify_chop_overrun,
    )
    from sase.axe.chop_script_context import ChopScriptContext
    from sase.axe.chop_script_runner import (
        discover_chop_script,
        list_chop_scripts,
        run_chop_script,
    )
    from sase.axe.config import AxeConfig, LumberjackConfig, load_axe_config
    from sase.axe.config_backend import (
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
    from sase.axe.lifecycle_journal import read_recent_lifecycle_events
    from sase.axe.lumberjack import Lumberjack
    from sase.axe.orchestrator import Orchestrator
    from sase.axe.process import (
        get_axe_pid,
        get_axe_status,
        get_lumberjack_names,
        is_axe_running,
        restart_axe_daemon,
        start_axe_daemon,
        stop_axe_daemon,
    )
    from sase.axe.runner_pool import RunnerPool, SharedRunnerPool
    from sase.axe.state import (
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
    from sase.axe.status_collector import (
        collect_axe_status,
        collect_axe_status_snapshot,
    )
    from sase.axe.status_models import (
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


def __getattr__(name: str) -> object:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__

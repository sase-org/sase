"""Detection and update operations for supported agent CLIs."""

from .history import (
    AgentCliUpdateRun,
    AgentCliUpdateRunEntry,
    agent_cli_update_journal_path,
    build_agent_cli_update_run,
    read_agent_cli_update_runs,
    record_agent_cli_update_run,
    should_record_run,
)
from .models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUnknownName,
    AgentCliUpdateEntry,
    AgentCliUpdatePlan,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    InstallMethod,
    UpdateResultStatus,
    UpdateStrategy,
    UpdateTrigger,
)
from .operations import (
    collect_agent_cli_statuses,
    detect_agent_cli_statuses_for_names,
    execute_agent_cli_updates,
    list_agent_clis,
    plan_agent_cli_status,
    plan_agent_cli_updates,
)

__all__ = [
    "AgentCliNothingToUpdate",
    "AgentCliStatus",
    "AgentCliUnknownName",
    "AgentCliUpdateEntry",
    "AgentCliUpdatePlan",
    "AgentCliUpdateResult",
    "AgentCliUpdateRun",
    "AgentCliUpdateRunEntry",
    "AgentCliUpdatesReady",
    "InstallMethod",
    "UpdateResultStatus",
    "UpdateStrategy",
    "UpdateTrigger",
    "agent_cli_update_journal_path",
    "build_agent_cli_update_run",
    "collect_agent_cli_statuses",
    "detect_agent_cli_statuses_for_names",
    "execute_agent_cli_updates",
    "list_agent_clis",
    "plan_agent_cli_status",
    "plan_agent_cli_updates",
    "read_agent_cli_update_runs",
    "record_agent_cli_update_run",
    "should_record_run",
]

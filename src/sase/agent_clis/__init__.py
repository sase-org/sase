"""Detection and update operations for supported agent CLIs."""

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
    "AgentCliUpdatesReady",
    "InstallMethod",
    "UpdateResultStatus",
    "UpdateStrategy",
    "collect_agent_cli_statuses",
    "detect_agent_cli_statuses_for_names",
    "execute_agent_cli_updates",
    "list_agent_clis",
    "plan_agent_cli_status",
    "plan_agent_cli_updates",
]

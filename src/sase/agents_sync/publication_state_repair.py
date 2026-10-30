"""Bounded report-and-apply repair for already-published agent-run states.

Preview reads the cached sidecar snapshot plus local marker evidence without
network, sidecar writes, audit writes, or checkpoint advancement. Apply
revalidates against a freshly pulled upstream snapshot under the existing
agents lock and publishes only state changes through the shared protection
and push-recovery path. Full sync, outbox drains, and prompt-archive
publishing never run as a side effect.
"""

from __future__ import annotations

from sase.agents_sync._publication_state_repair_service import (
    repair_agent_run_states,
    repair_project_run_states,
)
from sase.agents_sync._publication_state_repair_types import (
    REPAIR_STATES_APPLY_COMMAND,
    REPAIR_STATES_COMMAND,
    STATE_REPAIR_DEFAULT_LIMIT,
    STATE_REPAIR_MAX_HOODS,
    STATE_REPAIR_MAX_LIMIT,
    STATE_REPAIR_MIN_LIMIT,
    STATE_REPAIR_SCHEMA_VERSION,
    STATE_REPAIR_WORK_BUDGET_SECONDS,
    StateRepairAffected,
    StateRepairReport,
    StateRepairWindowRow,
)

__all__ = [
    "REPAIR_STATES_APPLY_COMMAND",
    "REPAIR_STATES_COMMAND",
    "STATE_REPAIR_DEFAULT_LIMIT",
    "STATE_REPAIR_MAX_HOODS",
    "STATE_REPAIR_MAX_LIMIT",
    "STATE_REPAIR_MIN_LIMIT",
    "STATE_REPAIR_SCHEMA_VERSION",
    "STATE_REPAIR_WORK_BUDGET_SECONDS",
    "StateRepairAffected",
    "StateRepairReport",
    "StateRepairWindowRow",
    "repair_agent_run_states",
    "repair_project_run_states",
]

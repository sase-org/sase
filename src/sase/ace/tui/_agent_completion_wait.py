"""Wait-dependency status aggregation for agent completion targets.

The implementation is split by responsibility across focused private
modules; this facade preserves the established import surface for TUI
callers.
"""

from __future__ import annotations

from sase.ace.tui._agent_completion_wait_maps import (
    agent_status_buckets_for_app,
    agent_wait_status_maps_for_app,
    collect_agent_status_buckets,
    collect_agent_wait_status_maps,
)
from sase.ace.tui._agent_completion_wait_models import (
    AgentWaitStatusMaps,
    WaitAgentStatusCounts,
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
    ZERO_WAIT_DEPENDENCY_STATUS_COUNTS,
)
from sase.ace.tui._agent_completion_wait_queries import (
    clan_unknown_wait_dependency_count,
    has_unresolvable_wait_target,
    missing_wait_dependency_names,
    wait_dependencies_satisfied,
    wait_dependency_status_counts,
    wait_dependency_unknown_targets,
)

__all__ = [
    "AgentWaitStatusMaps",
    "WaitAgentStatusCounts",
    "WaitBeadStatusCounts",
    "WaitDependencyStatusCounts",
    "ZERO_WAIT_DEPENDENCY_STATUS_COUNTS",
    "agent_status_buckets_for_app",
    "agent_wait_status_maps_for_app",
    "clan_unknown_wait_dependency_count",
    "collect_agent_status_buckets",
    "collect_agent_wait_status_maps",
    "has_unresolvable_wait_target",
    "missing_wait_dependency_names",
    "wait_dependency_status_counts",
    "wait_dependency_unknown_targets",
    "wait_dependencies_satisfied",
]

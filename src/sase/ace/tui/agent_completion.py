"""Shared visible-agent completion API for the ACE TUI.

The implementation is split by responsibility across focused private modules;
this facade preserves the established import surface for TUI callers.
"""

from __future__ import annotations

from sase.ace.tui._agent_completion_candidates import (
    agent_prompt_name,
    build_agent_completion_candidates,
    filter_agent_completion_candidates,
)
from sase.ace.tui._agent_completion_models import (
    AgentCompletionCandidate,
    AgentVcsWorkflow,
    neutral_vcs_workflow,
    status_style,
)
from sase.ace.tui._agent_completion_visibility import (
    visible_agent_completion_agents,
)
from sase.ace.tui._agent_completion_wait import (
    AgentWaitStatusMaps,
    agent_status_buckets_for_app,
    agent_wait_status_maps_for_app,
    collect_agent_status_buckets,
    collect_agent_wait_status_maps,
    missing_wait_dependency_names,
    wait_dependencies_satisfied,
)

# Kept for compatibility with existing internal tests and callers.
_collect_agent_status_buckets = collect_agent_status_buckets
_collect_agent_wait_status_maps = collect_agent_wait_status_maps

__all__ = [
    "AgentCompletionCandidate",
    "AgentVcsWorkflow",
    "AgentWaitStatusMaps",
    "_collect_agent_status_buckets",
    "_collect_agent_wait_status_maps",
    "agent_prompt_name",
    "agent_status_buckets_for_app",
    "agent_wait_status_maps_for_app",
    "build_agent_completion_candidates",
    "collect_agent_status_buckets",
    "filter_agent_completion_candidates",
    "missing_wait_dependency_names",
    "neutral_vcs_workflow",
    "status_style",
    "visible_agent_completion_agents",
    "wait_dependencies_satisfied",
]

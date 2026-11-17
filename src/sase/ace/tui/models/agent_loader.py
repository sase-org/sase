"""Functions for loading and aggregating agents from all sources."""

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index_bounded as query_agent_artifact_index,
    scan_agent_artifact_dirs,
    scan_agent_artifacts,
)

from ...hooks.processes import is_process_running
from ...patch import Patch, find_all_patches
from ._agent_loader_artifacts import AgentLoadState
from ._agent_loader_tiered import (
    artifact_dirs_for_normalized_timestamps,
    load_all_agents,
    load_all_workflows,
    load_artifact_delta_agents,
    load_live_plan_agents,
    load_live_plan_agents_for_timestamps,
    load_tiered_agents,
    normalize_timestamps,
)
from ._loader_memos import agent_loader_memos
from ._loaders import (
    get_all_project_files,
    get_workflow_timestamp_dirs,
    load_agents_from_comments,
    load_agents_from_hooks,
    load_agents_from_mentors,
    load_agents_from_running_field,
    load_done_agents,
    load_done_agents_from_snapshot,
    load_running_home_agents,
    load_running_home_agents_from_snapshot,
    load_workflow_agent_steps,
    load_workflow_agent_steps_from_snapshot,
    load_workflow_agents,
    load_workflow_agents_from_snapshot,
    load_workflow_states,
    load_workflow_states_from_snapshot,
)
from ._timestamps import normalize_to_14_digit
from .agent import Agent
from .workflow import WorkflowEntry

find_all_changespecs = find_all_patches  # legacy compatibility alias

__all__ = [
    "Agent",
    "AgentLoadState",
    "Patch",
    "WorkflowEntry",
    "agent_loader_memos",
    "artifact_dirs_for_normalized_timestamps",
    "default_agent_artifact_index_path",
    "find_all_changespecs",  # legacy compatibility alias
    "find_all_patches",
    "get_all_project_files",
    "get_workflow_timestamp_dirs",
    "is_process_running",
    "load_agents_from_comments",
    "load_agents_from_hooks",
    "load_agents_from_mentors",
    "load_agents_from_running_field",
    "load_all_agents",
    "load_all_workflows",
    "load_artifact_delta_agents",
    "load_done_agents",
    "load_done_agents_from_snapshot",
    "load_live_plan_agents",
    "load_live_plan_agents_for_timestamps",
    "load_running_home_agents",
    "load_running_home_agents_from_snapshot",
    "load_tiered_agents",
    "load_workflow_agent_steps",
    "load_workflow_agent_steps_from_snapshot",
    "load_workflow_agents",
    "load_workflow_agents_from_snapshot",
    "load_workflow_states",
    "load_workflow_states_from_snapshot",
    "normalize_timestamps",
    "normalize_to_14_digit",
    "query_agent_artifact_index",
    "scan_agent_artifact_dirs",
    "scan_agent_artifacts",
]

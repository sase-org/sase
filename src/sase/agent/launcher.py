"""Compatibility facade for shared agent-launching APIs.

The implementation is split across focused modules, while this module keeps
the historical ``sase.agent.launcher`` import and monkeypatch paths stable.
"""

from sase.agent.launch_cwd import (
    launch_agent_from_cwd,
    launch_agents_from_cwd,
    launch_planned_bead_work_agents,
    resolve_known_project_vcs_launch_ref,
)
from sase.agent.launch_projects import (
    activate_known_project_for_launch_ref,
    activate_known_project_vcs_refs_for_launch_prompt,
    enable_known_project_for_launch_ref,
    enable_known_project_vcs_refs_for_launch_prompt,
)
from sase.agent.launch_spawn import spawn_agent_subprocess
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.partial_launch import rollback_partial_launch_results

__all__ = [
    "AgentLaunchResult",
    "activate_known_project_for_launch_ref",
    "activate_known_project_vcs_refs_for_launch_prompt",
    "enable_known_project_for_launch_ref",
    "enable_known_project_vcs_refs_for_launch_prompt",
    "launch_agent_from_cwd",
    "launch_agents_from_cwd",
    "launch_planned_bead_work_agents",
    "resolve_known_project_vcs_launch_ref",
    "rollback_partial_launch_results",
    "spawn_agent_subprocess",
]

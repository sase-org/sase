"""Shared types for agent launch orchestration."""

from dataclasses import dataclass


@dataclass
class AgentLaunchResult:
    """Result returned after successfully spawning a background agent."""

    pid: int
    workspace_num: int
    workspace_dir: str
    output_path: str
    project_file: str = ""
    project_name: str = ""
    workflow_name: str = ""
    cl_name: str = ""
    timestamp: str = ""
    artifacts_dir: str = ""
    agent_name: str | None = None

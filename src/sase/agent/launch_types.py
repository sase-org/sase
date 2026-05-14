"""Shared types for agent launch orchestration."""

from dataclasses import dataclass
from typing import Any


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
    scheduler_batch_id: str | None = None
    scheduler_queue_id: str | None = None
    scheduler_slot_id: str | None = None
    scheduler_status: str | None = None
    scheduler_handle: dict[str, Any] | None = None

"""Shared types for agent launch plan execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import LaunchFanoutSlotWire


@dataclass(frozen=True)
class LaunchExecutionContext:
    """Host-resolved context used to execute one or more launch slots."""

    cl_name: str
    project_file: str
    project_name: str
    update_target: str = ""
    history_sort_key: str = ""
    is_home_mode: bool = False
    vcs_ref: tuple[str, str] | None = None
    deferred_workspace: bool = False
    workspace_num: int | None = None
    workspace_dir: str | None = None
    use_preallocated_workspace: bool = False


@dataclass(frozen=True)
class LaunchSpawnRequest:
    """Resolved low-level spawn request for one launch slot."""

    cl_name: str
    project_file: str
    workspace_dir: str
    workspace_num: int
    workflow_name: str
    prompt: str
    timestamp: str
    update_target: str = ""
    project_name: str = ""
    history_sort_key: str = ""
    is_home_mode: bool = False
    vcs_ref: tuple[str, str] | None = None
    deferred_workspace: bool = False
    local_xprompts_file: str | None = None
    extra_env: dict[str, str] | None = None
    transfer_from_pid: int | None = None

    def as_spawn_kwargs(self) -> dict[str, object]:
        """Return keyword arguments accepted by low-level launch spawners."""
        return {
            "cl_name": self.cl_name,
            "project_file": self.project_file,
            "workspace_dir": self.workspace_dir,
            "workspace_num": self.workspace_num,
            "workflow_name": self.workflow_name,
            "prompt": self.prompt,
            "timestamp": self.timestamp,
            "update_target": self.update_target,
            "project_name": self.project_name,
            "history_sort_key": self.history_sort_key,
            "is_home_mode": self.is_home_mode,
            "vcs_ref": self.vcs_ref,
            "deferred_workspace": self.deferred_workspace,
            "local_xprompts_file": self.local_xprompts_file,
            "extra_env": self.extra_env,
            "retry_transfer_from_pid": self.transfer_from_pid,
        }


@dataclass(frozen=True)
class LaunchExecutionRecord:
    """One executed launch slot plus the spawn result, when available."""

    slot: LaunchFanoutSlotWire
    request: LaunchSpawnRequest
    result: AgentLaunchResult | None


@dataclass(frozen=True)
class LaunchExecutionResult:
    """Summary returned after executing a launch fan-out plan."""

    records: list[LaunchExecutionRecord]

    @property
    def results(self) -> list[AgentLaunchResult]:
        return [record.result for record in self.records if record.result is not None]

    @property
    def launched_count(self) -> int:
        return len(self.records)


SpawnCallback = Callable[[LaunchSpawnRequest], AgentLaunchResult | None]
SlotContextCallback = Callable[
    [LaunchFanoutSlotWire, LaunchExecutionContext], LaunchExecutionContext
]
SlotEnvCallback = Callable[[LaunchFanoutSlotWire], dict[str, str]]
SlotLocalXpromptsCallback = Callable[[LaunchFanoutSlotWire], str | None]
SlotExecutedCallback = Callable[[LaunchExecutionRecord], None]


__all__ = [
    "LaunchExecutionContext",
    "LaunchExecutionRecord",
    "LaunchExecutionResult",
    "LaunchSpawnRequest",
    "SlotContextCallback",
    "SlotEnvCallback",
    "SlotExecutedCallback",
    "SlotLocalXpromptsCallback",
    "SpawnCallback",
]

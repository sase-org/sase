"""Wire records for the agent-launch migration boundary.

These dataclasses pin the Python-side JSON contract that later Rust-backed
launch phases will implement. Phase 1 only defines and tests the shapes; no
production launch path consumes these records yet.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

AGENT_LAUNCH_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WorkspaceClaimRequestWire:
    """Request to claim or transfer a launch workspace after process spawn."""

    project_file: str
    workspace_num: int
    workflow_name: str
    pid: int
    cl_name: str = ""
    artifacts_timestamp: str = ""
    transfer_from_pid: int | None = None
    pinned: bool = False


@dataclass(frozen=True)
class WorkspaceClaimOutcomeWire:
    """Result of applying a workspace claim request."""

    success: bool
    workspace_num: int
    project_file: str
    pid: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class AgentLaunchRequestWire:
    """Resolved host request for one low-level agent launch."""

    schema_version: int
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
    vcs_workflow_type: str | None = None
    vcs_ref: str | None = None
    deferred_workspace: bool = False
    local_xprompts_file: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)
    retry_transfer_from_pid: int | None = None


@dataclass(frozen=True)
class AgentLaunchPreparedWire:
    """Prepared process-spawn data derived from an agent launch request."""

    schema_version: int
    prompt_file: str
    output_path: str
    safe_name: str
    argv: list[str]
    cwd: str
    env_delta: dict[str, str] = field(default_factory=dict)
    claim_request: WorkspaceClaimRequestWire | None = None


@dataclass(frozen=True)
class LaunchFanoutSlotWire:
    """One child slot in a planned launch fan-out."""

    prompt: str
    launch_kind: str
    slot_index: int
    timestamp: str | None = None
    workflow_name: str | None = None
    model: str | None = None
    repeat_name: str | None = None
    wait_for_previous: bool = False


@dataclass(frozen=True)
class LaunchFanoutPlanWire:
    """Normalized launch fan-out plan shared by future TUI and CLI callers."""

    schema_version: int
    launch_kind: str
    slots: list[LaunchFanoutSlotWire] = field(default_factory=list)
    requires_sequential_naming_wait: bool = False
    fanout_sleep_seconds: float = 0.0


def agent_launch_wire_to_json_dict(record: Any) -> Any:
    """Project launch wire dataclasses to JSON-safe dict/list/scalar values."""

    if isinstance(record, (list, tuple)):
        return [agent_launch_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {str(k): agent_launch_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def workspace_claim_request_from_dict(
    data: dict[str, Any],
) -> WorkspaceClaimRequestWire:
    return WorkspaceClaimRequestWire(
        project_file=str(data["project_file"]),
        workspace_num=int(data["workspace_num"]),
        workflow_name=str(data["workflow_name"]),
        pid=int(data["pid"]),
        cl_name=str(data.get("cl_name") or ""),
        artifacts_timestamp=str(data.get("artifacts_timestamp") or ""),
        transfer_from_pid=(
            None
            if data.get("transfer_from_pid") is None
            else int(data["transfer_from_pid"])
        ),
        pinned=bool(data.get("pinned", False)),
    )


def launch_fanout_plan_from_dict(data: dict[str, Any]) -> LaunchFanoutPlanWire:
    return LaunchFanoutPlanWire(
        schema_version=int(data["schema_version"]),
        launch_kind=str(data["launch_kind"]),
        slots=[
            LaunchFanoutSlotWire(
                prompt=str(slot["prompt"]),
                launch_kind=str(slot["launch_kind"]),
                slot_index=int(slot["slot_index"]),
                timestamp=(
                    None if slot.get("timestamp") is None else str(slot["timestamp"])
                ),
                workflow_name=(
                    None
                    if slot.get("workflow_name") is None
                    else str(slot["workflow_name"])
                ),
                model=None if slot.get("model") is None else str(slot["model"]),
                repeat_name=(
                    None
                    if slot.get("repeat_name") is None
                    else str(slot["repeat_name"])
                ),
                wait_for_previous=bool(slot.get("wait_for_previous", False)),
            )
            for slot in data.get("slots", [])
        ],
        requires_sequential_naming_wait=bool(
            data.get("requires_sequential_naming_wait", False)
        ),
        fanout_sleep_seconds=float(data.get("fanout_sleep_seconds", 0.0)),
    )


__all__ = [
    "AGENT_LAUNCH_WIRE_SCHEMA_VERSION",
    "AgentLaunchPreparedWire",
    "AgentLaunchRequestWire",
    "LaunchFanoutPlanWire",
    "LaunchFanoutSlotWire",
    "WorkspaceClaimOutcomeWire",
    "WorkspaceClaimRequestWire",
    "agent_launch_wire_to_json_dict",
    "launch_fanout_plan_from_dict",
    "workspace_claim_request_from_dict",
]

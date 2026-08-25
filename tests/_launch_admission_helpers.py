"""Shared fixtures for launch-admission tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchPlanWire,
    LaunchUnitWire,
    ProcUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)
from sase.xprompt.code_value import CodeValue


def agent_result(tmp_path: Path, name: str = "reviewer") -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=321,
        workspace_num=2,
        workspace_dir=str(tmp_path / "ws"),
        output_path=str(tmp_path / "out.log"),
        agent_name=name,
    )


def code() -> CodeValue:
    return CodeValue(
        source="just check",
        language="bash",
        info_string=None,
        digest="b" * 64,
        preview="just check",
    )


def run_plan(
    tmp_path: Path,
    launch_plan: LaunchPlanWire,
    *,
    request_id: str = "req",
    **kwargs: Any,
) -> Any:
    response_dir = tmp_path / "bundle"
    response_dir.mkdir(exist_ok=True)
    result = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": request_id,
            "typed_plan": agent_launch_wire_to_json_dict(launch_plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        **kwargs,
    )
    return result, response_dir


def plan(*units: LaunchUnitWire) -> LaunchPlanWire:
    return LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project="sase",
        content_digest="d" * 64,
        units=list(units),
        approval_preview=["LaunchPlan v1"],
    )


def agent_unit(
    logical_id: str,
    *,
    source_order: int = 0,
    waits: list[WaitTargetWire] | None = None,
    condition: Any = None,
) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=logical_id,
        source_order=source_order,
        payload=AgentUnitWire(
            prompt="Do work", identity="reviewer", identity_explicit=True
        ),
        waits=list(waits or []),
        condition=condition,
    )


def proc_unit(
    logical_id: str,
    cwd: Path,
    *,
    source_order: int = 0,
    condition: Any = None,
) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=logical_id,
        source_order=source_order,
        payload=ProcUnitWire(
            code=code(),
            workspace=False,
            cwd=str(cwd),
        ),
        condition=condition,
    )

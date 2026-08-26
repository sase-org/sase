"""Shared helpers for launch condition workspace tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchPlanWire,
    LaunchUnitWire,
    agent_launch_wire_to_json_dict,
)
from sase.xprompt.code_value import CodeValue, make_code_value


def _code(source: str = "exit 0") -> CodeValue:
    return make_code_value(source, "bash", "bash")


def _unit(source: str = "exit 0") -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id="unit-1",
        source_order=0,
        payload=AgentUnitWire(prompt="Do work", identity="reviewer"),
        condition=LaunchConditionWire(code=_code(source)),
    )


def _plan(
    *units: LaunchUnitWire,
    selected_project: str | None = "sase",
) -> LaunchPlanWire:
    return LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project=selected_project,
        content_digest="d" * 64,
        units=list(units or [_unit()]),
        approval_preview=["LaunchPlan v1"],
    )


def _run_plan(tmp_path: Path) -> tuple[Any, Path]:
    response_dir = tmp_path / "bundle"
    response_dir.mkdir(exist_ok=True)
    stale = tmp_path / "stale"
    stale.mkdir(exist_ok=True)
    result = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-cond-ws",
            "typed_plan": agent_launch_wire_to_json_dict(_plan()),
            "dispatch": {"cwd": str(stale), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        agent_dispatcher=lambda unit, fingerprint: pytest.fail(
            "skipped condition should not dispatch"
        ),
    )
    return result, response_dir


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)

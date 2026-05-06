"""Smoke coverage for the mobile agent bridge workflows."""

from __future__ import annotations

from pathlib import Path

from sase.agent.launcher import AgentLaunchResult
from sase.agent.running import RunningAgentInfo, _KillResult
from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import (
    _kill_mobile_agent,
    _launch_mobile_image_agents,
    _launch_mobile_text_agents,
    _list_mobile_agents,
    _retry_mobile_agent,
)
from tests._mobile_agents_fixtures import _agent, _image_request


def test_mobile_agent_bridge_smoke_launch_list_kill_retry_and_image(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(mobile_agents, "allocate_retry_name", lambda name: f"{name}.1")
    launched_prompts: list[str] = []
    running_names: list[str] = []

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        launched_prompts.append(prompt)
        name = (
            mobile_agents._planned_name_for_prompt(prompt)
            or f"agent-{len(running_names)}"
        )
        running_names.append(name)
        return [
            AgentLaunchResult(
                pid=4000 + len(running_names),
                workspace_num=0,
                workspace_dir="/tmp/ws",
                output_path="/tmp/out",
                project_name="home",
                timestamp=f"260506_16000{len(running_names)}",
            )
        ]

    def fake_running() -> list[RunningAgentInfo]:
        return [_agent(tmp_path, name=name, project="home") for name in running_names]

    def fake_kill(name: str, *, exact_name: bool) -> _KillResult:
        if name in running_names:
            running_names.remove(name)
        return _KillResult(
            True,
            f"Killed agent '{name}' (PID 4001)",
            status="killed",
            pid=4001,
            changed=True,
            artifacts_dir=str(tmp_path / name),
            project="home",
            timestamp="20260506160001",
        )

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)
    monkeypatch.setattr(mobile_agents, "list_running_agents", fake_running)
    monkeypatch.setattr(mobile_agents, "list_all_agents", fake_running)
    monkeypatch.setattr(mobile_agents, "kill_named_agent", fake_kill)

    launch = _launch_mobile_text_agents(
        {
            "schema_version": 1,
            "prompt": "Do smoke work",
            "name": "smoke.text",
            "device_id": "device-one",
        }
    )
    listed = _list_mobile_agents({"schema_version": 1, "device_id": "device-one"})
    killed = _kill_mobile_agent(
        {"schema_version": 1, "name": "smoke.text", "device_id": "device-one"}
    )
    retry = _retry_mobile_agent(
        {"schema_version": 1, "name": "smoke.text", "device_id": "device-one"}
    )
    image = _launch_mobile_image_agents(_image_request(name="smoke.image"))

    assert launch["primary"]["name"] == "smoke.text"
    assert [agent["name"] for agent in listed["agents"]] == ["smoke.text"]
    assert killed["changed"] is True
    assert retry["launch"]["primary"]["name"] == "smoke.text.1"
    assert image["primary"]["name"] == "smoke.image"
    assert "The image has been saved to:" in launched_prompts[-1]
    assert list(
        (tmp_path / "mobile_gateway" / "uploads" / "images" / "device-one").glob(
            "*.png"
        )
    )

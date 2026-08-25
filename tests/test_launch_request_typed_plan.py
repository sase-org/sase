"""Launch approval request typed-plan behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_request import create_launch_approval_request
from sase.agent.launch_request_response import dispatch_approved_launch_request
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import plan_typed_launch_units
from sase.core.agent_launch_wire import agent_launch_wire_to_json_dict
from sase.feature_flags import override_flags
from tests._launch_admission_helpers import agent_result as _agent_result


def test_create_request_omits_typed_plan_when_flag_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    result = create_launch_approval_request(
        {"schema_version": 1, "prompt": "Do work", "reason": "cover flag off"}
    )
    written = json.loads(result.request_path.read_text(encoding="utf-8"))["payload"]
    assert "typed_plan" not in written


def test_create_request_attaches_typed_plan_when_flag_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    with override_flags(typed_launch_units=True):
        result = create_launch_approval_request(
            {"schema_version": 1, "prompt": "Do work", "reason": "cover flag on"}
        )
    written = json.loads(result.request_path.read_text(encoding="utf-8"))["payload"]
    assert written["typed_plan"]["units"][0]["payload"]["kind"] == "agent"
    assert written["plan_digest"] == written["typed_plan"]["content_digest"]
    preview = result.preview_path.read_text(encoding="utf-8")
    assert "## Typed launch plan" in preview
    assert written["typed_plan"]["content_digest"][:12] in preview


def test_old_request_without_typed_plan_uses_compat_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_dir = tmp_path / "launch"
    launch_cwd = tmp_path / "workspace"
    response_dir.mkdir()
    launch_cwd.mkdir()
    (response_dir / "launch_request.json").write_text(
        json.dumps(
            {
                "request_id": "legacy",
                "dispatch": {"cwd": str(launch_cwd), "prompt": "Do work"},
            }
        ),
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        seen["prompt"] = prompt
        seen["cwd"] = Path.cwd()
        return [_agent_result(tmp_path)]

    monkeypatch.setattr("sase.agent.launcher.launch_agents_from_cwd", fake_launch)
    result = dispatch_approved_launch_request(response_dir)
    assert seen["prompt"] == "Do work"
    assert seen["cwd"] == launch_cwd
    assert result.launched_count == 1
    assert result.summary is None


def test_typed_dispatch_result_includes_summary(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units("Do work", selected_project="sase")
    response_dir = tmp_path / "bundle"
    response_dir.mkdir()
    data = {
        "request_id": "typed-1",
        "typed_plan": agent_launch_wire_to_json_dict(plan),
        "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
    }
    result = dispatch_typed_launch_request(
        response_dir,
        data,
        spawn_coordinator=False,
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            "reviewer",
            None,
            [_agent_result(tmp_path)],
        ),
    )
    assert result.summary is not None
    assert result.launched_count == 1
    assert result.admission_complete is True
    assert result.summary.launched == 1
    receipt = json.loads(
        (response_dir / "launch_admission" / "receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["plan_digest"] == plan.content_digest

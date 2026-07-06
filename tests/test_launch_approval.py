"""Tests for launch preview and LaunchApproval response infrastructure."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_executor_types import LaunchExecutionContext
from sase.agent.launch_preview import (
    LAUNCH_REQUEST_FILE,
    build_launch_preview_request,
    write_launch_preview_files,
)
from sase.agent.launch_request import create_launch_approval_request
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import plan_fake_fanout
from sase.integrations.mobile_notifications import execute_mobile_launch_action
from sase.launch_approval_actions import (
    LaunchApprovalActionContext,
    LaunchApprovalActionError,
    execute_launch_approval_response,
    get_auto_launch_approval_action,
)
from sase.notifications import pending_actions
from sase.notifications.models import Notification


def _context(tmp_path: Path) -> LaunchExecutionContext:
    return LaunchExecutionContext(
        cl_name="demo",
        project_file=str(tmp_path / "project.sase"),
        project_name="demo",
        vcs_ref=("gh", "feature"),
    )


def test_launch_preview_request_and_files_cover_batch(tmp_path: Path) -> None:
    plan = plan_fake_fanout("multi_prompt", ["first prompt", "second prompt"])
    request = build_launch_preview_request(
        plan=plan,
        context=_context(tmp_path),
        source_surface="agent",
        request_id="launch-test",
        submitted_prompt="first prompt\n---\nsecond prompt",
        slot_planned_names={0: "demo.1", 1: "demo.2"},
        created_at_unix=10.0,
    )

    assert request["request_id"] == "launch-test"
    assert request["all_or_nothing"] is True
    assert request["slot_count"] == 2
    assert request["slots"][0]["planned_name"] == "demo.1"
    assert request["slots"][0]["workspace"]["vcs_ref"] == "feature"
    assert request["slots"][0]["prompt_sha256"]
    assert request["plan"]["slots"][1]["prompt"] == "second prompt"

    paths = write_launch_preview_files(request, response_dir=tmp_path / "launch")
    written = json.loads(paths["request"].read_text(encoding="utf-8"))
    assert written["request_id"] == "launch-test"
    assert paths["preview"].read_text(encoding="utf-8").startswith("# Launch Preview\n")
    assert paths["response"].name == "launch_response.json"


def test_execute_launch_approval_response_writes_once(tmp_path: Path) -> None:
    response_dir = tmp_path / "launch"
    response_dir.mkdir()
    (response_dir / LAUNCH_REQUEST_FILE).write_text("{}", encoding="utf-8")
    context = LaunchApprovalActionContext(
        id="launch-notification",
        host_files=(),
        host_action_data={"response_dir": str(response_dir)},
    )

    result = execute_launch_approval_response(context, "feedback", feedback="Too broad")

    assert result.response_file == "launch_response.json"
    assert result.response_json == {"action": "reject", "feedback": "Too broad"}
    assert json.loads(result.response_path.read_text(encoding="utf-8")) == {
        "action": "reject",
        "feedback": "Too broad",
    }
    with pytest.raises(LaunchApprovalActionError) as exc_info:
        execute_launch_approval_response(context, "approve")
    assert exc_info.value.code == "conflict_already_handled"


def test_create_launch_request_writes_preview_and_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)

    result = create_launch_approval_request(
        {
            "schema_version": 1,
            "prompt": "%n(foo, reviewer)\nDo work",
            "reason": "Need reviewer follow-up",
            "approval": "required",
            "max_slots": 1,
        },
        source_surface="agent_skill",
    )

    written = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert written["request_id"] == result.request_id
    assert written["source_surface"] == "agent_skill"
    assert written["launch_request"]["reason"] == "Need reviewer follow-up"
    assert written["dispatch"] == {
        "cwd": str(tmp_path),
        "prompt": "%n(foo, reviewer)\nDo work",
    }
    assert result.preview_path.read_text(encoding="utf-8").startswith(
        "# Launch Preview\n"
    )

    from sase.notifications.store import load_notifications

    notifications = load_notifications(include_dismissed=False)
    assert len(notifications) == 1
    assert notifications[0].action == "LaunchApproval"
    assert notifications[0].action_data["request_id"] == result.request_id


def test_approve_launch_response_dispatches_stored_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_dir = tmp_path / "launch"
    launch_cwd = tmp_path / "workspace"
    response_dir.mkdir()
    launch_cwd.mkdir()
    (response_dir / LAUNCH_REQUEST_FILE).write_text(
        json.dumps(
            {
                "request_id": "launch-dispatch",
                "dispatch": {
                    "cwd": str(launch_cwd),
                    "prompt": "%n(foo, reviewer)\nDo work",
                },
            }
        ),
        encoding="utf-8",
    )
    context = LaunchApprovalActionContext(
        id="launch-notification",
        host_files=(),
        host_action_data={"response_dir": str(response_dir)},
    )
    seen: dict[str, object] = {}

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        seen["prompt"] = prompt
        seen["cwd"] = Path.cwd()
        return [
            AgentLaunchResult(
                pid=123,
                workspace_num=1,
                workspace_dir=str(launch_cwd),
                output_path="/tmp/out",
            )
        ]

    monkeypatch.chdir(tmp_path)
    with patch("sase.agent.launcher.launch_agents_from_cwd", fake_launch):
        result = execute_launch_approval_response(context, "approve")

    assert seen == {
        "prompt": "%n(foo, reviewer)\nDo work",
        "cwd": launch_cwd,
    }
    assert result.launched_count == 1
    assert result.response_json == {
        "action": "approve",
        "dispatch_status": "launched",
        "launched_count": 1,
    }
    assert json.loads(result.response_path.read_text(encoding="utf-8")) == {
        "action": "approve",
        "dispatch_status": "launched",
        "launched_count": 1,
    }


def test_mobile_launch_action_writes_response_and_marks_dismissed(
    tmp_path: Path,
) -> None:
    notifications_path = tmp_path / "notifications" / "notifications.jsonl"
    pending_path = tmp_path / "pending_actions" / "actions.json"
    response_dir = tmp_path / "launch"
    response_dir.mkdir()
    (response_dir / "launch_request.json").write_text("{}", encoding="utf-8")
    notification = Notification(
        id="abcdef12-launch",
        timestamp="2026-05-06T12:00:00+00:00",
        sender="launch",
        notes=["launch"],
        files=[],
        action="LaunchApproval",
        action_data={"response_dir": str(response_dir), "request_id": "launch-1"},
    )

    from sase.notifications import store as notification_store

    with (
        patch.object(notification_store, "NOTIFICATIONS_FILE", str(notifications_path)),
        patch.object(pending_actions, "PENDING_ACTIONS_PATH", pending_path),
    ):
        notification_store.append_notification(notification)
        result = execute_mobile_launch_action(
            "abcdef12", "feedback", feedback="Narrow it"
        )
        assert result.response_file == "launch_response.json"
        assert result.response_json == {
            "action": "reject",
            "feedback": "Narrow it",
        }
        assert (
            notification_store.load_notifications(include_dismissed=True)[0].dismissed
            is True
        )


def test_auto_launch_approval_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT_AUTO_APPROVE", "1")
    assert get_auto_launch_approval_action() == "approve"

    monkeypatch.setenv("SASE_AGENT_AUTO_APPROVE_LAUNCH_ACTION", "reject")
    assert get_auto_launch_approval_action() == "reject"

    monkeypatch.delenv("SASE_AGENT_AUTO_APPROVE_LAUNCH_ACTION")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.delenv("SASE_AGENT_AUTO_APPROVE")
    (tmp_path / "agent_meta.json").write_text(
        '{"auto_approve_launch_action": "feedback"}',
        encoding="utf-8",
    )
    assert get_auto_launch_approval_action() == "feedback"

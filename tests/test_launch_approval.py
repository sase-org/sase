"""Tests for LaunchApproval request and response infrastructure."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_preview import LAUNCH_REQUEST_FILE
from sase.agent.launch_request import (
    cancel_launch_approval_request,
    create_launch_approval_request,
    wait_for_launch_approval,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.launch_approval_actions import (
    _LaunchApprovalActionContext,
    LaunchApprovalActionError,
    execute_launch_approval_response,
)


def test_execute_launch_approval_response_writes_once(tmp_path: Path) -> None:
    response_dir = tmp_path / "launch"
    response_dir.mkdir()
    (response_dir / LAUNCH_REQUEST_FILE).write_text("{}", encoding="utf-8")
    context = _LaunchApprovalActionContext(
        id="launch-notification",
        host_files=(),
        host_action_data={"response_dir": str(response_dir)},
    )

    result = execute_launch_approval_response(context, "reject", feedback="Too broad")

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
            "prompt": "%i(reviewer, family=foo)\nDo work",
            "reason": "Need reviewer follow-up",
            "approval": "required",
            "max_slots": 1,
        },
        source_surface="agent_skill",
    )

    envelope = json.loads(result.request_path.read_text(encoding="utf-8"))
    written = envelope["payload"]
    assert envelope["request_id"] == result.request_id
    assert envelope["kind"] == "launch"
    assert envelope["continuation_mode"] == "wait_for_launch"
    assert written["source_surface"] == "agent_skill"
    assert written["launch_request"]["reason"] == "Need reviewer follow-up"
    assert written["dispatch"] == {
        "cwd": str(tmp_path),
        "prompt": "%i(reviewer, family=foo)\nDo work",
    }
    assert envelope["query"] == "approve OR reject"
    assert envelope["primary_branch"] == ["approve"]
    # Rejecting with a note is one decision: the third option id that existed
    # only to carry a string is gone, and `feedback` is a declared input.
    assert [option["id"] for option in envelope["options"]] == ["approve", "reject"]
    reject_option = next(
        option for option in envelope["options"] if option["id"] == "reject"
    )
    assert [field["id"] for field in reject_option["inputs"]] == ["feedback"]
    assert reject_option["input_schema"]["properties"]["feedback"] == {"type": "string"}
    assert reject_option["input_schema"]["required"] == []
    assert all(
        (result.response_dir / option["command"]["argv"][0]).is_file()
        for option in envelope["options"]
    )
    assert result.request_path.name == "request.json"
    assert result.response_path.name == "response.json"
    assert result.preview_path.read_text(encoding="utf-8").startswith(
        "# Launch Preview\n"
    )

    from sase.notifications.store import load_notifications

    notifications = load_notifications(include_dismissed=False)
    assert len(notifications) == 1
    assert notifications[0].action == "LaunchApproval"
    assert notifications[0].action_data["request_id"] == result.request_id
    assert notifications[0].action_data["request_path"] == str(result.request_path)
    assert notifications[0].action_data["response_path"] == str(result.response_path)


def test_neutral_launch_feedback_wait_and_cancellation_are_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    feedback_request = create_launch_approval_request(
        {
            "schema_version": 1,
            "prompt": "Do work",
            "reason": "Need follow-up",
            "max_slots": 1,
        }
    )
    context = _LaunchApprovalActionContext(
        id=feedback_request.notification_id,
        host_files=(str(feedback_request.preview_path),),
        host_action_data={
            "request_id": feedback_request.request_id,
            "request_kind": "launch",
            "response_dir": str(feedback_request.response_dir),
        },
    )

    action = execute_launch_approval_response(
        context, "reject", feedback="Use a smaller fanout"
    )
    outcome = wait_for_launch_approval(feedback_request, poll_interval=0.001)

    assert action.response_file == "response.json"
    assert action.response_json["selected_option_ids"] == ["reject"]
    assert action.response_json["option_inputs"] == {
        "reject": {"feedback": "Use a smaller fanout"}
    }
    assert action.response_json["option_results"] == [
        {
            "id": "reject",
            "result": {
                "action": "reject",
                "feedback": "Use a smaller fanout",
            },
        }
    ]
    assert action.response_json["feedback"] == "Use a smaller fanout"
    # A rejection carrying a note keeps its own reported status even though it
    # no longer answers through an option id of its own.
    assert outcome.status == "feedback"
    assert outcome.selected_option_ids == ("reject",)
    assert outcome.response == action.response_json
    with pytest.raises(LaunchApprovalActionError) as duplicate:
        execute_launch_approval_response(
            context, "reject", feedback="Use a smaller fanout"
        )
    assert duplicate.value.code == "conflict_already_handled"

    cancelled_request = create_launch_approval_request(
        {
            "schema_version": 1,
            "prompt": "Do different work",
            "reason": "Need a second follow-up",
            "max_slots": 1,
        }
    )
    cancel_launch_approval_request(cancelled_request)
    cancelled = wait_for_launch_approval(cancelled_request, poll_interval=0.001)
    assert cancelled.status == "cancelled"


def test_neutral_launch_approval_dispatch_failure_is_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    launch_cwd = tmp_path / "workspace"
    launch_cwd.mkdir()
    monkeypatch.chdir(launch_cwd)
    request = create_launch_approval_request(
        {
            "schema_version": 1,
            "prompt": "Do work",
            "reason": "Need dispatch coverage",
            "max_slots": 1,
        }
    )
    context = _LaunchApprovalActionContext(
        id=request.notification_id,
        host_files=(str(request.preview_path),),
        host_action_data={
            "request_id": request.request_id,
            "request_kind": "launch",
            "response_dir": str(request.response_dir),
        },
    )
    monkeypatch.chdir(tmp_path)
    launch_cwd.rmdir()

    with pytest.raises(LaunchApprovalActionError) as exc_info:
        execute_launch_approval_response(context, "approve")

    assert exc_info.value.code == "dispatch_failed"
    outcome = wait_for_launch_approval(request, poll_interval=0.001)
    assert outcome.status == "dispatch_failed"
    assert "does not exist" in outcome.message
    assert outcome.response["option_results"][0]["result"]["dispatch_status"] == (
        "failed"
    )


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
                    "prompt": "%i(reviewer, family=foo)\nDo work",
                },
            }
        ),
        encoding="utf-8",
    )
    context = _LaunchApprovalActionContext(
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
        "prompt": "%i(reviewer, family=foo)\nDo work",
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

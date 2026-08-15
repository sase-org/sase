"""Tests for resolving launch approvals through mobile and TUI surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._notification_modals import handle_launch_approval
from sase.ace.tui.actions.agents._notification_launch_approval import (
    _read_launch_approval_task_metadata,
)
from sase.ace.tui.modals import LaunchApprovalResult
from sase.agent.launch_preview import LAUNCH_REQUEST_FILE
from sase.agent.launch_request import create_launch_approval_request
from sase.agent.launch_types import AgentLaunchResult
from sase.integrations.mobile_notifications import execute_mobile_gate_action
from sase.notifications import pending_actions
from sase.notifications.models import Notification
from sase.ops.names import LAUNCH_APPROVAL
from tests._project_display_case import ProjectDisplayCase


class _TuiLaunchApprovalApp:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed_screens: list[tuple[object, object]] = []
        self.refresh_count = 0
        self.agent_refresh_sources: list[str] = []
        self.durable_procs: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed_screens.append((screen, callback))

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def request_agents_refresh(self, source: str) -> None:
        self.agent_refresh_sources.append(source)


class _DurableTuiLaunchApprovalApp(_TuiLaunchApprovalApp):
    def _submit_durable_proc(self, *args: object, **kwargs: object) -> object:
        self.durable_procs.append((args, kwargs))
        return object()


def _write_tui_launch_request(
    response_dir: Path,
    launch_cwd: Path,
    *,
    request_id: str = "launch-dispatch",
    prompt: str = "%i(reviewer, family=foo)\nDo work",
    project_name: str = "demo",
    cl_name: str = "demo",
) -> None:
    response_dir.mkdir()
    launch_cwd.mkdir()
    (response_dir / LAUNCH_REQUEST_FILE).write_text(
        json.dumps(
            {
                "request_id": request_id,
                "dispatch": {
                    "cwd": str(launch_cwd),
                    "prompt": prompt,
                },
                "slots": [
                    {
                        "workspace": {
                            "cl_name": cl_name,
                            "project_file": str(launch_cwd / f"{project_name}.sase"),
                            "project_name": project_name,
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _launch_notification(
    response_dir: Path,
    *,
    notification_id: str = "abcdef12-launch",
    request_id: str = "launch-dispatch",
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp="2026-05-06T12:00:00+00:00",
        sender="launch",
        notes=["launch"],
        files=[],
        action="LaunchApproval",
        action_data={"response_dir": str(response_dir), "request_id": request_id},
    )


def _drive_tui_launch_approval(
    app: _TuiLaunchApprovalApp,
    notification: Notification,
    result: LaunchApprovalResult,
) -> None:
    assert handle_launch_approval(app, notification)
    assert len(app.pushed_screens) == 1
    callback = app.pushed_screens[0][1]
    assert callable(callback)
    callback(result)


def _isolated_notification_paths(tmp_path: Path) -> tuple[Path, Path]:
    notifications_path = tmp_path / "notifications" / "notifications.jsonl"
    pending_path = tmp_path / "pending_actions" / "actions.json"
    notifications_path.parent.mkdir()
    pending_path.parent.mkdir()
    return notifications_path, pending_path


def test_mobile_and_tui_resolve_neutral_launch_bundles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    mobile_request = create_launch_approval_request(
        {
            "schema_version": 1,
            "prompt": "Do mobile work",
            "reason": "Need mobile approval",
            "max_slots": 1,
        }
    )

    mobile = execute_mobile_gate_action(
        mobile_request.notification_id[:8],
        ["reject"],
        feedback="Narrow the mobile launch",
    )

    assert mobile.response_file == "response.json"
    assert mobile.response_json["selected_option_ids"] == ["reject"]
    assert mobile.response_json["option_results"][0]["result"]["feedback"] == (
        "Narrow the mobile launch"
    )

    tui_request = create_launch_approval_request(
        {
            "schema_version": 1,
            "prompt": "Do TUI work",
            "reason": "Need TUI approval",
            "max_slots": 1,
        }
    )
    from sase.notifications.store import load_notifications

    notification = next(
        row
        for row in load_notifications(include_dismissed=False)
        if row.id == tui_request.notification_id
    )
    app = _TuiLaunchApprovalApp()
    _drive_tui_launch_approval(
        app,
        notification,
        LaunchApprovalResult(action="reject"),
    )

    response = json.loads(tui_request.response_path.read_text(encoding="utf-8"))
    assert response["selected_option_ids"] == ["reject"]
    assert response["option_results"] == [
        {"id": "reject", "result": {"action": "reject"}}
    ]
    assert app.notifications == [
        ("Rejecting launch...", None),
        ("Launch rejected", None),
    ]


def test_tui_launch_approval_submits_durable_request(tmp_path: Path) -> None:
    response_dir = tmp_path / "launch"
    launch_cwd = tmp_path / "workspace"
    _write_tui_launch_request(response_dir, launch_cwd)
    notification = _launch_notification(response_dir)
    app = _DurableTuiLaunchApprovalApp()

    _drive_tui_launch_approval(
        app,
        notification,
        LaunchApprovalResult(action="reject", feedback="Too broad"),
    )

    [(args, kwargs)] = app.durable_procs
    assert args == (["sase", "launch", "reject", "launch-dispatch"],)
    assert kwargs["operation"] == LAUNCH_APPROVAL
    assert kwargs["request"] == {"feedback": "Too broad"}
    assert kwargs["concurrency_keys"] == ("launch-approval:launch-dispatch",)
    assert kwargs["cl_name"] == "launch approval launch-dispatch"
    assert kwargs["project_file"] == str(response_dir)
    assert app.notifications == [("Rejecting launch...", None)]


def test_tui_launch_approval_approve_dispatches_stored_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_dir = tmp_path / "launch"
    launch_cwd = tmp_path / "workspace"
    _write_tui_launch_request(response_dir, launch_cwd)
    notification = _launch_notification(response_dir)
    app = _TuiLaunchApprovalApp()
    seen: dict[str, object] = {}
    notifications_path, pending_path = _isolated_notification_paths(tmp_path)

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

    from sase.notifications import store as notification_store

    monkeypatch.chdir(tmp_path)
    with (
        patch("sase.agent.launcher.launch_agents_from_cwd", fake_launch),
        patch.object(notification_store, "NOTIFICATIONS_FILE", str(notifications_path)),
        patch.object(pending_actions, "PENDING_ACTIONS_PATH", pending_path),
    ):
        _drive_tui_launch_approval(
            app,
            notification,
            LaunchApprovalResult(action="approve"),
        )

    assert seen == {
        "prompt": "%i(reviewer, family=foo)\nDo work",
        "cwd": launch_cwd,
    }
    assert json.loads((response_dir / "launch_response.json").read_text()) == {
        "action": "approve",
        "dispatch_status": "launched",
        "launched_count": 1,
    }
    assert app.notifications == [
        ("Approving launch...", None),
        ("Launch approved and dispatched 1 agent", None),
    ]
    assert app.refresh_count == 1
    assert app.agent_refresh_sources == ["launch"]


def test_tui_launch_approval_projects_completed_task_label_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    canonical = project_display_case.project_key
    canonical_cl = project_display_case.patch_key
    response_dir = tmp_path / "launch"
    launch_cwd = tmp_path / "workspace"
    _write_tui_launch_request(
        response_dir,
        launch_cwd,
        project_name=canonical,
        cl_name=canonical_cl,
    )
    project_display_case.write_project_layout(
        tmp_path / "sase-home" / "projects",
        workspace_dir=launch_cwd,
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    notification = _launch_notification(response_dir)
    app = _TuiLaunchApprovalApp()
    notifications_path, pending_path = _isolated_notification_paths(tmp_path)
    metadata = _read_launch_approval_task_metadata(notification, "approve")

    assert metadata.display_name == f"approve launch {project_display_case.patch_label}"
    assert metadata.cl_name == canonical_cl
    assert metadata.project_file == str(launch_cwd / f"{canonical}.sase")

    from sase.notifications import store as notification_store

    with (
        patch(
            "sase.agent.launcher.launch_agents_from_cwd",
            return_value=[
                AgentLaunchResult(
                    pid=123,
                    workspace_num=1,
                    workspace_dir=str(launch_cwd),
                    output_path="/tmp/out",
                )
            ],
        ),
        patch.object(notification_store, "NOTIFICATIONS_FILE", str(notifications_path)),
        patch.object(pending_actions, "PENDING_ACTIONS_PATH", pending_path),
    ):
        _drive_tui_launch_approval(
            app,
            notification,
            LaunchApprovalResult(action="approve"),
        )

    stored_request = json.loads(
        (response_dir / LAUNCH_REQUEST_FILE).read_text(encoding="utf-8")
    )
    workspace = stored_request["slots"][0]["workspace"]
    assert workspace["project_name"] == canonical
    assert workspace["cl_name"] == canonical_cl


def test_tui_launch_approval_reject_does_not_dispatch(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "launch"
    launch_cwd = tmp_path / "workspace"
    _write_tui_launch_request(response_dir, launch_cwd)
    notification = _launch_notification(response_dir)
    app = _TuiLaunchApprovalApp()
    notifications_path, pending_path = _isolated_notification_paths(tmp_path)

    from sase.notifications import store as notification_store

    with (
        patch("sase.agent.launcher.launch_agents_from_cwd") as launch,
        patch.object(notification_store, "NOTIFICATIONS_FILE", str(notifications_path)),
        patch.object(pending_actions, "PENDING_ACTIONS_PATH", pending_path),
    ):
        _drive_tui_launch_approval(
            app,
            notification,
            LaunchApprovalResult(action="reject", feedback="Too broad"),
        )

    launch.assert_not_called()
    assert json.loads((response_dir / "launch_response.json").read_text()) == {
        "action": "reject",
        "feedback": "Too broad",
    }
    assert app.notifications == [
        ("Rejecting launch...", None),
        ("Feedback received", None),
    ]
    assert app.refresh_count == 1
    assert app.agent_refresh_sources == []


def test_tui_launch_approval_already_handled_warns_without_dispatch(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "launch"
    launch_cwd = tmp_path / "workspace"
    _write_tui_launch_request(response_dir, launch_cwd)
    (response_dir / "launch_response.json").write_text(
        json.dumps({"action": "approve"}),
        encoding="utf-8",
    )
    notification = _launch_notification(response_dir)
    app = _TuiLaunchApprovalApp()
    notifications_path, pending_path = _isolated_notification_paths(tmp_path)

    from sase.notifications import store as notification_store

    with (
        patch("sase.agent.launcher.launch_agents_from_cwd") as launch,
        patch.object(notification_store, "NOTIFICATIONS_FILE", str(notifications_path)),
        patch.object(pending_actions, "PENDING_ACTIONS_PATH", pending_path),
    ):
        _drive_tui_launch_approval(
            app,
            notification,
            LaunchApprovalResult(action="approve"),
        )

    launch.assert_not_called()
    assert json.loads((response_dir / "launch_response.json").read_text()) == {
        "action": "approve"
    }
    assert app.notifications == [
        ("Approving launch...", None),
        ("Launch request was already handled", "warning"),
    ]
    assert app.refresh_count == 1
    assert app.agent_refresh_sources == []


def test_tui_launch_approval_dispatch_failure_records_failed_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_dir = tmp_path / "launch"
    launch_cwd = tmp_path / "workspace"
    _write_tui_launch_request(response_dir, launch_cwd)
    notification = _launch_notification(response_dir)
    app = _TuiLaunchApprovalApp()
    notifications_path, pending_path = _isolated_notification_paths(tmp_path)

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        del prompt
        raise RuntimeError("launch boom")

    from sase.notifications import store as notification_store

    monkeypatch.chdir(tmp_path)
    with (
        patch("sase.agent.launcher.launch_agents_from_cwd", fake_launch),
        patch.object(notification_store, "NOTIFICATIONS_FILE", str(notifications_path)),
        patch.object(pending_actions, "PENDING_ACTIONS_PATH", pending_path),
    ):
        _drive_tui_launch_approval(
            app,
            notification,
            LaunchApprovalResult(action="approve"),
        )

    assert json.loads((response_dir / "launch_response.json").read_text()) == {
        "action": "approve",
        "dispatch_status": "failed",
        "dispatch_error": "launch boom",
    }
    assert app.notifications == [
        ("Approving launch...", None),
        ("launch boom", "error"),
    ]
    assert app.refresh_count == 1
    assert app.agent_refresh_sources == []

"""Tests for launch preview and LaunchApproval response infrastructure."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._notification_modals import handle_launch_approval
from sase.ace.tui.actions.task_actions import TrackedTaskCompletion
from sase.ace.tui.modals import LaunchApprovalResult
from sase.ace.tui.task_queue import TaskInfo
from sase.agent.launch_executor_types import LaunchExecutionContext
from sase.agent.launch_preview import (
    LAUNCH_REQUEST_FILE,
    build_launch_preview_request,
    render_launch_preview_markdown,
)
from sase.agent.launch_request import (
    cancel_launch_approval_request,
    create_launch_approval_request,
    wait_for_launch_approval,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import plan_fake_fanout
from sase.integrations.mobile_notifications import execute_mobile_gate_action
from sase.launch_approval_actions import (
    _LaunchApprovalActionContext,
    LaunchApprovalActionError,
    execute_launch_approval_response,
)
from sase.notifications import pending_actions
from sase.notifications.models import Notification


class _TuiLaunchApprovalApp:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed_screens: list[tuple[object, object]] = []
        self.refresh_count = 0
        self.agent_refresh_sources: list[str] = []
        self.tracked_tasks: list[dict[str, Any]] = []

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed_screens.append((screen, callback))

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def request_agents_refresh(self, source: str) -> None:
        self.agent_refresh_sources.append(source)

    def _submit_tracked_task(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> TaskInfo:
        del duplicate_message, reload_on_complete, notify_on_complete
        task_info = TaskInfo(
            task_id=f"task-{len(self.tracked_tasks)}",
            task_type=task_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
            dedup_key=dedup_key,
        )
        self.tracked_tasks.append(
            {
                "task_type": task_type,
                "cl_name": cl_name,
                "project_file": project_file,
                "display_name": display_name,
                "dedup_key": dedup_key,
                "task_info": task_info,
            }
        )
        result = task_callable()
        task_info.status = "success" if result.success else "error"
        task_info.message = result.message
        task_info.error = result.error
        if on_complete is not None:
            on_complete(
                TrackedTaskCompletion(
                    task_info=task_info,
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return task_info


def _context(tmp_path: Path) -> LaunchExecutionContext:
    return LaunchExecutionContext(
        cl_name="demo",
        project_file=str(tmp_path / "project.sase"),
        project_name="demo",
        vcs_ref=("gh", "feature"),
    )


def _write_tui_launch_request(
    response_dir: Path,
    launch_cwd: Path,
    *,
    request_id: str = "launch-dispatch",
    prompt: str = "%i(foo, reviewer)\nDo work",
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
                            "cl_name": "demo",
                            "project_file": str(launch_cwd / "demo.sase"),
                            "project_name": "demo",
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


def test_launch_preview_request_covers_batch(tmp_path: Path) -> None:
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


def test_launch_preview_markdown_renders_full_prompt(tmp_path: Path) -> None:
    full_prompt = "\n".join(
        [
            "%i:demo-review",
            "Keep the line structure intact.",
            "x" * 540,
            "#plan",
            "`actstat --repo sase`",
        ]
    )
    request = build_launch_preview_request(
        plan=plan_fake_fanout("agent", [full_prompt]),
        context=_context(tmp_path),
        source_surface="agent_skill",
        request_id="launch-full",
        slot_planned_names={0: "demo.review"},
        created_at_unix=10.0,
    )
    request["slots"][0]["prompt_snippet"] = "truncated snippet only"

    preview = render_launch_preview_markdown(request)

    assert preview.startswith("# Launch Preview\n\n")
    assert (
        "**1 agent** · source `agent_skill` · all-or-nothing · request `launch-full`"
        in preview
    )
    assert "## Agent 1 of 1 · demo" in preview
    assert "model `default` · kind `agent` · name `demo.review`" in preview
    assert f"```sase\n{full_prompt}\n```" in preview
    assert "truncated snippet only" not in preview
    assert f"SHA-256 `{request['slots'][0]['prompt_sha256'][:12]}`" in preview


def test_launch_preview_markdown_uses_safe_fence_for_backticks(
    tmp_path: Path,
) -> None:
    prompt = "\n".join(
        [
            "Explain this embedded fence:",
            "```python",
            "print('hello')",
            "```",
            "and then continue.",
        ]
    )
    request = build_launch_preview_request(
        plan=plan_fake_fanout("agent", [prompt]),
        context=_context(tmp_path),
        source_surface="agent",
        request_id="launch-fence",
        created_at_unix=10.0,
    )

    preview = render_launch_preview_markdown(request)

    assert f"````sase\n{prompt}\n````" in preview


def test_launch_preview_models_come_from_prompt_directives(tmp_path: Path) -> None:
    plan = plan_fake_fanout(
        "multi_prompt",
        [
            "#git:nova %model:claude-sonnet-4-6\nAudit parser handling.",
            "#git:nova %model:gpt-5-codex\nAdd parser tests.",
            "#git:nova %model:gemini-2.5-pro\nReview release notes.",
        ],
    )
    request = build_launch_preview_request(
        plan=plan,
        context=_context(tmp_path),
        source_surface="ace",
        request_id="launch-models",
        submitted_prompt="ignored",
        created_at_unix=10.0,
    )

    models = [slot["model"] for slot in request["slots"]]
    assert models == [
        "claude-sonnet-4-6",
        "gpt-5-codex",
        "gemini-2.5-pro",
    ]

    preview = render_launch_preview_markdown(request)
    assert (
        "**3 agents** · source `ace` · all-or-nothing · models "
        "`claude-sonnet-4-6`, `gpt-5-codex`, `gemini-2.5-pro` · "
        "request `launch-models`"
    ) in preview
    assert "model `claude-sonnet-4-6`" in preview
    assert "model `gpt-5-codex`" in preview
    assert "model `gemini-2.5-pro`" in preview


def test_launch_preview_renders_model_alias_overrides(tmp_path: Path) -> None:
    request = build_launch_preview_request(
        plan=plan_fake_fanout(
            "agent",
            ["%m(opus, coder=sonnet, phase_worker=@coder)\nImplement"],
        ),
        context=_context(tmp_path),
        source_surface="ace",
        request_id="launch-overrides",
        created_at_unix=10.0,
    )

    assert request["slots"][0]["model_alias_overrides"] == {
        "coder": "sonnet",
        "phase_worker": "@coder",
    }
    preview = render_launch_preview_markdown(request)
    assert (
        "model `opus` · alias overrides: coder → sonnet, phase_worker → @coder"
    ) in preview


def test_launch_preview_annotates_rootless_clan_members(tmp_path: Path) -> None:
    request = build_launch_preview_request(
        plan=plan_fake_fanout(
            "multi_prompt",
            [
                "%id:demo.phase-a\n%clan:demo\nImplement",
                "%id:demo.land\n%clan:demo\nLand the clan",
                "%id:demo.review\n%clan:demo\nReview",
            ],
        ),
        context=_context(tmp_path),
        source_surface="agent_skill",
        request_id="launch-clan",
        created_at_unix=10.0,
    )

    preview = render_launch_preview_markdown(request)

    assert preview.count("clan `demo`") == 3
    assert "family root" not in preview


def test_launch_preview_annotates_clan_tribe(tmp_path: Path) -> None:
    request = build_launch_preview_request(
        plan=plan_fake_fanout(
            "multi_prompt",
            ["%id:demo.phase\n%clan(demo, tribe=quality)\nImplement"],
        ),
        context=_context(tmp_path),
        source_surface="agent_skill",
        request_id="launch-clan-tribe",
        created_at_unix=10.0,
    )

    preview = render_launch_preview_markdown(request)

    assert "clan `demo` · tribe `@quality`" in preview


def test_execute_launch_approval_response_writes_once(tmp_path: Path) -> None:
    response_dir = tmp_path / "launch"
    response_dir.mkdir()
    (response_dir / LAUNCH_REQUEST_FILE).write_text("{}", encoding="utf-8")
    context = _LaunchApprovalActionContext(
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
            "prompt": "%i(foo, reviewer)\nDo work",
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
        "prompt": "%i(foo, reviewer)\nDo work",
    }
    assert envelope["query"] == "approve OR reject OR feedback"
    assert envelope["primary_branch"] == ["approve"]
    assert {option["id"] for option in envelope["options"]} == {
        "approve",
        "reject",
        "feedback",
    }
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
        context, "feedback", feedback="Use a smaller fanout"
    )
    outcome = wait_for_launch_approval(feedback_request, poll_interval=0.001)

    assert action.response_file == "response.json"
    assert action.response_json["selected_option_ids"] == ["feedback"]
    assert action.response_json["option_results"] == [
        {
            "id": "feedback",
            "result": {
                "action": "reject",
                "feedback": "Use a smaller fanout",
            },
        }
    ]
    assert action.response_json["feedback"] == "Use a smaller fanout"
    assert outcome.status == "feedback"
    assert outcome.selected_option_ids == ("feedback",)
    assert outcome.response == action.response_json
    with pytest.raises(LaunchApprovalActionError) as duplicate:
        execute_launch_approval_response(
            context, "feedback", feedback="Use a smaller fanout"
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
        ["feedback"],
        feedback="Narrow the mobile launch",
    )

    assert mobile.response_file == "response.json"
    assert mobile.response_json["selected_option_ids"] == ["feedback"]
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
                    "prompt": "%i(foo, reviewer)\nDo work",
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
        "prompt": "%i(foo, reviewer)\nDo work",
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
        "prompt": "%i(foo, reviewer)\nDo work",
        "cwd": launch_cwd,
    }
    assert json.loads((response_dir / "launch_response.json").read_text()) == {
        "action": "approve",
        "dispatch_status": "launched",
        "launched_count": 1,
    }
    assert app.tracked_tasks[0]["task_type"] == "launch"
    assert app.tracked_tasks[0]["dedup_key"] == "launch-approval:launch-dispatch"
    assert app.tracked_tasks[0]["task_info"].cl_name == "demo"
    assert app.notifications == [
        ("Approving launch...", None),
        ("Launch approved and dispatched 1 agent", None),
    ]
    assert app.refresh_count == 1
    assert app.agent_refresh_sources == ["launch"]


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
        ("Launch rejected", None),
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

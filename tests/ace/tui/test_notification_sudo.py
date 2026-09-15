"""ACE coverage for typed sudo request notifications."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from textual.app import SuspendNotSupported

from sase.ace.tui.actions.agents._notification_sudo import (
    _load_sudo_request_modal_data,
    _run_sudo_terminal_handoff,
    _sudo_cli_message,
    handle_sudo_request,
)
from sase.ace.tui.modals import SudoRequestModalData, SudoRequestModalResult
from sase.feature_flags import SASE_FEATURE_FLAGS_ENV, override_flags
from sase.notification_gates.service import create_gate
from sase.notifications import Notification
from sase.notifications.store import load_notifications
from sase.sudo.gate import DENY_OPTION_ID, build_sudo_gate_request


class _SuspendRecorder:
    def __init__(self) -> None:
        self.active = False
        self.enters = 0
        self.exits = 0

    def __enter__(self) -> None:
        self.active = True
        self.enters += 1

    def __exit__(self, *_args: object) -> None:
        self.active = False
        self.exits += 1


class _SudoActionApp:
    def __init__(self, result: object) -> None:
        self.result = result
        self.suspend_recorder = _SuspendRecorder()
        self.notifications: list[tuple[str, str]] = []
        self.refresh_count = 0
        self.agent_refreshes: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.durable_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.screen: object | None = None

    def push_screen(self, screen: object, callback: Any) -> None:
        self.screen = screen
        callback(self.result)

    def suspend(self) -> _SuspendRecorder:
        return self.suspend_recorder

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def request_agents_refresh(self, *args: object, **kwargs: object) -> None:
        self.agent_refreshes.append((args, kwargs))

    def _submit_durable_proc(self, *args: object, **kwargs: object) -> object:
        self.durable_calls.append((args, kwargs))
        return object()


def _sudo_request() -> dict[str, object]:
    executable = shutil.which("true")
    assert executable is not None
    return {
        "reason": "Refresh root-owned cache",
        "commands": [
            {
                "id": "refresh",
                "argv": [executable, "--refresh"],
                "why": "Refresh root-owned cache",
            },
            {
                "id": "verify",
                "argv": [executable, "--verify"],
                "why": "Verify root-owned cache",
            },
        ],
        "run_as": "root",
        "cwd": "/tmp",
        "env": {"LC_ALL": "C"},
        "timeout_seconds": 30,
        "stop_policy": "terminate",
        "output_policy": "bounded",
    }


def _modal_data() -> SudoRequestModalData:
    return SudoRequestModalData(
        request_id="sudo-123",
        title="Sudo request: true",
        sender="sudo",
        reason="Refresh root-owned cache",
        commands=(),
        run_as="root",
        cwd="/tmp",
        env=(),
        timeout_seconds=30,
        stop_policy="terminate",
        output_policy="bounded",
        machine=None,
        manifest_sha256="abc",
        risk_badges=("root",),
    )


def _notification() -> Notification:
    return Notification(
        id="notice-1",
        timestamp="2026-09-14T00:00:00+00:00",
        sender="sudo",
        action="SudoRequest",
        action_data={"request_id": "sudo-123", "request_kind": "sudo"},
    )


def test_sudo_notification_loader_projects_verified_manifest(
    gate_home: Path,
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        create_gate(
            build_sudo_gate_request(
                _sudo_request(),
                producer={"agent": "coder", "project": "sase"},
            )
        )
    notification = load_notifications()[0]
    notification.action_data["project"] = "sase"

    data = _load_sudo_request_modal_data(notification)

    assert data.request_id == notification.action_data["request_id"]
    assert data.title.startswith("Sudo request:")
    assert data.reason == "Refresh root-owned cache"
    assert [command.id for command in data.commands] == ["refresh", "verify"]
    assert data.env == (("LC_ALL", "C"),)
    assert data.project == "sase"
    assert data.expires_at is not None


async def test_sudo_run_uses_terminal_handoff_not_durable_proc(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        create_gate(build_sudo_gate_request(_sudo_request()))
    notification = load_notifications()[0]
    result = SudoRequestModalResult(action="run", command_ids=("refresh",))
    app = _SudoActionApp(result)
    run_calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setenv(SASE_FEATURE_FLAGS_ENV, '{"agent_sudo_requests":false}')
    monkeypatch.setenv("SASE_SUDO_HANDOFF_TEST_ENV", "preserved")

    def fake_run(
        argv: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert app.suspend_recorder.active is True
        run_calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"status": "answered", "outcome": "completed"}),
        )

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_sudo.subprocess.run",
        fake_run,
    )

    assert handle_sudo_request(app, notification) is True
    [task] = app._sudo_request_open_tasks
    await task

    assert run_calls[0][0] == [
        "sase",
        "sudo",
        "answer",
        notification.action_data["request_id"],
        "--run",
        "--json",
        "--command",
        "refresh",
    ]
    kwargs = run_calls[0][1]
    assert kwargs["check"] is False
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is None
    assert kwargs["text"] is True
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert SASE_FEATURE_FLAGS_ENV not in env
    assert env["SASE_SUDO_HANDOFF_TEST_ENV"] == "preserved"
    assert app.durable_calls == []
    assert app.suspend_recorder.enters == 1
    assert app.suspend_recorder.exits == 1
    assert app.notifications == [("Sudo request completed", "information")]
    assert app.refresh_count == 1
    assert app.agent_refreshes == [(("notification",), {"latest_only": True})]


async def test_sudo_deny_uses_headless_durable_gate_executor(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        create_gate(build_sudo_gate_request(_sudo_request()))
    notification = load_notifications()[0]
    result = SudoRequestModalResult(action="deny", feedback="not needed")
    app = _SudoActionApp(result)
    submissions: list[object] = []

    def fake_submit(_app: object, _notification: object, submission: object) -> bool:
        submissions.append(submission)
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_sudo.submit_gate_execution_task",
        fake_submit,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_sudo.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("sudo deny must not spawn terminal"),
    )

    assert handle_sudo_request(app, notification) is True
    [task] = app._sudo_request_open_tasks
    await task

    [submission] = submissions
    assert submission.selected_option_ids == (DENY_OPTION_ID,)
    assert submission.feedback == "not needed"
    assert app.durable_calls == []
    assert app.suspend_recorder.enters == 0


def test_sudo_terminal_handoff_reports_auth_failure_and_keeps_gate_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _modal_data()
    result = SudoRequestModalResult(action="run", command_ids=("refresh",))
    app = _SudoActionApp(result)

    def fake_run(
        argv: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            2,
            stdout=json.dumps(
                {
                    "status": "pending",
                    "settled": False,
                    "outcome": "authentication_failed",
                }
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_sudo.subprocess.run",
        fake_run,
    )
    _run_sudo_terminal_handoff(app, _notification(), data, result)

    assert app.notifications == [
        ("Sudo authentication failed; gate remains pending", "warning")
    ]
    assert app.refresh_count == 1


def test_sudo_cli_message_reports_feature_disabled_detail() -> None:
    message = _sudo_cli_message(
        1,
        {
            "status": "pending",
            "outcome": "runner_error",
            "code": "feature_disabled",
            "message": "sudo requests are behind the agent_sudo_requests beta flag",
        },
    )

    assert message.text == (
        "Sudo handoff failed: "
        "sudo requests are behind the agent_sudo_requests beta flag"
    )
    assert message.severity == "error"


def test_sudo_terminal_handoff_handles_unsupported_suspend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _modal_data()
    result = SudoRequestModalResult(action="run", command_ids=("refresh",))
    app = _SudoActionApp(result)

    def fail_suspend() -> object:
        raise SuspendNotSupported()

    app.suspend = fail_suspend  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_sudo.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("unsupported suspend must not run sudo"),
    )
    _run_sudo_terminal_handoff(app, _notification(), data, result)

    assert app.notifications == [
        (
            "Could not open a trusted terminal for sudo authentication; gate remains pending",
            "error",
        )
    ]
    assert app.refresh_count == 1

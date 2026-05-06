from __future__ import annotations

import pytest

from sase.integrations.chat_install import (
    ChatInstallLaunchResult,
    ChatInstallStatusResult,
)
from tests._mobile_helper_bridge_helpers import run_bridge


def test_update_start_bridge_returns_running_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.start_chat_install_worker",
        lambda: ChatInstallLaunchResult(
            status="launched",
            message="Update worker started.",
            log_path=None,
            workspace=None,
            pid=1234,
            job_id="job_123",
            status_path=None,
        ),
    )

    code, data, stderr = run_bridge(
        {"schema_version": 1, "request_id": "req_1", "device_id": "device_1"},
        "update-start",
    )

    assert code == 0
    assert stderr == ""
    assert data["result"]["status"] == "success"  # type: ignore[index]
    assert data["job"]["job_id"] == "job_123"  # type: ignore[index]
    assert data["job"]["status"] == "running"  # type: ignore[index]


def test_update_start_bridge_rejects_mobile_command_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_called = False

    def start() -> ChatInstallLaunchResult:
        nonlocal start_called
        start_called = True
        return ChatInstallLaunchResult(
            status="launched",
            message="Update worker started.",
            job_id="job_123",
        )

    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.start_chat_install_worker", start
    )

    code, data, stderr = run_bridge(
        {"schema_version": 1, "command": "rm -rf /", "workspace": "/tmp/repo"},
        "update-start",
    )

    assert code == 2
    assert data == {}
    assert start_called is False
    assert "unexpected request field(s): command, workspace" in stderr


def test_update_start_bridge_maps_already_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.start_chat_install_worker",
        lambda: ChatInstallLaunchResult(
            status="already_running",
            message="A chat update worker is already running.",
        ),
    )

    code, data, stderr = run_bridge({"schema_version": 1}, "update-start")

    assert code == 4
    assert data == {}
    assert "already running" in stderr


def test_update_status_bridge_returns_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.read_chat_install_status",
        lambda job_id: ChatInstallStatusResult(
            status="succeeded",
            message="Update completed successfully.",
            job_id=job_id,
            started_at="2026-05-06T15:00:00+00:00",
            finished_at="2026-05-06T15:01:00+00:00",
        ),
    )

    code, data, stderr = run_bridge(
        {"schema_version": 1, "job_id": "job_123"}, "update-status"
    )

    assert code == 0
    assert stderr == ""
    assert data["result"]["status"] == "success"  # type: ignore[index]
    assert data["job"]["status"] == "succeeded"  # type: ignore[index]
    assert data["job"]["finished_at"] == "2026-05-06T15:01:00+00:00"  # type: ignore[index]


def test_update_status_bridge_maps_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.read_chat_install_status",
        lambda job_id: ChatInstallStatusResult(
            status="not_found",
            message="Update job was not found.",
            job_id=job_id,
        ),
    )

    code, data, stderr = run_bridge(
        {"schema_version": 1, "job_id": "missing"}, "update-status"
    )

    assert code == 4
    assert data == {}
    assert "not found" in stderr

"""Duplicate-start handling in :func:`sase.monitor.start.start_monitor`.

One lane may only carry one active monitor. These tests pin which repeat
requests are idempotent replays of the record already running and which are
rejected outright.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.monitor.models import MonitorAlreadyRunningError, MonitorRecord
from sase.monitor.start import StartMonitorRequest, start_monitor
from tests.monitor._fixtures import make_starter_agent, patch_project_records


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def test_start_monitor_returns_the_existing_record_for_a_duplicate_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import store as store_module
    import sase.monitor.start as start_module

    existing = MonitorRecord(
        monitor_id="aaa",
        member_agent_name="acme--mon",
        lane="acme",
        project_name="proj",
        artifacts_dir="/some/dir",
        timestamp="20260812120000",
        command="just check-full",
        cwd=str(tmp_path),
        reason="verify",
        label="just check-full",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=2700.0,
        tail_lines=200,
        monitor_state="running",
        request_fingerprint="sha256:match",
    )

    def fake_blocking(project_name: str, lane: str) -> MonitorRecord:
        del project_name, lane
        return existing

    monkeypatch.setattr(store_module, "monitor_blocking_start_for_lane", fake_blocking)
    monkeypatch.setattr(
        start_module,
        "monitor_request_fingerprint",
        lambda request, *, lane, label: "sha256:match",
    )

    request = StartMonitorRequest(
        command="just check-full",
        reason="verify",
        timeout_seconds=2700.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    result = start_monitor(request)

    assert result is existing


def test_start_monitor_rejects_same_command_with_changed_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import store as store_module
    import sase.monitor.start as start_module

    existing = MonitorRecord(
        monitor_id="aaa",
        member_agent_name="acme--mon",
        lane="acme",
        project_name="proj",
        artifacts_dir="/some/dir",
        timestamp="20260812120000",
        command="just check-full",
        cwd=str(tmp_path),
        reason="verify",
        label="just check-full",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=2700.0,
        tail_lines=200,
        monitor_state="running",
        request_fingerprint="sha256:old",
    )

    monkeypatch.setattr(
        store_module,
        "monitor_blocking_start_for_lane",
        lambda project_name, lane: existing,
    )
    monkeypatch.setattr(
        start_module,
        "monitor_request_fingerprint",
        lambda request, *, lane, label: "sha256:new",
    )

    request = StartMonitorRequest(
        command="just check-full",
        reason="verify with a different follow-up",
        timeout_seconds=2700.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
        next_action="Fix failures.",
    )

    with pytest.raises(MonitorAlreadyRunningError, match="same command"):
        start_monitor(request)


def test_start_monitor_rejects_identical_replay_of_lost_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import store as store_module
    import sase.monitor.start as start_module

    existing = MonitorRecord(
        monitor_id="aaabbbcccddd",
        member_agent_name="acme--mon",
        lane="acme",
        project_name="proj",
        artifacts_dir="/some/dir",
        timestamp="20260812120000",
        command="just check-full",
        cwd=str(tmp_path),
        reason="verify",
        label="just check-full",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=2700.0,
        tail_lines=200,
        monitor_state="lost",
        request_fingerprint="sha256:match",
        settled=True,
    )

    monkeypatch.setattr(
        store_module,
        "monitor_blocking_start_for_lane",
        lambda project_name, lane: existing,
    )
    monkeypatch.setattr(
        start_module,
        "monitor_request_fingerprint",
        lambda request, *, lane, label: "sha256:match",
    )

    request = StartMonitorRequest(
        command="just check-full",
        reason="verify",
        timeout_seconds=2700.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    with pytest.raises(MonitorAlreadyRunningError, match="lost monitor"):
        start_monitor(request)


def test_start_monitor_rejects_a_second_concurrent_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import store as store_module
    import sase.monitor.start as start_module

    existing = MonitorRecord(
        monitor_id="aaa",
        member_agent_name="acme--mon",
        lane="acme",
        project_name="proj",
        artifacts_dir="/some/dir",
        timestamp="20260812120000",
        command="sleep 300",
        cwd=str(tmp_path),
        reason="verify",
        label="sleep",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=300.0,
        tail_lines=200,
        monitor_state="running",
        request_fingerprint="sha256:existing",
    )

    monkeypatch.setattr(
        store_module,
        "monitor_blocking_start_for_lane",
        lambda project_name, lane: existing,
    )
    monkeypatch.setattr(
        start_module,
        "monitor_request_fingerprint",
        lambda request, *, lane, label: "sha256:requested",
    )

    request = StartMonitorRequest(
        command="just check-full",
        reason="verify",
        timeout_seconds=2700.0,
        idle_timeout_seconds=600.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    with pytest.raises(MonitorAlreadyRunningError):
        start_monitor(request)


def test_implicit_start_conflicts_on_durable_family_not_member_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller_ws = tmp_path / "ws12"
    caller_ws.mkdir()
    caller_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "02i--code",
        agent_family="02i",
        model="caller-model",
        workspace_dir=str(caller_ws),
        workspace_num=12,
        pid=os.getpid(),
        cl_name="02i",
    )
    running_dir = make_starter_agent(
        "proj",
        "20260812130000",
        "02i--mon",
        agent_family="02i",
        agent_family_role="monitor",
        monitor_id="runningmon001",
        monitor_state="running",
        monitor_command="sleep 300",
        monitor_cwd=str(tmp_path),
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
    )
    patch_project_records(monkeypatch, [caller_dir, running_dir])
    monkeypatch.setenv("SASE_AGENT_NAME", "02i--code")

    request = StartMonitorRequest(
        command="just check-full",
        reason="verify",
        timeout_seconds=2700.0,
        cwd=str(caller_ws),
        project_name="proj",
    )

    with pytest.raises(MonitorAlreadyRunningError, match="lane '02i'"):
        start_monitor(request)

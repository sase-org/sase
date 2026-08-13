"""Tests for :mod:`sase.monitor.start`."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.monitor.models import MonitorAlreadyRunningError, MonitorError, MonitorRecord
from sase.monitor.start import (
    StartMonitorRequest,
    maybe_handoff_monitor_from_agent,
    start_monitor,
    write_monitor_pending_marker,
)
from sase.core.paths import sase_projects_dir
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import make_starter_agent, patch_project_records, write_project_file

_POLL_TIMEOUT = 60.0
_POLL_INTERVAL = 0.1


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _wait_for_done(artifacts_dir: str) -> dict[str, object]:
    done_path = Path(artifacts_dir) / "done.json"
    deadline = time.monotonic() + _POLL_TIMEOUT
    while time.monotonic() < deadline:
        if done_path.exists():
            try:
                return json.loads(done_path.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(_POLL_INTERVAL)
    raise AssertionError(f"monitor at {artifacts_dir} never finished")


def test_start_monitor_promotes_a_bare_lane_and_runs_to_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_file = write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    record = start_monitor(request)

    assert record.monitor_state == "running"
    assert record.member_agent_name == "acme--mon"
    assert record.lane == "acme"

    # The starter is now a promoted family root.
    starter_meta = json.loads((Path(starter_dir) / "agent_meta.json").read_text())
    assert starter_meta["agent_family"] == "acme"
    assert starter_meta["name"] == "acme--0"

    done = _wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"
    assert done["monitor_exit_code"] == 0

    # No next action: the transferred claim is released once the command
    # finishes.
    assert get_claimed_workspaces(project_file) == []


def test_start_monitor_returns_the_existing_record_for_a_duplicate_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import store as store_module

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
    )

    def fake_active(project_name: str, lane: str) -> object:
        del project_name, lane
        return object()  # sentinel; MonitorRecord.from_record is patched below too

    monkeypatch.setattr(store_module, "active_monitor_for_lane", fake_active)
    monkeypatch.setattr(
        MonitorRecord, "from_record", staticmethod(lambda record: existing)
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


def test_start_monitor_rejects_a_second_concurrent_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import store as store_module

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
    )

    monkeypatch.setattr(
        store_module, "active_monitor_for_lane", lambda project_name, lane: object()
    )
    monkeypatch.setattr(
        MonitorRecord, "from_record", staticmethod(lambda record: existing)
    )

    request = StartMonitorRequest(
        command="just check-full",
        reason="verify",
        timeout_seconds=2700.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    with pytest.raises(MonitorAlreadyRunningError):
        start_monitor(request)


def test_start_monitor_tears_down_the_member_when_the_supervisor_cannot_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    import sase.monitor.start as start_module

    def fake_popen(*args: object, **kwargs: object) -> None:
        raise OSError("no more processes")

    monkeypatch.setattr(start_module.subprocess, "Popen", fake_popen)

    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    with pytest.raises(MonitorError):
        start_monitor(request)

    # The half-created member is marked failed, not left phantom-running.
    artifacts_root = sase_projects_dir() / "proj" / "artifacts" / "ace-run"
    member_dirs = [
        p.parent
        for p in artifacts_root.glob("*/*/*/agent_meta.json")
        if p.parent != Path(starter_dir)
    ]
    assert len(member_dirs) == 1
    meta = json.loads((member_dirs[0] / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    done = json.loads((member_dirs[0] / "done.json").read_text())
    assert done["monitor_state"] == "failed"


def test_write_monitor_pending_marker_pulses_artifacts_root(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "ace-run" / "202608" / "12"
    artifacts_dir.mkdir(parents=True)
    record = MonitorRecord(
        monitor_id="m123",
        member_agent_name="agent--mon",
        lane="agent",
        project_name="proj",
        artifacts_dir="/tmp/member",
        timestamp="20260812120000",
        command="just check-full",
        cwd=str(tmp_path),
        reason="verify",
        label="just",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=30.0,
        tail_lines=200,
        monitor_state="running",
    )

    marker_path = write_monitor_pending_marker(
        record,
        str(artifacts_dir),
        timestamp=123.0,
    )

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker == {
        "monitor_id": "m123",
        "member_artifacts_dir": "/tmp/member",
        "member_agent_name": "agent--mon",
        "timestamp": 123.0,
    }
    assert (tmp_path / "artifacts" / "ace-run" / ".ace_refresh_pulse").exists()


def test_maybe_handoff_monitor_from_agent_writes_marker_and_kills_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "ace-run" / "202608" / "12"
    artifacts_dir.mkdir(parents=True)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    record = MonitorRecord(
        monitor_id="m123",
        member_agent_name="agent--mon",
        lane="agent",
        project_name="proj",
        artifacts_dir="/tmp/member",
        timestamp="20260812120000",
        command="just check-full",
        cwd=str(tmp_path),
        reason="verify",
        label="just",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=30.0,
        tail_lines=200,
        monitor_state="running",
    )

    with patch("sase.main.utils.kill_agent_runner_group") as kill:
        assert maybe_handoff_monitor_from_agent(record) is True

    assert (artifacts_dir / ".sase_monitor_pending").exists()
    kill.assert_called_once_with(str(artifacts_dir))


def test_maybe_handoff_monitor_from_agent_is_noop_outside_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    record = MonitorRecord(
        monitor_id="m123",
        member_agent_name="agent--mon",
        lane="agent",
        project_name="proj",
        artifacts_dir="/tmp/member",
        timestamp="20260812120000",
        command="just check-full",
        cwd=str(tmp_path),
        reason="verify",
        label="just",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=30.0,
        tail_lines=200,
        monitor_state="running",
    )

    with patch("sase.main.utils.kill_agent_runner_group") as kill:
        assert (
            maybe_handoff_monitor_from_agent(record, artifacts_dir=str(tmp_path))
            is False
        )

    assert not (tmp_path / ".sase_monitor_pending").exists()
    kill.assert_not_called()

"""Monitor handoff markers written by :mod:`sase.monitor.start`.

A monitor started from inside an agent hands its lane over by dropping a
pending marker in the starter's artifacts dir and killing the agent runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.monitor.models import MonitorRecord
from sase.monitor.start import (
    maybe_handoff_monitor_from_agent,
    write_monitor_pending_marker,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


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

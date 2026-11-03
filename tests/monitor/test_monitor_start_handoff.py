"""Archived pending-monitor marker writer used by historical kill-path readers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.monitor.models import MonitorRecord
from sase.monitor.start import write_monitor_pending_marker


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def test_write_monitor_pending_marker_pulses_artifacts_root(tmp_path: Path) -> None:
    artifacts_root = tmp_path / ".sase" / "projects" / "demo" / "artifacts"
    artifacts_dir = artifacts_root / "ace-run" / "202608" / "12" / "20260812120000"
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
    assert marker["monitor_id"] == "m123"
    assert marker["member_artifacts_dir"] == "/tmp/member"
    assert marker["member_agent_name"] == "agent--mon"
    assert marker["timestamp"] == 123.0
    checkpoint_ref = marker["handoff_checkpoint_ref"]
    assert isinstance(checkpoint_ref, str)
    checkpoint_path = (
        artifacts_dir
        / "continuation"
        / checkpoint_ref.removeprefix("local:continuation/")
    )
    assert checkpoint_path.exists()
    assert (artifacts_root / ".ace_refresh_pulse").exists()
    assert not (artifacts_root / "ace-run" / "202608" / ".ace_refresh_pulse").exists()

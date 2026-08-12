"""Tests for :mod:`sase.monitor.store`."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.monitor.models import MonitorLaneError, MonitorRecord
from sase.monitor.store import (
    active_monitor_for_lane,
    get_monitor,
    has_any_monitor,
    resolve_lane,
    stop_monitor,
)

from ._fixtures import (
    DEAD_PID,
    make_starter_agent,
    patch_project_records,
    record_from_disk,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_resolve_lane_picks_the_newest_family_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = make_starter_agent("proj", "20260812120000", "acme--0", agent_family="acme")
    newer = make_starter_agent(
        "proj", "20260812130000", "acme--mon", agent_family="acme"
    )
    patch_project_records(monkeypatch, [older, newer])

    ctx = resolve_lane("proj", "acme")

    assert ctx.record.artifact_dir == newer


def test_resolve_lane_raises_when_lane_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_project_records(monkeypatch, [])

    with pytest.raises(MonitorLaneError):
        resolve_lane("proj", "ghost")


def test_active_monitor_for_lane_ignores_other_lanes_and_terminal_monitors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running_other_lane = make_starter_agent(
        "proj",
        "20260812120000",
        "other--mon",
        agent_family="other",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
    )
    terminal_same_lane = make_starter_agent(
        "proj",
        "20260812121000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="bbb",
        monitor_state="completed",
    )
    running_same_lane = make_starter_agent(
        "proj",
        "20260812122000",
        "acme--mon-0",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="ccc",
        monitor_state="running",
        monitor_command="sleep 60",
    )
    patch_project_records(
        monkeypatch, [running_other_lane, terminal_same_lane, running_same_lane]
    )

    found = active_monitor_for_lane("proj", "acme")

    assert found is not None
    assert found.artifact_dir == running_same_lane


def test_has_any_monitor_is_true_once_any_monitor_member_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_project_records(monkeypatch, [])
    assert has_any_monitor("proj", "acme") is False

    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="completed",
    )
    patch_project_records(monkeypatch, [monitor_dir])
    assert has_any_monitor("proj", "acme") is True


def test_stop_monitor_is_idempotent_once_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    monkeypatch.setattr("os.kill", lambda pid, sig: calls.append(pid))
    record = MonitorRecord(
        monitor_id="aaa",
        member_agent_name="acme--mon",
        lane="acme",
        project_name="proj",
        artifacts_dir="/irrelevant",
        timestamp="20260812120000",
        command="sleep 60",
        cwd="/work",
        reason="test",
        label="sleep",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=60.0,
        tail_lines=200,
        monitor_state="completed",
    )

    result = stop_monitor(record)

    assert result is record
    assert calls == []


def test_stop_monitor_signals_the_supervisor_and_waits_for_it_to_settle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
        monitor_command="sleep 60",
        monitor_stop_status="MONITORED",
    )
    # A real, long-lived process stands in for the supervisor pid so the
    # liveness pre-checks pass; the fake ``os.kill`` below simulates the real
    # supervisor's own synchronous SIGTERM-handler reaction (write the
    # terminal marker) instead of actually killing it, so there is no race
    # between this test's two independent observers of process liveness.
    child = subprocess.Popen(["sleep", "30"])
    real_kill = os.kill
    signaled: list[int] = []

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0:
            real_kill(pid, sig)
            return
        assert pid == child.pid
        assert sig == signal.SIGTERM
        signaled.append(pid)
        _with_meta_state(monitor_dir, "stopped")

    try:
        patch_project_records(monkeypatch, [monitor_dir])
        monkeypatch.setattr("os.kill", fake_kill)

        record = MonitorRecord.from_record(record_from_disk(monitor_dir))
        record = MonitorRecord(**{**record.__dict__, "pid": child.pid})

        result = stop_monitor(record)

        assert signaled == [child.pid]
        assert result is not None
        assert result.monitor_state == "stopped"
    finally:
        if child.poll() is None:
            real_kill(child.pid, signal.SIGKILL)
        child.wait()


def test_stop_monitor_reconciles_a_dead_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
        monitor_command="sleep 60",
        monitor_stop_status="MONITORED",
    )
    patch_project_records(monkeypatch, [monitor_dir])
    record = MonitorRecord.from_record(record_from_disk(monitor_dir))
    record = MonitorRecord(**{**record.__dict__, "pid": DEAD_PID})

    result = stop_monitor(record)

    assert result is not None
    assert result.monitor_state == "failed"
    on_disk_meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk_meta["monitor_state"] == "failed"
    on_disk_done = json.loads((Path(monitor_dir) / "done.json").read_text())
    assert on_disk_done["monitor_state"] == "failed"
    assert on_disk_done["error"] == "monitor supervisor died without reporting"


def test_get_monitor_returns_none_for_an_unknown_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_project_records(monkeypatch, [])
    assert get_monitor("proj", "/nowhere") is None


def _with_meta_state(artifacts_dir: str, monitor_state: str) -> AgentArtifactRecordWire:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["monitor_state"] = monitor_state
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return record_from_disk(artifacts_dir)

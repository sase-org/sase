"""An implicit in-agent ``sase monitor start`` must not load project history.

On a host with ~12k artifact records the start used to spend 20-40 s in
full-history reads: one project scan to find the caller it was already
running in, then a project-wide monitor read three separate times. Codex's
yielding ``exec_command`` returns control after ~30 s, so those starts were
cut off mid-handoff. These tests pin the shape that keeps the start fast:
read the pinned artifact dir directly, and read the lane's monitors once.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.monitor import store, store_lane
from sase.monitor.models import MonitorLaneError
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.monitor.start_timing import MONITOR_START_TIMING_FILENAME, StartTimer
from sase.running_field import WorkspaceClaim

from ._fixtures import (
    make_starter_agent,
    record_from_disk,
    wait_for_done,
    write_project_file,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)


class _RecordScans:
    """Stand-in for ``store.project_records`` that counts every call."""

    def __init__(self, artifacts_dirs: list[str]) -> None:
        self._artifacts_dirs = artifacts_dirs
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        project_name: str | None,
        *,
        only_monitors: bool = False,
        agent_session: str | None = None,
    ) -> list[AgentArtifactRecordWire]:
        self.calls.append(
            {"only_monitors": only_monitors, "agent_session": agent_session}
        )
        return [
            record
            for record in (record_from_disk(d) for d in self._artifacts_dirs)
            if project_name is None or record.project_name == project_name
        ]

    @property
    def full_scans(self) -> list[dict[str, object]]:
        """Calls that asked for the whole project rather than one lane."""
        return [call for call in self.calls if call["agent_session"] is None]

    @property
    def lane_reads(self) -> list[dict[str, object]]:
        return [call for call in self.calls if call["agent_session"] is not None]


def _caller(tmp_path: Path) -> tuple[Path, str]:
    caller_ws = tmp_path / "ws12"
    caller_ws.mkdir()
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(12, "ace-run", "02i", pid=os.getpid())],
    )
    caller_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "02i--code",
        agent_session="02i",
        model="caller-model",
        workspace_dir=str(caller_ws),
        workspace_num=12,
        pid=os.getpid(),
        cl_name="02i",
    )
    return caller_ws, caller_dir


def _implicit_request(cwd: Path) -> StartMonitorRequest:
    return StartMonitorRequest(
        command="true",
        reason="verify fast start",
        timeout_seconds=30.0,
        cwd=str(cwd),
        project_name="proj",
        start_status="MONITORING",
        stop_status="MONITORED",
    )


def test_implicit_pinned_start_does_not_scan_project_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller_ws, caller_dir = _caller(tmp_path)
    scans = _RecordScans([caller_dir])
    monkeypatch.setattr(store, "project_records", scans)
    monkeypatch.setenv("SASE_AGENT_NAME", "02i--code")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", caller_dir)

    record = start_monitor(_implicit_request(caller_ws))

    assert record.lane == "02i"
    assert scans.full_scans == []
    wait_for_done(record.artifacts_dir)


def test_lane_monitor_read_happens_once_per_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller_ws, caller_dir = _caller(tmp_path)
    scans = _RecordScans([caller_dir])
    monkeypatch.setattr(store, "project_records", scans)
    monkeypatch.setenv("SASE_AGENT_NAME", "02i--code")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", caller_dir)

    record = start_monitor(_implicit_request(caller_ws))

    # The replay check and the ``--mon`` suffix allocation both ask about the
    # lane's monitors; they share one snapshot.
    assert scans.lane_reads == [{"only_monitors": True, "agent_session": "02i"}]
    wait_for_done(record.artifacts_dir)


def test_start_writes_phase_timing_into_the_member_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller_ws, caller_dir = _caller(tmp_path)
    monkeypatch.setattr(store, "project_records", _RecordScans([caller_dir]))
    monkeypatch.setenv("SASE_AGENT_NAME", "02i--code")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", caller_dir)

    record = start_monitor(_implicit_request(caller_ws))

    timing = json.loads(
        (Path(record.artifacts_dir) / MONITOR_START_TIMING_FILENAME).read_text()
    )
    assert timing["total_seconds"] >= 0
    assert set(timing["phases"]) == {
        "resolve_identity",
        "lane_lock",
        "continuation_setup",
        "replay_lookup",
        "resolve_lane_start",
        "claim_preflight",
        "suffix_lookup",
        "bind_completion",
        "create_member",
        "tool_reservation",
        "spawn_and_ack",
        "persist_intent",
    }
    wait_for_done(record.artifacts_dir)


def test_start_timer_charges_elapsed_time_to_each_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter([100.0, 101.5, 104.0, 104.25])
    monkeypatch.setattr("sase.monitor.start_timing.time.monotonic", lambda: next(ticks))

    timer = StartTimer()
    timer.mark("read")
    timer.mark("spawn")
    timer.mark("read")

    assert timer.snapshot() == {
        "total_seconds": 4.25,
        "phases": {"read": 1.75, "spawn": 2.5},
    }
    timer.write(tmp_path)
    assert json.loads((tmp_path / MONITOR_START_TIMING_FILENAME).read_text()) == (
        timer.snapshot()
    )


def test_resolve_caller_agent_reads_only_the_pinned_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, caller_dir = _caller(tmp_path)
    scans = _RecordScans([caller_dir])
    monkeypatch.setattr(store, "project_records", scans)

    ctx = store_lane.resolve_caller_agent("proj", "02i--code", artifacts_dir=caller_dir)

    assert ctx.record.artifact_dir == caller_dir
    assert scans.calls == []


def test_resolve_caller_agent_falls_back_when_the_pin_is_foreign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, caller_dir = _caller(tmp_path)
    other_dir = make_starter_agent("proj", "20260812130000", "other", model="m")
    scans = _RecordScans([caller_dir, other_dir])
    monkeypatch.setattr(store, "project_records", scans)

    ctx = store_lane.resolve_caller_agent("proj", "02i--code", artifacts_dir=other_dir)

    assert ctx.record.artifact_dir == caller_dir
    assert len(scans.full_scans) == 1


def test_resolve_caller_agent_falls_back_when_the_pin_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, caller_dir = _caller(tmp_path)
    scans = _RecordScans([caller_dir])
    monkeypatch.setattr(store, "project_records", scans)

    ctx = store_lane.resolve_caller_agent(
        "proj", "02i--code", artifacts_dir=str(tmp_path / "gone")
    )

    assert ctx.record.artifact_dir == caller_dir
    assert len(scans.full_scans) == 1


def test_resolve_caller_agent_still_errors_when_nothing_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "project_records", _RecordScans([]))

    with pytest.raises(MonitorLaneError, match="no artifacts found"):
        store_lane.resolve_caller_agent("proj", "ghost", artifacts_dir=None)


def test_lane_monitor_records_keep_only_the_exact_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def monitor(timestamp: str, lane: str) -> str:
        return make_starter_agent(
            "proj",
            timestamp,
            f"{lane}--mon",
            agent_session=lane,
            agent_session_role="monitor",
            monitor_id=f"id{timestamp}",
            monitor_state="running",
        )

    dirs = [
        monitor("20260812120000", "lane"),
        # The index matches sessions case-insensitively, so a differently
        # cased lane can come back from the query and must be dropped.
        monitor("20260812120100", "LANE"),
        make_starter_agent(
            "proj", "20260812120200", "lane--code", agent_session="lane"
        ),
    ]
    monkeypatch.setattr(store, "project_records", _RecordScans(dirs))

    records = store.lane_monitor_records("proj", "lane")

    assert [record.timestamp for record in records] == ["20260812120000"]

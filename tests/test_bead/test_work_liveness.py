"""Tests for the shared bead work-in-flight liveness helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.bead.work_liveness import (
    AGENT_BEAD_SCAN_OPTIONS,
    BeadWorkInFlight,
    agent_record_is_alive,
    beads_with_live_agents,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
)


def _record(
    *,
    project_name: str = "sase",
    bead_id: str | None = "sase-task.1",
    agent_name: str | None = "sase-task.1",
    workflow_dir_name: str = "ace-run",
    timestamp: str = "20260818120000",
    pid: int | None = 12345,
    stopped_at: str | None = None,
    has_meta: bool = True,
) -> AgentArtifactRecordWire:
    meta = None
    if has_meta:
        meta = AgentMetaWire(
            name=agent_name,
            bead_id=bead_id,
            pid=pid,
            stopped_at=stopped_at,
        )
    return AgentArtifactRecordWire(
        project_name=project_name,
        project_dir=f"/tmp/{project_name}",
        project_file=f"/tmp/{project_name}/{project_name}.sase",
        workflow_dir_name=workflow_dir_name,
        artifact_dir=f"/tmp/{project_name}/artifacts/{workflow_dir_name}/{timestamp}",
        timestamp=timestamp,
        agent_meta=meta,
    )


def _snapshot(
    records: list[AgentArtifactRecordWire], projects_root: Path
) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(projects_root),
        options=AGENT_BEAD_SCAN_OPTIONS,
        stats=AgentArtifactScanStatsWire(),
        records=records,
    )


def test_beads_with_live_agents_skips_incomplete_and_non_ace_run_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    records = [
        _record(),
        _record(
            agent_name="no-bead",
            bead_id=None,
            timestamp="20260818120001",
        ),
        _record(has_meta=False, timestamp="20260818120002"),
        _record(
            workflow_dir_name="mentor-bryan",
            bead_id="sase-other.1",
            agent_name="sase-other.1",
            timestamp="20260818120003",
        ),
    ]
    monkeypatch.setattr(
        "sase.bead.work_liveness.scan_agent_artifacts",
        lambda *_args, **_kwargs: _snapshot(records, tmp_path),
    )
    monkeypatch.setattr("sase.bead.work_liveness.is_process_alive", lambda *_: True)

    assert beads_with_live_agents(tmp_path) == {("sase", "sase-task.1"): "sase-task.1"}


def test_dead_pid_is_not_alive() -> None:
    assert not agent_record_is_alive(_record(pid=1))
    assert not agent_record_is_alive(_record(pid=None))


def test_stopped_at_is_not_alive() -> None:
    assert not agent_record_is_alive(
        _record(pid=os.getpid(), stopped_at="2026-08-18T12:00:00Z")
    )


def test_newest_timestamp_per_agent_decides_liveness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    records = [
        _record(timestamp="20260818110000", pid=111),
        _record(
            timestamp="20260818120000",
            pid=222,
            stopped_at="2026-08-18T12:00:00Z",
        ),
    ]
    monkeypatch.setattr(
        "sase.bead.work_liveness.scan_agent_artifacts",
        lambda *_args, **_kwargs: _snapshot(records, tmp_path),
    )

    assert beads_with_live_agents(tmp_path) == {}


def test_covers_is_true_for_either_half() -> None:
    work = BeadWorkInFlight(
        launching=frozenset({"sase-a.1"}),
        working=frozenset({("sase", "sase-b.1")}),
    )
    assert work.covers("sase", "sase-a.1")
    assert work.covers("other", "sase-a.1")
    assert work.covers("sase", "sase-b.1")
    assert not work.covers("other", "sase-b.1")
    assert not work.covers("sase", "sase-c.1")
    assert work.is_launching("sase-a.1")
    assert work.is_worked("sase", "sase-b.1")
    assert not work.is_worked("other", "sase-b.1")

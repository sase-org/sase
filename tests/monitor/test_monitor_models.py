"""Tests for :mod:`sase.monitor.models`."""

from __future__ import annotations

import pytest

from sase.core.agent_scan_wire import AgentMetaWire, DoneMarkerWire
from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.monitor.models import MonitorRecord, monitor_state_bucket
from sase.monitor_state import is_monitor_member_role


def _record(
    *,
    agent_meta: AgentMetaWire | None,
    done: DoneMarkerWire | None = None,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/home/proj",
        project_file="/home/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir="/home/proj/artifacts/ace-run/20260812120000",
        timestamp="20260812120000",
        agent_meta=agent_meta,
        done=done,
    )


@pytest.mark.parametrize(
    ("state", "bucket"),
    [
        ("running", "Running"),
        ("completed", "Done"),
        ("failed", "Failed"),
        ("timeout", "Failed"),
        ("stopped", "Done"),
        ("lost", "Failed"),
        (None, "Running"),
        ("bogus", "Running"),
    ],
)
def test_monitor_state_bucket_maps_every_terminal_state(
    state: str | None, bucket: str
) -> None:
    assert monitor_state_bucket(state) == bucket


@pytest.mark.parametrize(
    ("agent_family_role", "role_suffix", "expected"),
    [
        ("monitor", None, True),
        ("root", "--0", False),
        ("root", "--mon", False),
        (None, "--mon", True),
        (None, "--mon-0", True),
    ],
)
def test_is_monitor_member_role_uses_role_then_suffix_fallback(
    agent_family_role: str | None,
    role_suffix: str | None,
    expected: bool,
) -> None:
    assert is_monitor_member_role(agent_family_role, role_suffix) is expected


def test_from_record_rejects_non_monitor_rows() -> None:
    with pytest.raises(ValueError):
        MonitorRecord.from_record(_record(agent_meta=None))

    with pytest.raises(ValueError):
        MonitorRecord.from_record(_record(agent_meta=AgentMetaWire(name="agent--0")))


def test_from_record_prefers_running_meta_fields() -> None:
    meta = AgentMetaWire(
        name="acme--mon",
        agent_family="acme",
        monitor_id="abc123",
        monitor_command="sleep 60",
        monitor_cwd="/work",
        monitor_reason="verify",
        monitor_label="sleep",
        monitor_start_status="MONITORING",
        monitor_stop_status="MONITORED",
        monitor_timeout_seconds=60.0,
        monitor_idle_timeout_seconds=10.0,
        monitor_tail_lines=200,
        monitor_state="running",
        pid=4242,
    )
    record = MonitorRecord.from_record(_record(agent_meta=meta))

    assert record.monitor_id == "abc123"
    assert record.member_agent_name == "acme--mon"
    assert record.lane == "acme"
    assert record.monitor_state == "running"
    assert record.status_bucket == "Running"
    assert not record.is_terminal
    assert record.pid == 4242
    assert record.exit_code is None
    assert record.idle_timeout_seconds == 10.0


def test_from_record_prefers_done_marker_over_running_meta() -> None:
    meta = AgentMetaWire(
        name="acme--mon",
        agent_family="acme",
        monitor_id="abc123",
        monitor_command="sh -c 'exit 3'",
        monitor_state="running",
    )
    done = DoneMarkerWire(monitor_state="failed", monitor_exit_code=3)
    record = MonitorRecord.from_record(_record(agent_meta=meta, done=done))

    assert record.monitor_state == "failed"
    assert record.exit_code == 3
    assert record.status_bucket == "Failed"
    assert record.is_terminal


def test_from_record_treats_unsettled_terminal_meta_as_active() -> None:
    meta = AgentMetaWire(
        name="acme--mon",
        agent_family="acme",
        monitor_id="abc123",
        monitor_command="true",
        monitor_state="completed",
        monitor_settled=False,
    )
    record = MonitorRecord.from_record(_record(agent_meta=meta))

    assert record.monitor_state == "completed"
    assert record.settled is False
    assert record.status_bucket == "Running"
    assert not record.is_terminal


def test_from_record_uses_settled_meta_without_done_marker() -> None:
    meta = AgentMetaWire(
        name="acme--mon",
        agent_family="acme",
        monitor_id="abc123",
        monitor_command="true",
        monitor_state="completed",
        monitor_settled=True,
        monitor_request_fingerprint="sha256:test",
    )
    record = MonitorRecord.from_record(_record(agent_meta=meta))

    assert record.settled is True
    assert record.request_fingerprint == "sha256:test"
    assert record.status_bucket == "Done"
    assert record.is_terminal


def test_from_record_preserves_a_zero_exit_code() -> None:
    meta = AgentMetaWire(
        name="acme--mon",
        agent_family="acme",
        monitor_id="abc123",
        monitor_command="true",
        monitor_state="running",
        monitor_exit_code=0,
    )
    record = MonitorRecord.from_record(_record(agent_meta=meta))

    assert record.exit_code == 0

"""Duplicate-start handling in :func:`sase.monitor.start.start_monitor`.

One lane may only carry one active monitor. These tests pin which repeat
requests are idempotent replays of the record already running and which are
rejected outright, including when the requests race each other.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.core.paths import sase_projects_dir
from sase.monitor.models import MonitorAlreadyRunningError, MonitorRecord
from sase.monitor.start import StartMonitorRequest, start_monitor
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    record_from_disk,
    wait_for_done,
    write_project_file,
)


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
        start_status="MONITORING",
        stop_status="MONITORED",
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
        start_status="MONITORING",
        stop_status="MONITORED",
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
        start_status="MONITORING",
        stop_status="MONITORED",
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
        start_status="MONITORING",
        stop_status="MONITORED",
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
        start_status="MONITORING",
        stop_status="MONITORED",
    )

    with pytest.raises(MonitorAlreadyRunningError, match="lane '02i'"):
        start_monitor(request)


def test_start_monitor_serializes_concurrent_starts_in_one_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import store as store_module

    write_project_file("proj")
    make_starter_agent(
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

    def dynamic_project_records(
        project_name: str | None, *, only_monitors: bool = False
    ) -> list[AgentArtifactRecordWire]:
        records: list[AgentArtifactRecordWire] = []
        projects_root = sase_projects_dir()
        project_names = [project_name] if project_name else ["proj"]
        for name in project_names:
            artifacts_root = projects_root / name / "artifacts" / "ace-run"
            for meta_path in artifacts_root.glob("*/*/*/agent_meta.json"):
                record = record_from_disk(meta_path.parent)
                if only_monitors and (
                    record.agent_meta is None
                    or record.agent_meta.agent_family_role != "monitor"
                ):
                    continue
                records.append(record)
        return records

    monkeypatch.setattr(store_module, "_project_records", dynamic_project_records)

    barrier = threading.Barrier(3)
    records: list[MonitorRecord] = []
    expected_errors: list[str] = []
    unexpected_errors: list[BaseException] = []

    def worker(command: str) -> None:
        request = StartMonitorRequest(
            command=command,
            reason="verify",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
            inherit_lane_workspace_claim=False,
        )
        barrier.wait()
        try:
            records.append(start_monitor(request))
        except MonitorAlreadyRunningError as exc:
            expected_errors.append(str(exc))
        except BaseException as exc:
            unexpected_errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("sleep 2",)),
        threading.Thread(target=worker, args=("sleep 3",)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10.0)

    if unexpected_errors:
        raise unexpected_errors[0]
    assert [thread.is_alive() for thread in threads] == [False, False]
    assert len(records) == 1
    assert len(expected_errors) == 1
    assert "already has an active monitor" in expected_errors[0]

    monitor_meta_paths = [
        p
        for p in (sase_projects_dir() / "proj" / "artifacts" / "ace-run").glob(
            "*/*/*/agent_meta.json"
        )
        if json.loads(p.read_text()).get("agent_family_role") == "monitor"
    ]
    assert len(monitor_meta_paths) == 1
    wait_for_done(records[0].artifacts_dir)

"""Tests for :mod:`sase.monitor.start`."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.monitor.models import MonitorAlreadyRunningError, MonitorError, MonitorRecord
from sase.monitor.start import (
    SUPERVISOR_LOG_NAME,
    StartMonitorRequest,
    maybe_handoff_monitor_from_agent,
    start_monitor,
    write_monitor_pending_marker,
)
from sase.core.paths import sase_projects_dir
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import (
    make_starter_agent,
    patch_project_records,
    record_from_disk,
    write_project_file,
)

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
        idle_timeout_seconds=10.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    record = start_monitor(request)

    assert record.monitor_state == "running"
    assert record.member_agent_name == "acme--mon"
    assert record.lane == "acme"
    assert record.idle_timeout_seconds == 10.0

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
    _wait_for_done(records[0].artifacts_dir)


def test_start_monitor_scrubs_agent_identity_from_the_supervisor_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "starter--0")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", "/dead/starter")
    write_project_file(
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

    import sase.monitor.start as start_module

    real_popen = start_module.subprocess.Popen
    captured_env: dict[str, str] = {}

    def fake_popen(*args: object, **kwargs: object) -> object:
        env = kwargs.get("env")
        if isinstance(env, dict):
            captured_env.update(env)
        return real_popen(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(start_module.subprocess, "Popen", fake_popen)

    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    record = start_monitor(request)
    _wait_for_done(record.artifacts_dir)

    assert "SASE_AGENT" not in captured_env
    assert "SASE_AGENT_NAME" not in captured_env
    assert "SASE_ARTIFACTS_DIR" not in captured_env


def test_start_monitor_captures_supervisor_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project_file("proj")
    starter_dir = make_starter_agent(
        "proj",
        "20260812121000",
        "acme--0",
        agent_family="acme",
        model="test",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    import sase.monitor.start as start_module

    captured: dict[str, object] = {}

    def fake_popen(*args: object, **kwargs: object) -> object:
        del args
        output = kwargs["stdout"]
        assert hasattr(output, "write")
        output.write(b"supervisor traceback\n")
        output.flush()
        captured.update(kwargs)
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr(start_module.subprocess, "Popen", fake_popen)

    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify diagnostics",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            lane="acme",
            inherit_lane_workspace_claim=False,
        )
    )

    log_path = Path(record.artifacts_dir) / SUPERVISOR_LOG_NAME
    assert log_path.read_bytes() == b"supervisor traceback\n"
    assert captured["stderr"] == start_module.subprocess.STDOUT
    assert captured["stdin"] == start_module.subprocess.DEVNULL
    assert captured["start_new_session"] is True
    assert captured["close_fds"] is True


def test_start_monitor_persists_a_supervisor_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project_file(
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
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    _wait_for_done(record.artifacts_dir)

    # Empty is an accepted fallback on platforms without /proc identity
    # support; the field must at least have been written.
    assert "monitor_supervisor_identity" in meta


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
        "_monitor_request_fingerprint",
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
        "_monitor_request_fingerprint",
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
        "_monitor_request_fingerprint",
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
        "_monitor_request_fingerprint",
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


def test_start_monitor_claim_failure_does_not_run_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "command-ran"
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=123456)],
    )
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

    request = StartMonitorRequest(
        command=f"touch {sentinel}",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    with pytest.raises(MonitorError, match="could not claim workspace"):
        start_monitor(request)

    assert not sentinel.exists()
    artifacts_root = sase_projects_dir() / "proj" / "artifacts" / "ace-run"
    member_dirs = [
        p.parent
        for p in artifacts_root.glob("*/*/*/agent_meta.json")
        if p.parent != Path(starter_dir)
    ]
    assert len(member_dirs) == 1
    meta = json.loads((member_dirs[0] / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    assert meta["monitor_settled"] is True
    assert "monitor_pgid" not in meta
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

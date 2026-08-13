"""Tests for :mod:`sase.monitor.store`."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.monitor.models import MonitorLaneError, MonitorRecord, MonitorRefError
from sase.monitor.output import OutputCapture
from sase.monitor.start import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from sase.monitor.store import (
    active_monitor_for_lane,
    get_monitor,
    has_any_monitor,
    list_monitors,
    read_monitor_marker,
    reconcile_dead_supervisors,
    resolve_lane,
    resolve_monitor_ref,
    stop_monitor,
)
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import (
    DEAD_PID,
    make_starter_agent,
    patch_project_records,
    record_from_disk,
    write_project_file,
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
        monitor_settled=True,
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
        pid=os.getpid(),
    )
    patch_project_records(
        monkeypatch, [running_other_lane, terminal_same_lane, running_same_lane]
    )

    found = active_monitor_for_lane("proj", "acme")

    assert found is not None
    assert found.artifact_dir == running_same_lane


def test_active_monitor_for_lane_keeps_unsettled_terminal_meta_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsettled_same_lane = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="completed",
        monitor_settled=False,
    )
    patch_project_records(monkeypatch, [unsettled_same_lane])

    found = active_monitor_for_lane("proj", "acme")

    assert found is not None
    assert found.artifact_dir == unsettled_same_lane


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


def test_stop_monitor_treats_a_recycled_pid_as_dead_and_never_signals_it(
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
    # A real, live process stands in for the pid on disk, but its recorded
    # identity is rewritten below to simulate the OS having recycled that
    # pid for an unrelated process since the supervisor recorded it.
    child = subprocess.Popen(["sleep", "30"])
    real_kill = os.kill
    signaled: list[int] = []

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0:
            real_kill(pid, sig)
            return
        signaled.append(pid)

    import sase.monitor.identity as identity_module
    import sase.monitor.reconcile as reconcile_module

    monkeypatch.setattr(identity_module, "process_identity", lambda pid: "boot-b:2")
    monkeypatch.setattr(reconcile_module, "_current_boot_id", lambda: "boot-a")

    try:
        patch_project_records(monkeypatch, [monitor_dir])
        monkeypatch.setattr("os.kill", fake_kill)

        record = MonitorRecord.from_record(record_from_disk(monitor_dir))
        record = MonitorRecord(
            **{
                **record.__dict__,
                "pid": child.pid,
                "supervisor_identity": "boot-a:1",
            }
        )

        result = stop_monitor(record)

        assert signaled == []
        assert result is not None
        assert result.monitor_state == "failed"
        on_disk_done = json.loads((Path(monitor_dir) / "done.json").read_text())
        assert on_disk_done["error"].startswith(
            "monitor supervisor died without reporting"
        )
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
    assert on_disk_done["error"].startswith("monitor supervisor died without reporting")


def test_dead_supervisor_reconciliation_kills_tree_releases_claim_and_settles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.reconcile as reconcile_module

    child = subprocess.Popen(
        ["sh", "-c", "trap '' TERM; sleep 30 & wait"],
        start_new_session=True,
    )
    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(
                workspace_num=0,
                workflow=MONITOR_WORKSPACE_CLAIM_WORKFLOW,
                cl_name="acme",
                pid=DEAD_PID,
                artifacts_timestamp="20260812120000",
            )
        ],
    )
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
        monitor_pgid=child.pid,
        pid=DEAD_PID,
        workspace_num=0,
        workspace_dir="/work",
        cl_name="acme",
    )
    (Path(monitor_dir) / "live_reply.md").write_text("before crash\n")
    patch_project_records(monkeypatch, [monitor_dir])
    monkeypatch.setattr(reconcile_module, "_RECONCILE_KILL_GRACE_SECONDS", 0.05)

    try:
        record = MonitorRecord.from_record(record_from_disk(monitor_dir))

        result = stop_monitor(record)

        assert result.monitor_state == "failed"
        assert result.settled is True
        assert get_claimed_workspaces(project_file) == []
        on_disk_meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
        assert on_disk_meta["monitor_settled"] is True
        on_disk_done = json.loads((Path(monitor_dir) / "done.json").read_text())
        assert on_disk_done["monitor_state"] == "failed"
        assert on_disk_done["error"].startswith(
            "monitor supervisor died without reporting"
        )
        log_text = (Path(monitor_dir) / "live_reply.md").read_text()
        assert "before crash" in log_text
        assert "monitor supervisor died without reporting" in log_text
        child.wait(timeout=5)
        _wait_for_process_group_gone(child.pid)
    finally:
        if child.poll() is None:
            _kill_process_group(child.pid)
            child.wait(timeout=5)


def test_dead_supervisor_reconciliation_launches_recorded_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.settlement as settlement_module

    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
        monitor_command="just check-full",
        monitor_stop_status="MONITORED",
        monitor_next_action="fix the failure",
        monitor_pgid=DEAD_PID,
        pid=DEAD_PID,
        workspace_num=0,
        workspace_dir="/work",
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [monitor_dir])
    calls: list[dict[str, object]] = []

    def fake_launch_followup_agent(
        artifacts_dir: str,
        meta: dict[str, object],
        **kwargs: object,
    ) -> bool:
        capture = kwargs["capture"]
        assert isinstance(capture, OutputCapture)
        calls.append(
            {
                "artifacts_dir": artifacts_dir,
                "monitor_state": kwargs["monitor_state"],
                "output": capture.retained_text(),
                "transfer_from_pid": kwargs["transfer_from_pid"],
            }
        )
        meta["monitor_followup_agent"] = "acme--next"
        return True

    monkeypatch.setattr(
        settlement_module, "launch_followup_agent", fake_launch_followup_agent
    )

    record = MonitorRecord.from_record(record_from_disk(monitor_dir))
    result = stop_monitor(record)

    assert result.monitor_state == "failed"
    assert result.followup_agent == "acme--next"
    assert calls == [
        {
            "artifacts_dir": monitor_dir,
            "monitor_state": "failed",
            "output": "monitor supervisor died without reporting\n",
            "transfer_from_pid": DEAD_PID,
        }
    ]


def test_pre_reboot_monitor_reconciles_to_lost_without_followup_or_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.reconcile as reconcile_module
    from sase.monitor.settlement import LOST_FOLLOWUP_ERROR

    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(
                workspace_num=0,
                workflow=MONITOR_WORKSPACE_CLAIM_WORKFLOW,
                cl_name="acme",
                pid=DEAD_PID,
                artifacts_timestamp="20260812120000",
            )
        ],
    )
    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
        monitor_command="just check-full",
        monitor_stop_status="MONITORED",
        monitor_next_action="fix the failure",
        monitor_supervisor_identity="old-boot:123",
        monitor_pgid=12345,
        pid=DEAD_PID,
        workspace_num=0,
        workspace_dir="/work",
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [monitor_dir])
    signaled: list[tuple[int, int]] = []
    monkeypatch.setattr(reconcile_module, "_current_boot_id", lambda: "new-boot")
    monkeypatch.setattr(
        os,
        "killpg",
        lambda pgid, sig: signaled.append((pgid, sig)),
    )

    record = MonitorRecord.from_record(record_from_disk(monitor_dir))
    result = stop_monitor(record)

    assert result.monitor_state == "lost"
    assert result.status_bucket == "Failed"
    assert signaled == []
    done = json.loads((Path(monitor_dir) / "done.json").read_text())
    assert done["monitor_state"] == "lost"
    assert done["monitor_followup_error"] == LOST_FOLLOWUP_ERROR
    assert get_claimed_workspaces(project_file) == []


def test_list_monitors_reconciles_dead_supervisors(
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
        pid=DEAD_PID,
    )
    patch_project_records(monkeypatch, [monitor_dir])

    records = list_monitors(project="proj")

    assert [record.monitor_state for record in records] == ["failed"]
    assert (Path(monitor_dir) / "done.json").exists()


def test_reconcile_dead_supervisors_leaves_healthy_running_monitors_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = subprocess.Popen(["sleep", "30"])
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
        pid=child.pid,
    )
    patch_project_records(monkeypatch, [monitor_dir])

    try:
        reconciled = reconcile_dead_supervisors(project="proj")

        assert reconciled == []
        assert not (Path(monitor_dir) / "done.json").exists()
        meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
        assert meta["monitor_state"] == "running"
    finally:
        os.kill(child.pid, signal.SIGKILL)
        child.wait()


def test_get_monitor_returns_none_for_an_unknown_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_project_records(monkeypatch, [])
    assert get_monitor("proj", "/nowhere") is None


def test_read_monitor_marker_returns_none_for_a_missing_artifacts_dir(
    tmp_path: Path,
) -> None:
    assert read_monitor_marker("proj", str(tmp_path / "nowhere")) is None


def test_read_monitor_marker_does_not_query_the_artifact_index(
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

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read_monitor_marker must not query the artifact index")

    monkeypatch.setattr("sase.monitor.store._project_records", _fail)

    record = read_monitor_marker("proj", monitor_dir)

    assert record is not None
    assert record.monitor_id == "aaa"
    assert record.monitor_state == "running"
    assert record.command == "sleep 60"


def test_read_monitor_marker_reflects_a_settled_done_marker() -> None:
    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="completed",
        monitor_settled=True,
        monitor_command="true",
    )
    done_path = Path(monitor_dir) / "done.json"
    done_path.write_text(
        json.dumps({"outcome": "monitored", "monitor_state": "completed"}),
        encoding="utf-8",
    )

    record = read_monitor_marker("proj", monitor_dir)

    assert record is not None
    assert record.monitor_state == "completed"
    assert record.is_terminal is True


def test_list_monitors_defaults_to_every_project_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
    )
    newer = make_starter_agent(
        "other",
        "20260812130000",
        "beta--mon",
        agent_family="beta",
        agent_family_role="monitor",
        monitor_id="bbb",
        monitor_state="completed",
    )
    patch_project_records(monkeypatch, [older, newer])

    records = list_monitors()

    assert [record.monitor_id for record in records] == ["bbb", "aaa"]


def test_list_monitors_scopes_to_one_project(monkeypatch: pytest.MonkeyPatch) -> None:
    in_scope = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
    )
    out_of_scope = make_starter_agent(
        "other",
        "20260812130000",
        "beta--mon",
        agent_family="beta",
        agent_family_role="monitor",
        monitor_id="bbb",
        monitor_state="running",
    )
    patch_project_records(monkeypatch, [in_scope, out_of_scope])

    records = list_monitors(project="proj")

    assert [record.monitor_id for record in records] == ["aaa"]


def test_resolve_monitor_ref_matches_a_unique_id_prefix() -> None:
    records = [_fake_record(monitor_id="aaabbbcccddd", lane="acme")]

    resolved = resolve_monitor_ref("aaab", records)

    assert resolved.monitor_id == "aaabbbcccddd"


def test_resolve_monitor_ref_matches_the_exact_member_agent_name() -> None:
    records = [
        _fake_record(monitor_id="aaa", lane="acme", member_agent_name="acme--mon"),
        _fake_record(monitor_id="bbb", lane="beta", member_agent_name="beta--mon"),
    ]

    resolved = resolve_monitor_ref("acme--mon", records)

    assert resolved.monitor_id == "aaa"


def test_resolve_monitor_ref_prefers_the_active_monitor_for_a_lane() -> None:
    finished = _fake_record(
        monitor_id="aaa",
        lane="acme",
        timestamp="20260812120000",
        state="completed",
        settled=True,
    )
    active = _fake_record(
        monitor_id="bbb", lane="acme", timestamp="20260812110000", state="running"
    )
    records = [finished, active]

    resolved = resolve_monitor_ref("acme", records)

    assert resolved.monitor_id == "bbb"


def test_resolve_monitor_ref_falls_back_to_the_newest_when_a_lane_has_no_active_one() -> (
    None
):
    older = _fake_record(monitor_id="aaa", lane="acme", timestamp="20260812110000")
    newer = _fake_record(monitor_id="bbb", lane="acme", timestamp="20260812120000")

    resolved = resolve_monitor_ref("acme", [older, newer])

    assert resolved.monitor_id == "bbb"


def test_resolve_monitor_ref_rejects_an_empty_reference() -> None:
    with pytest.raises(MonitorRefError):
        resolve_monitor_ref("  ", [_fake_record(monitor_id="aaa", lane="acme")])


def test_resolve_monitor_ref_rejects_a_short_unknown_id_prefix() -> None:
    with pytest.raises(MonitorRefError):
        resolve_monitor_ref("zz", [_fake_record(monitor_id="aaa", lane="acme")])


def test_resolve_monitor_ref_reports_an_ambiguous_id_prefix() -> None:
    records = [
        _fake_record(monitor_id="aaabbb111111", lane="acme"),
        _fake_record(monitor_id="aaabbb222222", lane="beta"),
    ]

    with pytest.raises(MonitorRefError):
        resolve_monitor_ref("aaabbb", records)


def _fake_record(
    *,
    monitor_id: str,
    lane: str,
    member_agent_name: str | None = None,
    timestamp: str = "20260812120000",
    state: str = "running",
    settled: bool = False,
) -> MonitorRecord:
    return MonitorRecord(
        monitor_id=monitor_id,
        member_agent_name=member_agent_name or f"{lane}--mon",
        lane=lane,
        project_name="proj",
        artifacts_dir=f"/irrelevant/{monitor_id}",
        timestamp=timestamp,
        command="sleep 60",
        cwd="/work",
        reason="test",
        label="sleep",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=60.0,
        tail_lines=200,
        monitor_state=state,  # type: ignore[arg-type]
        settled=settled,
    )


def _with_meta_state(artifacts_dir: str, monitor_state: str) -> AgentArtifactRecordWire:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["monitor_state"] = monitor_state
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return record_from_disk(artifacts_dir)


def _kill_process_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _wait_for_process_group_gone(pgid: int) -> None:
    for _ in range(50):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)  # sase-test-wait: wait for the killed process group to vanish
    raise AssertionError(f"process group {pgid} is still alive")

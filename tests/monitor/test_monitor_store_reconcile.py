"""Tests for dead-supervisor reconciliation in :mod:`sase.monitor.store`."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)
from sase.monitor.models import MonitorRecord
from sase.monitor.output import OutputCapture
from sase.monitor.start import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from sase.monitor.store import (
    list_monitors,
    reconcile_dead_supervisors,
    stop_monitor,
)
from sase.notifications.store import load_notifications
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
        # Dead-supervisor reconciliation is notification-neutral: the
        # failure is discoverable via done.json/agent_meta.json above only.
        assert load_notifications() == []
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


def test_dead_supervisor_reconciliation_records_project_file_and_finalizes_workflow_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        monitor_pgid=DEAD_PID,
        pid=DEAD_PID,
        workspace_num=0,
        workspace_dir="/work",
        cl_name="acme",
    )
    workflow_state_path = Path(monitor_dir) / "workflow_state.json"
    workflow_state_path.write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "status": "running",
                "current_step_index": 0,
                "steps": [],
                "context": {"cl_name": "acme"},
                "artifacts_dir": monitor_dir,
                "pid": os.getpid(),
                "appears_as_agent": True,
            }
        ),
        encoding="utf-8",
    )
    patch_project_records(monkeypatch, [monitor_dir])

    record = MonitorRecord.from_record(record_from_disk(monitor_dir))
    result = stop_monitor(record)

    assert result.monitor_state == "failed"
    on_disk_done = json.loads((Path(monitor_dir) / "done.json").read_text())
    assert on_disk_done["project_file"] == project_file

    workflow_state = json.loads(workflow_state_path.read_text())
    assert workflow_state["status"] == "completed"
    assert workflow_state["appears_as_agent"] is True
    assert workflow_state["context"] == {"cl_name": "acme"}


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
    # A pre-reboot dropped follow-up remains diagnosable via done.json
    # above -- reconciliation must not also raise an alarm notification.
    assert load_notifications() == []


def test_reconcile_dead_supervisors_uses_bounded_active_monitor_index_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.store as store_module

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    calls: list[
        tuple[
            Path,
            Path,
            AgentArtifactIndexQueryWire,
            AgentArtifactScanOptionsWire,
        ]
    ] = []

    def fake_query(
        path: Path,
        projects_root: Path,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        calls.append((path, projects_root, query, options))
        return _empty_snapshot(projects_root, options)

    monkeypatch.setattr(
        store_module,
        "default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(store_module, "query_agent_artifact_index", fake_query)
    monkeypatch.setattr(
        store_module,
        "scan_agent_artifacts",
        lambda *_args, **_kwargs: pytest.fail("reconciliation should use the index"),
    )

    assert reconcile_dead_supervisors(project="proj") == []

    assert len(calls) == 1
    _, _, query, options = calls[0]
    assert query.include_active is True
    assert query.include_recent_completed is False
    assert query.include_full_history is False
    assert query.active_limit == 1000
    assert query.recent_completed_limit == 0
    assert query.include_hidden is True
    assert query.only_monitors is True
    assert options.only_workflow_dirs == ("ace-run",)
    assert options.include_prompt_step_markers is False
    assert options.include_raw_prompt_snippets is False
    assert options.only_projects == ("proj",)
    assert options.max_records == 0
    assert options.newest_first is True


def test_reconcile_dead_supervisors_fallback_scan_stays_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.store as store_module

    calls: list[tuple[Path, AgentArtifactScanOptionsWire]] = []

    def fake_scan(
        projects_root: Path,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        calls.append((projects_root, options))
        return _empty_snapshot(projects_root, options)

    monkeypatch.setattr(
        store_module,
        "default_agent_artifact_index_path",
        lambda: tmp_path / "missing.sqlite",
    )
    monkeypatch.setattr(store_module, "scan_agent_artifacts", fake_scan)

    assert reconcile_dead_supervisors(project="proj") == []

    assert len(calls) == 1
    _, options = calls[0]
    assert options.only_workflow_dirs == ("ace-run",)
    assert options.include_prompt_step_markers is False
    assert options.include_raw_prompt_snippets is False
    assert options.only_projects == ("proj",)
    assert options.max_records == 0
    assert options.newest_first is True


def test_list_monitors_keeps_full_history_listing_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.store as store_module
    import sase.procs.service as proc_service

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    calls: list[
        tuple[
            Path,
            Path,
            AgentArtifactIndexQueryWire,
            AgentArtifactScanOptionsWire,
        ]
    ] = []

    def fake_query(
        path: Path,
        projects_root: Path,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        calls.append((path, projects_root, query, options))
        return _empty_snapshot(projects_root, options)

    monkeypatch.setattr(proc_service, "reconcile_proc_shells", lambda: None)
    monkeypatch.setattr(
        store_module, "reconcile_dead_supervisors", lambda *, project: []
    )
    monkeypatch.setattr(
        store_module,
        "default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(store_module, "query_agent_artifact_index", fake_query)
    monkeypatch.setattr(
        store_module,
        "scan_agent_artifacts",
        lambda *_args, **_kwargs: pytest.fail("listing should use the index"),
    )

    assert list_monitors(project="proj") == []

    assert len(calls) == 1
    _, _, query, options = calls[0]
    assert query.include_active is True
    assert query.include_recent_completed is True
    assert query.include_full_history is True
    assert query.active_limit is None
    assert query.recent_completed_limit is None
    assert query.include_hidden is True
    assert query.only_monitors is True
    assert options.only_workflow_dirs == ("ace-run",)
    assert options.only_projects == ("proj",)
    assert options.max_records is None
    assert options.newest_first is False


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


def _make_monitor_record(**overrides: object) -> MonitorRecord:
    base: dict[str, object] = {
        "monitor_id": "aaa",
        "member_agent_name": "acme--mon",
        "lane": "acme",
        "project_name": "proj",
        "artifacts_dir": "/tmp/does-not-matter",
        "timestamp": "20260812120000",
        "command": "sleep 60",
        "cwd": "/work",
        "reason": "",
        "label": "",
        "start_status": "MONITORED",
        "stop_status": "MONITORED",
        "timeout_seconds": 0.0,
        "tail_lines": 0,
        "monitor_state": "running",
        "pid": 12345,
    }
    base.update(overrides)
    return MonitorRecord(**base)  # type: ignore[arg-type]


def test_should_reconcile_dead_supervisor_skips_proc_lookup_for_terminal_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cheap ``monitor_state``/``pid`` rejects must run before any proc I/O."""
    import sase.monitor.proc_adapter as proc_adapter_module
    from sase.monitor.reconcile import should_reconcile_dead_supervisor

    calls: list[str] = []

    def fake_proc_shell_owns(monitor_id: str) -> bool:
        calls.append(monitor_id)
        return False

    monkeypatch.setattr(proc_adapter_module, "proc_shell_owns", fake_proc_shell_owns)

    terminal_record = _make_monitor_record(monitor_state="completed", settled=True)
    assert should_reconcile_dead_supervisor(terminal_record) is False

    pidless_record = _make_monitor_record(monitor_state="running", pid=None)
    assert should_reconcile_dead_supervisor(pidless_record) is False

    assert calls == []


def _empty_snapshot(
    projects_root: Path,
    options: AgentArtifactScanOptionsWire,
) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(projects_root),
        options=options,
        stats=AgentArtifactScanStatsWire(),
        records=[],
    )


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

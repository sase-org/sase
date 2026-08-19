"""Facade tests: monitor start/list/show/stop over the shared proc service."""

from __future__ import annotations

import json
import os
import shlex
import signal
import sys
import time
from pathlib import Path

import pytest

from sase.monitor.models import MonitorRecord
from sase.monitor.proc_adapter import compile_monitor_argv
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.monitor.store import list_monitors, stop_monitor
from sase.procs.models import COMMAND_PROC_KIND
from sase.procs.store import get_proc
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from sase.core.paths import sase_projects_dir

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


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _patch_live_records(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.monitor import store as store_module

    def live_records(
        project_name: str | None, *, only_monitors: bool = False
    ) -> list[object]:
        records = []
        projects_root = sase_projects_dir()
        names = [project_name] if project_name else ["proj"]
        for name in names:
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

    monkeypatch.setattr(store_module, "_project_records", live_records)


def _start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    command: str,
    next_action: str | None = None,
    idle_timeout_seconds: float = 0.0,
    timeout_seconds: float = 30.0,
    timestamp: str = "20260812120000",
    inherit_lane_workspace_claim: bool = True,
) -> MonitorRecord:
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    make_starter_agent(
        "proj",
        timestamp,
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    _patch_live_records(monkeypatch)
    return start_monitor(
        StartMonitorRequest(
            command=command,
            reason="verify facade",
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
            next_action=next_action,
            inherit_lane_workspace_claim=inherit_lane_workspace_claim,
        )
    )


def test_compile_monitor_argv_is_explicit_sh_c() -> None:
    assert compile_monitor_argv("just check-full") == [
        "/bin/sh",
        "-c",
        "just check-full",
    ]


def test_start_uses_one_proc_id_and_artifacts_cross_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _start(tmp_path, monkeypatch, command="true")
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.proc_id == record.monitor_id
    assert proc.argv == ["/bin/sh", "-c", "true"]
    assert proc.origin == "monitor"
    assert proc.kind == COMMAND_PROC_KIND
    assert proc.shell_kind == "proc"
    assert proc.shell_name == "acme--mon"
    assert proc.log_owner == "artifacts"
    assert proc.log_path == str(Path(record.artifacts_dir) / "live_reply.md")

    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["shell_kind"] == "proc"
    assert meta["proc_id"] == record.monitor_id
    assert meta["monitor_id"] == record.monitor_id

    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"
    listed = list_monitors(project="proj")
    assert [item.monitor_id for item in listed] == [record.monitor_id]
    assert listed[0].monitor_state == "completed"


def test_stop_uses_the_proc_service_and_suppresses_followup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _start(
        tmp_path,
        monkeypatch,
        command="sleep 30",
        next_action="Inspect the result.",
    )
    stopped = stop_monitor(record)
    assert stopped.monitor_state == "stopped"
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.status == "killed"
    done = wait_for_done(record.artifacts_dir, timeout=10.0)
    assert done["monitor_state"] == "stopped"
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta.get("monitor_followup_outcome") in {None, "suppressed"}
    assert meta.get("monitor_followup_agent") is None


def test_quiet_command_retains_an_output_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiet = _start(tmp_path, monkeypatch, command="true")
    wait_for_done(quiet.artifacts_dir)
    assert Path(quiet.artifacts_dir, "live_reply.md").exists()


def test_invalid_utf8_output_is_retained_with_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid = _start(
        tmp_path,
        monkeypatch,
        command=_python_command(
            "import sys; sys.stdout.buffer.write(b'ok\\xff\\xfe done\\n')"
        ),
    )
    wait_for_done(invalid.artifacts_dir)
    text = Path(invalid.artifacts_dir, "live_reply.md").read_text(errors="replace")
    assert "ok" in text
    assert "done" in text


def test_background_grandchild_and_resistant_group_are_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    grandchild = tmp_path / "grandchild.pid"
    record = _start(
        tmp_path,
        monkeypatch,
        command=_python_command(
            "import os, signal, time, pathlib;"
            f"path = pathlib.Path({str(grandchild)!r});"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
            "child = os.fork();"
            "path.write_text(str(child if child else os.getpid()));"
            "time.sleep(30)"
        ),
        timeout_seconds=60.0,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not grandchild.exists():
            time.sleep(0.05)  # sase-test-wait: poll grandchild pid file
        stopped = stop_monitor(record)
        assert stopped.monitor_state == "stopped"
        wait_for_done(record.artifacts_dir, timeout=10.0)
    finally:
        if record.pid is not None:
            try:
                os.kill(record.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_historical_legacy_monitor_is_not_adopted_into_a_proc_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project_file("proj")
    make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="legacyid0001",
        monitor_command="echo legacy",
        monitor_cwd=str(tmp_path),
        monitor_reason="historical",
        monitor_state="running",
        monitor_settled=False,
        pid=99_999_999,
    )
    _patch_live_records(monkeypatch)

    records = list_monitors(project="proj")
    assert len(records) == 1
    assert records[0].monitor_id == "legacyid0001"
    assert get_proc("legacyid0001") is None


def test_claim_is_released_when_there_is_no_followup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_file = write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    _patch_live_records(monkeypatch)
    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify claim release",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
        )
    )
    wait_for_done(record.artifacts_dir)
    assert get_claimed_workspaces(project_file) == []

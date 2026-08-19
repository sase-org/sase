"""Supervisor-process behavior of :func:`sase.monitor.start.start_monitor`.

Covers the environment handed to the supervisor, its diagnostics log and
persisted identity, and the process-tree guarantees that keep a monitor alive
once the starter agent goes away.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import sys
from pathlib import Path
import pytest

from sase.monitor.start import (
    SUPERVISOR_LOG_NAME,
    StartMonitorRequest,
    start_monitor,
)
from sase.procs.runtime import proc_runtime_dir
from sase.running_field import WorkspaceClaim

from ._fixtures import (
    make_starter_agent,
    patch_project_records,
    wait_for_done,
    wait_for_path,
    write_project_file,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _proc_ppid(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    close_paren = stat.rfind(")")
    if close_paren < 0:
        return None
    fields = stat[close_paren + 1 :].split()
    try:
        return int(fields[1])
    except (IndexError, ValueError):
        return None


def _ancestor_pids(pid: int) -> list[int]:
    ancestors: list[int] = []
    seen: set[int] = set()
    current = pid
    while current not in seen:
        seen.add(current)
        ppid = _proc_ppid(current)
        if ppid is None:
            return ancestors
        ancestors.append(ppid)
        if ppid <= 1:
            return ancestors
        current = ppid
    return ancestors


def _descendant_pids(root_pid: int) -> list[int]:
    children_by_parent: dict[int, list[int]] = {}
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            pid = int(stat_path.parent.name)
        except ValueError:
            continue
        ppid = _proc_ppid(pid)
        if ppid is not None:
            children_by_parent.setdefault(ppid, []).append(pid)

    descendants: list[int] = []
    frontier = list(children_by_parent.get(root_pid, []))
    while frontier:
        pid = frontier.pop()
        descendants.append(pid)
        frontier.extend(children_by_parent.get(pid, []))
    return descendants


def _signal_descendants(root_pid: int, signum: signal.Signals) -> None:
    for pid in sorted(_descendant_pids(root_pid), reverse=True):
        try:
            os.kill(pid, signum)
        except (ProcessLookupError, PermissionError):
            pass


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

    import sase.procs.spawn as spawn_module

    real_popen = spawn_module.subprocess.Popen
    captured_env: dict[str, str] = {}

    def fake_popen(*args: object, **kwargs: object) -> object:
        env = kwargs.get("env")
        if isinstance(env, dict):
            captured_env.update(env)
        return real_popen(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)

    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        start_status="MONITORING",
        stop_status="MONITORED",
        lane="acme",
    )

    record = start_monitor(request)
    wait_for_done(record.artifacts_dir)

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

    import sase.procs.spawn as spawn_module

    real_popen = spawn_module.subprocess.Popen
    captured: dict[str, object] = {}

    def wrapping_popen(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return real_popen(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(spawn_module.subprocess, "Popen", wrapping_popen)

    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify diagnostics",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
            inherit_lane_workspace_claim=False,
        )
    )
    wait_for_done(record.artifacts_dir)

    log_path = proc_runtime_dir(record.monitor_id) / SUPERVISOR_LOG_NAME
    assert log_path.exists()
    assert captured["stderr"] == spawn_module.subprocess.STDOUT
    assert captured["stdin"] == spawn_module.subprocess.DEVNULL
    assert captured["start_new_session"] is True
    assert captured["close_fds"] is True
    assert captured["pass_fds"]


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
        start_status="MONITORING",
        stop_status="MONITORED",
        lane="acme",
    )

    record = start_monitor(request)
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    wait_for_done(record.artifacts_dir)

    # Empty is an accepted fallback on platforms without /proc identity
    # support; the field must at least have been written.
    assert "monitor_supervisor_identity" in meta


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="/proc ancestry is required")
def test_start_monitor_reparents_the_supervisor_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project_file("proj")
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    record = start_monitor(
        StartMonitorRequest(
            command="sleep 30",
            reason="verify reparenting",
            timeout_seconds=120.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
            inherit_lane_workspace_claim=False,
        )
    )

    try:
        assert record.pid is not None
        assert os.getpid() not in _ancestor_pids(record.pid)
    finally:
        if record.pid is not None:
            os.kill(record.pid, signal.SIGTERM)
        wait_for_done(record.artifacts_dir, timeout=10.0)


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="/proc ancestry is required")
def test_ppid_walk_teardown_of_starter_descendants_leaves_monitor_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project_file("proj")
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    command = _python_command(
        "import time; print('survived teardown', flush=True); "
        "time.sleep(0.2); print('finished', flush=True)"
    )

    record = start_monitor(
        StartMonitorRequest(
            command=command,
            reason="verify ppid walk survival",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
            inherit_lane_workspace_claim=False,
        )
    )

    _signal_descendants(os.getpid(), signal.SIGTERM)

    done = wait_for_done(record.artifacts_dir, timeout=10.0)
    assert done["monitor_state"] == "completed"
    live_reply = Path(record.artifacts_dir, "live_reply.md").read_text()
    assert "survived teardown" in live_reply
    assert "finished" in live_reply


def test_sighup_to_supervisor_does_not_stop_the_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_file = tmp_path / "ready"
    write_project_file("proj")
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    command = _python_command(
        f"from pathlib import Path; import time; "
        f"Path({str(ready_file)!r}).write_text('1'); "
        "print('ready', flush=True); time.sleep(0.5); print('done', flush=True)"
    )

    record = start_monitor(
        StartMonitorRequest(
            command=command,
            reason="verify sighup ignored",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
            inherit_lane_workspace_claim=False,
        )
    )

    assert record.pid is not None
    wait_for_path(ready_file, timeout=10.0)
    os.kill(record.pid, signal.SIGHUP)

    done = wait_for_done(record.artifacts_dir, timeout=10.0)
    assert done["monitor_state"] == "completed"
    live_reply = Path(record.artifacts_dir, "live_reply.md").read_text()
    assert "ready" in live_reply
    assert "done" in live_reply

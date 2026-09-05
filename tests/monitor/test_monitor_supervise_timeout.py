"""Timeout, idle, and process-tree tests for :mod:`sase.monitor.supervise`."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.monitor.supervise import run_supervisor
from sase.running_field import get_claimed_workspaces

from ._supervise import (
    _make_member,
    _restore_signal_handlers,
    _run_supervisor_subprocess,
    _sandbox_home,
    _terminate_pid,
)

_STOP_POLL_TIMEOUT = 60.0
_STOP_POLL_INTERVAL = 0.1


def test_run_supervisor_kills_the_whole_process_group_on_timeout(
    tmp_path: Path,
) -> None:
    pidfile = tmp_path / "grandchild.pid"
    command = f"sh -c 'sleep 30 & echo $! > {pidfile}; wait'"
    artifacts_dir, _ = _make_member(tmp_path, command=command, timeout_seconds=0.3)

    completed = _run_supervisor_subprocess(artifacts_dir)

    assert completed.returncode == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"

    grandchild_pid = int(pidfile.read_text().strip())
    assert not is_process_running(grandchild_pid)


def test_run_supervisor_times_out_continuous_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_MONITOR_LOG_MAX_BYTES", "4096")
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'while :; do echo chatty; done'",
        timeout_seconds=0.2,
    )

    completed = _run_supervisor_subprocess(artifacts_dir)

    assert completed.returncode == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert (Path(artifacts_dir) / "live_reply.md").stat().st_size <= 4096


def test_run_supervisor_times_out_after_partial_line(tmp_path: Path) -> None:
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'printf partial; sleep 30'",
        # Long enough for spawn+printf under load; the child still sleeps 30s
        # so this remains a timeout, not a completion.
        timeout_seconds=3.0,
    )

    completed = _run_supervisor_subprocess(artifacts_dir)

    assert completed.returncode == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert (Path(artifacts_dir) / "live_reply.md").read_text() == "partial"


def test_supervisor_subprocess_liveness_verdict_catches_a_wedged_driver(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sleep 0.2",
        timeout_seconds=30.0,
    )

    with pytest.raises(pytest.fail.Exception, match="did not exit within 0.5s"):
        _run_supervisor_subprocess(
            artifacts_dir,
            overrides={"_POLL_SECONDS": 60.0},
            liveness_timeout=0.5,
        )


def test_run_supervisor_completes_when_grandchild_holds_stdout(
    tmp_path: Path,
) -> None:
    pidfile = tmp_path / "grandchild.pid"
    command = f"sh -c 'sleep 30 & echo $! > {pidfile}; echo parent done'"
    artifacts_dir, _ = _make_member(tmp_path, command=command, timeout_seconds=30.0)

    try:
        completed = _run_supervisor_subprocess(artifacts_dir)

        assert completed.returncode == 0
        meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
        assert meta["monitor_state"] == "completed"
        assert "parent done" in (Path(artifacts_dir) / "live_reply.md").read_text()
    finally:
        if pidfile.exists():
            grandchild_pid = int(pidfile.read_text().strip())
            _terminate_pid(grandchild_pid)


def test_run_supervisor_times_out_after_child_closes_stdio(tmp_path: Path) -> None:
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'exec >/dev/null 2>&1; sleep 30'",
        timeout_seconds=0.2,
    )

    completed = _run_supervisor_subprocess(artifacts_dir)

    assert completed.returncode == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"


def test_run_supervisor_idle_timeout_fires_after_output_stalls(tmp_path: Path) -> None:
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'echo started; sleep 30'",
        timeout_seconds=30.0,
        idle_timeout_seconds=0.2,
    )

    completed = _run_supervisor_subprocess(artifacts_dir)

    assert completed.returncode == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert meta["monitor_timeout_kind"] == "idle"
    assert meta["monitor_timeout_message"] == "no output for 0.2s"
    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["monitor_timeout_kind"] == "idle"
    assert done["monitor_timeout_message"] == "no output for 0.2s"
    assert "started" in (Path(artifacts_dir) / "live_reply.md").read_text()


def test_run_supervisor_chatty_command_does_not_hit_idle_timeout(
    tmp_path: Path,
) -> None:
    command = (
        f'{shlex.quote(sys.executable)} -u -c "import sys, time; '
        "[(sys.stdout.write('tick\\\\n'), sys.stdout.flush(), time.sleep(0.05)) "
        'for _ in range(4)]"'
    )
    artifacts_dir, _ = _make_member(
        tmp_path,
        command=command,
        timeout_seconds=5.0,
        idle_timeout_seconds=0.2,
    )

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "completed"
    assert "monitor_timeout_kind" not in meta


def test_run_supervisor_quiet_command_without_idle_timeout_completes(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sleep 0.2",
        timeout_seconds=5.0,
    )

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "completed"


def test_run_supervisor_survives_invalid_utf8_output(tmp_path: Path) -> None:
    command = (
        f'{shlex.quote(sys.executable)} -c "import sys, time; '
        "sys.stdout.buffer.write(b'bad\\\\xff\\\\n'); "
        'sys.stdout.flush(); time.sleep(30)"'
    )
    artifacts_dir, _ = _make_member(tmp_path, command=command, timeout_seconds=0.2)

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert (Path(artifacts_dir) / "live_reply.md").read_bytes().startswith(b"bad\xff")


def test_run_supervisor_escalates_term_ignoring_chatty_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_MONITOR_LOG_MAX_BYTES", "4096")
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'trap \"\" TERM; while :; do echo stubborn; done'",
        timeout_seconds=0.2,
    )

    completed = _run_supervisor_subprocess(
        artifacts_dir, overrides={"_KILL_GRACE_SECONDS": 0.2}
    )

    assert completed.returncode == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert (Path(artifacts_dir) / "live_reply.md").stat().st_size <= 4096


def test_supervisor_subprocess_stops_cleanly_on_sigterm(tmp_path: Path) -> None:
    ready_file = tmp_path / "ready"
    artifacts_dir, project_file = _make_member(
        tmp_path, command=f"touch {ready_file} && sleep 30", timeout_seconds=120.0
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "sase.monitor.supervise",
            "--artifacts-dir",
            artifacts_dir,
        ],
        env=os.environ.copy(),
    )
    try:
        deadline = time.monotonic() + _STOP_POLL_TIMEOUT
        while not ready_file.exists() and time.monotonic() < deadline:
            time.sleep(_STOP_POLL_INTERVAL)
        assert ready_file.exists(), "monitored command never started"

        process.send_signal(signal.SIGTERM)
        process.wait(timeout=_STOP_POLL_TIMEOUT)

        meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
        assert meta["monitor_state"] == "stopped"
        done = json.loads((Path(artifacts_dir) / "done.json").read_text())
        assert done["monitor_state"] == "stopped"
        # A stopped monitor releases the claim -- no follow-up is launched.
        assert get_claimed_workspaces(project_file) == []
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_supervisor_subprocess_persists_monitor_pgid_while_the_command_runs(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _make_member(tmp_path, command="sleep 5", timeout_seconds=120.0)

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "sase.monitor.supervise",
            "--artifacts-dir",
            artifacts_dir,
        ],
        env=os.environ.copy(),
    )
    try:
        meta_path = Path(artifacts_dir) / "agent_meta.json"
        deadline = time.monotonic() + _STOP_POLL_TIMEOUT
        pgid: int | None = None
        while time.monotonic() < deadline:
            meta = json.loads(meta_path.read_text())
            if meta.get("monitor_state") == "running" and meta.get("monitor_pgid"):
                pgid = meta["monitor_pgid"]
                break
            time.sleep(_STOP_POLL_INTERVAL)

        assert pgid is not None, "monitor_pgid was never persisted while running"
        assert is_process_running(pgid)
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=_STOP_POLL_TIMEOUT)
